"""LaTeX renderer for exam, answer key, and validation report PDFs."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import Field

from src.core.schemas import RenderBundle, StrictModel, utc_now
from src.render.contracts import (
    InternalAnswerKeyEntry,
    InternalAnswerKeyRenderContext,
    InternalValidationReportContext,
    InternalValidationReportEntry,
    RendererConfig,
    StudentExamRenderContext,
    StudentRenderItem,
)
from src.render.diagram_builders import build_diagram_tex, infer_diagram_tag
from src.validators.report import ValidatorSuiteReport


MATH_TOKEN_PATTERN = re.compile(
    r"(?P<expr>(?:[A-Za-z][A-Za-z0-9]*\([^)]*\)|[A-Za-z0-9_]+)\s*(?:[=+\-*/^≤≥<>|]\s*[A-Za-z0-9_()./√]+)+)"
)


class RenderedDocument(StrictModel):
    """Metadata for one rendered LaTeX document."""

    kind: str
    template_name: str
    tex_path: str
    pdf_path: str | None = None
    compiled: bool = False
    compiler: str | None = None
    debug_message: str | None = None


class RenderJobResult(StrictModel):
    """Result bundle for one render command."""

    render_id: str = Field(default_factory=lambda: f"rdr-{utc_now().strftime('%Y%m%d%H%M%S%f')}")
    run_id: str
    spec_id: str
    bundle_artifact_id: str
    validator_suite_artifact_ids: list[str] = Field(default_factory=list)
    output_dir: str
    documents: list[RenderedDocument]
    rendered_at: str = Field(default_factory=lambda: utc_now().isoformat())


def _math_normalize(text: str) -> str:
    replacements = {
        "≤": r"\leq",
        "≥": r"\geq",
        "√": r"\sqrt",
        "∩": r"\cap",
        "∪": r"\cup",
        "∫": r"\int",
        "∑": r"\sum",
    }
    normalized = text
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"\\sqrt(\d+)", r"\\sqrt{\1}", normalized)
    return normalized


def escape_latex(text: str) -> str:
    """Escape text while preserving a small amount of inline math quality."""
    placeholders: list[str] = []

    def replace_math(match: re.Match[str]) -> str:
        expr = _math_normalize(match.group("expr"))
        placeholders.append(rf"\({expr}\)")
        return f"@@MATH{len(placeholders) - 1}@@"

    prepared = MATH_TOKEN_PATTERN.sub(replace_math, text)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    escaped = prepared
    for source, target in replacements.items():
        escaped = escaped.replace(source, target)

    for index, placeholder in enumerate(placeholders):
        escaped = escaped.replace(f"@@MATH{index}@@", placeholder)
    return escaped.replace("\n", r"\\ ")


class LaTeXRenderer:
    """Render exam documents to XeLaTeX-ready sources and PDFs."""

    def __init__(self, *, template_dir: Path, config: RendererConfig | None = None) -> None:
        self.template_dir = template_dir
        self.config = config or RendererConfig()
        self.environment = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            undefined=StrictUndefined,
        )

    def render_exam_set(
        self,
        *,
        run_id: str,
        bundle: RenderBundle,
        bundle_artifact_id: str,
        validator_reports: list[ValidatorSuiteReport],
        validator_suite_artifact_ids: list[str],
        output_dir: Path,
        compile_pdf: bool = True,
    ) -> RenderJobResult:
        """Render exam, answer key, and validation report sources."""
        output_dir.mkdir(parents=True, exist_ok=True)
        documents = [
            self.render_exam(bundle=bundle, output_dir=output_dir, compile_pdf=compile_pdf),
            self.render_answer_key(bundle=bundle, output_dir=output_dir, compile_pdf=compile_pdf),
            self.render_validation_report(
                bundle=bundle,
                validator_reports=validator_reports,
                output_dir=output_dir,
                compile_pdf=compile_pdf,
            ),
        ]
        result = RenderJobResult(
            run_id=run_id,
            spec_id=bundle.spec_id,
            bundle_artifact_id=bundle_artifact_id,
            validator_suite_artifact_ids=validator_suite_artifact_ids,
            output_dir=str(output_dir),
            documents=documents,
        )
        self.write_manifest(output_dir=output_dir, result=result)
        return result

    def render_exam(
        self, *, bundle: RenderBundle, output_dir: Path, compile_pdf: bool = True
    ) -> RenderedDocument:
        template_name = "exam.tex.j2"
        template = self.environment.get_template(template_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        tex_path = output_dir / "exam.tex"
        context = self._student_exam_context(bundle).model_dump(mode="json")
        tex_path.write_text(template.render(context), encoding="utf-8")
        return self._maybe_compile(
            tex_path,
            kind="exam",
            template_name=template_name,
            compile_pdf=compile_pdf,
        )

    def render_answer_key(
        self, *, bundle: RenderBundle, output_dir: Path, compile_pdf: bool = True
    ) -> RenderedDocument:
        template_name = "answer_key.tex.j2"
        template = self.environment.get_template(template_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        tex_path = output_dir / "answer_key.tex"
        context = self._internal_answer_key_context(bundle).model_dump(mode="json")
        tex_path.write_text(template.render(context), encoding="utf-8")
        return self._maybe_compile(
            tex_path,
            kind="answer_key",
            template_name=template_name,
            compile_pdf=compile_pdf,
        )

    def render_validation_report(
        self,
        *,
        bundle: RenderBundle,
        validator_reports: list[ValidatorSuiteReport],
        output_dir: Path,
        compile_pdf: bool = True,
    ) -> RenderedDocument:
        template_name = "validation_report.tex.j2"
        template = self.environment.get_template(template_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        tex_path = output_dir / "validation_report.tex"
        tex_path.write_text(
            template.render(
                self._internal_validation_context(bundle, validator_reports).model_dump(mode="json")
            ),
            encoding="utf-8",
        )
        return self._maybe_compile(
            tex_path,
            kind="validation_report",
            template_name=template_name,
            compile_pdf=compile_pdf,
        )

    def write_manifest(self, *, output_dir: Path, result: RenderJobResult) -> Path:
        """Write a JSON manifest next to the generated TeX/PDF outputs."""
        manifest_path = output_dir / "render_manifest.json"
        manifest_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return manifest_path

    def _student_exam_context(self, bundle: RenderBundle) -> StudentExamRenderContext:
        items = []
        for item in sorted(bundle.items, key=lambda entry: entry.solved.draft.blueprint.item_no):
            blueprint = item.solved.draft.blueprint
            items.append(
                StudentRenderItem(
                    item_no=blueprint.item_no,
                    score=blueprint.score,
                    format=blueprint.format.value,
                    stem=escape_latex(item.solved.draft.stem),
                    choices=[escape_latex(choice) for choice in item.solved.draft.choices],
                    diagram=build_diagram_tex(infer_diagram_tag(item)) or None,
                )
            )
        return StudentExamRenderContext(
            title=bundle.student_metadata["title"],
            duration_minutes=bundle.student_metadata["duration_minutes"],
            total_score=bundle.student_metadata["total_score"],
            items=items,
        )

    def _internal_answer_key_context(self, bundle: RenderBundle) -> InternalAnswerKeyRenderContext:
        answers = [
            InternalAnswerKeyEntry(
                item_no=item.solved.draft.blueprint.item_no,
                answer=escape_latex(item.solved.final_answer),
                score=item.solved.draft.blueprint.score,
                correct_choice_index=item.solved.correct_choice_index,
                correct_choice_value=escape_latex(item.solved.correct_choice_value)
                if item.solved.correct_choice_value is not None
                else None,
            )
            for item in sorted(bundle.items, key=lambda entry: entry.solved.draft.blueprint.item_no)
        ]
        return InternalAnswerKeyRenderContext(
            title=bundle.student_metadata["title"],
            generated_at=bundle.generated_at.isoformat(),
            answers=answers,
        )

    def _internal_validation_context(
        self, bundle: RenderBundle, validator_reports: list[ValidatorSuiteReport]
    ) -> InternalValidationReportContext:
        reports = []
        for report in sorted(validator_reports, key=lambda entry: entry.item_no):
            reports.append(
                InternalValidationReportEntry(
                    item_no=report.item_no,
                    status=report.final_report.status.value,
                    reason_codes=", ".join(report.final_report.reason_codes) or "-",
                    recommendation=report.final_report.regenerate_recommendation.value,
                    summary=escape_latex(report.final_report.summary),
                    difficulty_band=report.difficulty_estimate.predicted_band,
                    step_count=report.difficulty_estimate.expected_step_count,
                    concept_count=report.difficulty_estimate.concept_count,
                    branching_factor=report.difficulty_estimate.branching_factor,
                    solver_disagreement_score=report.difficulty_estimate.solver_disagreement_score,
                )
            )
        return InternalValidationReportContext(
            title=bundle.student_metadata["title"],
            generated_at=bundle.generated_at.isoformat(),
            reports=reports,
        )

    def _maybe_compile(
        self,
        tex_path: Path,
        *,
        kind: str,
        template_name: str,
        compile_pdf: bool,
    ) -> RenderedDocument:
        if not compile_pdf:
            return RenderedDocument(
                kind=kind,
                template_name=template_name,
                tex_path=str(tex_path),
                compiled=False,
                debug_message="compile_pdf disabled; only TeX source was generated.",
            )

        compiler = self._resolve_xelatex_path()
        if compiler is None:
            debug_message = (
                f"Configured xelatex_path was not found: {self.config.xelatex_path}"
                if self.config.xelatex_path
                else "xelatex not found. Install TeX Live or MacTeX with ko.TeX support."
            )
            return RenderedDocument(
                kind=kind,
                template_name=template_name,
                tex_path=str(tex_path),
                compiled=False,
                compiler=None,
                debug_message=debug_message,
            )

        command = [
            compiler,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(tex_path.parent),
            tex_path.name,
        ]
        combined_logs: list[str] = []
        for _ in range(2):
            result = subprocess.run(
                command,
                cwd=tex_path.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            combined_logs.append((result.stdout + "\n" + result.stderr).strip())
            if result.returncode != 0:
                break

        pdf_path = tex_path.with_suffix(".pdf")
        debug_message = "\n".join(log for log in combined_logs if log).strip()[:2000]
        return RenderedDocument(
            kind=kind,
            template_name=template_name,
            tex_path=str(tex_path),
            pdf_path=str(pdf_path) if pdf_path.exists() else None,
            compiled=pdf_path.exists() and (result.returncode == 0),
            compiler=compiler,
            debug_message=debug_message or None,
        )

    def _resolve_xelatex_path(self) -> str | None:
        """Resolve the XeLaTeX executable with config-first lookup."""
        if self.config.xelatex_path:
            configured_path = Path(self.config.xelatex_path).expanduser()
            if configured_path.is_file():
                return str(configured_path.resolve())
            return None
        return shutil.which("xelatex")
