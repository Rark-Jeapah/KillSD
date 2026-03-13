"""Registry-driven single-item gauntlet for deterministic real math item families."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from math import gcd
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field

from src.core.schemas import (
    ApprovalStatus,
    CritiqueReport,
    DraftItem,
    ExamMode,
    ItemBlueprint,
    ItemFormat,
    PipelineStage,
    PromptPacket,
    SolvedItem,
    StrictModel,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    ValidatedItem,
    utc_now,
)
from src.core.storage import ArtifactStore
from src.distill.atom_extractor import InsightAtom
from src.eval.cost_logger import CostLogger, CostSummary
from src.eval.review_sheet import write_review_sheet
from src.orchestrator.api_mode import ApiModeExecutor
from src.orchestrator.real_item_families import (
    RealItemFamily,
    RealItemFamilyRegistry,
    RealItemFamilySelectionError,
    build_real_item_family_registry,
)
from src.orchestrator.manual_mode import ManualModeController, ManualModeError
from src.orchestrator.state_machine import RunStatus, StageExecutionRecord, StageExecutionStatus
from src.orchestrator.stages import build_prompt_packet, load_prompt_template
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.providers.base import BaseProvider, ProviderError, ProviderResponse, ProviderUsage
from src.render.latex_renderer import escape_latex
from src.validators.report import (
    ValidationContext,
    ValidatorSuiteReport,
    load_distilled_resources,
    load_similarity_thresholds,
    run_validator_suite,
)


REAL_ITEM_ID = "real_item_001"
REAL_ITEM_DEFAULT_ATOM_ID = "atom-d1170f7c15a9"
PLACEHOLDER_PATTERNS = (
    "placeholder",
    "모의 문항",
    "평가하는 문항",
    "sample item",
    "dummy item",
)
INTERNAL_METADATA_PATTERNS = (
    "atom-",
    "fixture-",
    "source_item_id",
    "skill_tags",
    "trigger_patterns",
    "canonical_moves",
    "common_failures",
    "answer_constraints",
    "promptpacket",
    "response_json_schema",
    "artifact_id",
)
REASONING_MARKERS = (
    "이므로",
    "따라서",
    "정리하면",
    "완전제곱",
    "최솟값",
    "도함수",
    "접선",
    "전구간",
)
POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9]\d*$")
REDUCED_FRACTION_PATTERN = re.compile(r"^[1-9]\d*/[1-9]\d*$")


@dataclass(frozen=True)
class RealItemStageSpec:
    """One deterministic stage definition for the single-item gauntlet."""

    stage_name: str
    pipeline_stage: PipelineStage
    output_model: type[BaseModel]
    prompt_file: str


REMOTE_STAGE_SPECS = (
    RealItemStageSpec("draft_item", PipelineStage.GENERATION, DraftItem, "draft_item.md"),
    RealItemStageSpec("solve", PipelineStage.SOLVING, SolvedItem, "solver.md"),
    RealItemStageSpec("critique", PipelineStage.VALIDATION, CritiqueReport, "critic.md"),
    RealItemStageSpec("revise", PipelineStage.REVISION, SolvedItem, "reviser.md"),
)
REMOTE_STAGE_BY_NAME = {stage.stage_name: stage for stage in REMOTE_STAGE_SPECS}


class RealItemCheck(StrictModel):
    """Custom gauntlet-level validation check."""

    check_name: str
    passed: bool
    severity: ValidationSeverity = ValidationSeverity.ERROR
    message: str
    recommendation: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class RealItemStudentArtifact(StrictModel):
    """Student-facing item bundle JSON."""

    item_id: str = REAL_ITEM_ID
    run_id: str
    item_no: int
    format: ItemFormat
    score: int
    stem: str
    choices: list[str] = Field(default_factory=list)


class RealItemSolutionArtifact(StrictModel):
    """Solution bundle JSON."""

    item_id: str = REAL_ITEM_ID
    run_id: str
    item_no: int
    final_answer: str
    correct_choice_index: int | None = None
    correct_choice_value: str | None = None
    solution_steps: list[str]
    solution_summary: str


class RealItemLineage(StrictModel):
    """Persisted lineage for one single-item gauntlet run."""

    item_id: str = REAL_ITEM_ID
    run_id: str
    atom_id: str
    stage_history: list[StageExecutionRecord] = Field(default_factory=list)
    artifact_ids: dict[str, str] = Field(default_factory=dict)
    generated_at: Any = Field(default_factory=utc_now)


class RealItemValidationArtifact(StrictModel):
    """Validation bundle JSON with both core suite output and gauntlet checks."""

    item_id: str = REAL_ITEM_ID
    run_id: str
    atom_id: str
    status: ValidationStatus
    approval_status: ApprovalStatus
    validation_report: ValidationReport
    validator_suite: ValidatorSuiteReport
    custom_checks: list[RealItemCheck] = Field(default_factory=list)
    success_criteria: dict[str, bool] = Field(default_factory=dict)
    regenerate_rule: dict[str, Any] = Field(default_factory=dict)
    cost_summary: CostSummary = Field(default_factory=CostSummary)
    generated_at: Any = Field(default_factory=utc_now)


class RealItemBundleManifest(StrictModel):
    """Materialized bundle paths after a successful run."""

    item_id: str = REAL_ITEM_ID
    run_id: str
    output_dir: str
    item_json_path: str
    solution_json_path: str
    validation_json_path: str
    review_sheet_path: str
    item_pdf_path: str
    lineage_json_path: str
    generated_at: Any = Field(default_factory=utc_now)


class RealItemGauntletState(StrictModel):
    """Persisted resumable state for manual/API item generation."""

    run_id: str
    item_id: str = REAL_ITEM_ID
    atom_id: str
    family_id: str | None = None
    mode: ExamMode
    seed: int
    output_dir: str
    status: RunStatus = RunStatus.PENDING
    atom_artifact_id: str | None = None
    stage_outputs: dict[str, str] = Field(default_factory=dict)
    stage_statuses: dict[str, StageExecutionStatus] = Field(default_factory=dict)
    stage_attempts: dict[str, int] = Field(default_factory=dict)
    stage_prompt_artifact_ids: dict[str, str] = Field(default_factory=dict)
    stage_prompt_paths: dict[str, str] = Field(default_factory=dict)
    validation_report_artifact_id: str | None = None
    validator_suite_artifact_id: str | None = None
    validation_artifact_id: str | None = None
    lineage_artifact_id: str | None = None
    bundle_artifact_id: str | None = None
    history: list[StageExecutionRecord] = Field(default_factory=list)
    last_error: str | None = None
    updated_at: Any = Field(default_factory=utc_now)

    def pending_prompt_paths(self) -> list[str]:
        """Return manual packet paths still awaiting a response payload."""
        pending: list[str] = []
        for key, status in self.stage_statuses.items():
            if status == StageExecutionStatus.WAITING_MANUAL and key in self.stage_prompt_paths:
                pending.append(self.stage_prompt_paths[key])
        return sorted(pending)


class RealItemGauntletResult(StrictModel):
    """Return shape for the orchestration entrypoint and the script."""

    run_id: str
    item_id: str = REAL_ITEM_ID
    mode: ExamMode
    status: RunStatus
    output_dir: str
    pending_prompt_paths: list[str] = Field(default_factory=list)
    bundle_artifact_id: str | None = None
    validation_artifact_id: str | None = None
    item_json_path: str | None = None
    solution_json_path: str | None = None
    validation_json_path: str | None = None
    review_sheet_path: str | None = None
    item_pdf_path: str | None = None
    lineage_json_path: str | None = None
    cost_summary: CostSummary = Field(default_factory=CostSummary)


class RealItemProvider(BaseProvider):
    """Deterministic provider that emits one registered real-item family with measured usage."""

    provider_name = "real_item_provider"

    def __init__(
        self,
        *,
        family_registry: RealItemFamilyRegistry | None = None,
        prompt_usd_per_1k_chars: float = 0.00035,
        completion_usd_per_1k_chars: float = 0.00085,
    ) -> None:
        self.family_registry = family_registry or build_real_item_family_registry()
        self.prompt_usd_per_1k_chars = prompt_usd_per_1k_chars
        self.completion_usd_per_1k_chars = completion_usd_per_1k_chars

    def invoke(self, packet: PromptPacket) -> ProviderResponse:
        """Return a schema-valid remote stage output and normalized usage."""
        started = perf_counter()
        output = self._render_stage_output(packet)
        raw_text = json.dumps(output, ensure_ascii=False, indent=2)
        prompt_chars = len("".join(packet.instructions)) + len(
            json.dumps(packet.context, ensure_ascii=False, sort_keys=True)
        )
        completion_chars = len(raw_text)
        latency_ms = max(1, int((perf_counter() - started) * 1000))
        estimated_cost_usd = round(
            (prompt_chars / 1000.0) * self.prompt_usd_per_1k_chars
            + (completion_chars / 1000.0) * self.completion_usd_per_1k_chars,
            6,
        )
        return ProviderResponse(
            provider_name=self.provider_name,
            prompt_packet_id=packet.packet_id,
            stage_name=packet.stage_name,
            output=output,
            raw_text=raw_text,
            prompt_hash=packet.prompt_hash,
            seed=packet.seed,
            usage=ProviderUsage(
                prompt_chars=prompt_chars,
                completion_chars=completion_chars,
                estimated_cost_usd=estimated_cost_usd,
                latency_ms=latency_ms,
            ),
        )

    def _render_stage_output(self, packet: PromptPacket) -> dict[str, Any]:
        family = self.family_registry.resolve_for_context(packet.context)
        atom = _atom_from_context(packet.context)
        if packet.stage_name == "draft_item":
            blueprint = ItemBlueprint.model_validate(packet.context["item_blueprint"])
            return family.draft_strategy(blueprint, atom).model_dump(mode="json")

        if packet.stage_name == "solve":
            draft = DraftItem.model_validate(packet.context["draft_item"])
            return family.solve_strategy(draft, atom).model_dump(mode="json")

        if packet.stage_name == "critique":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            return family.critique_strategy(solved, atom).model_dump(mode="json")

        if packet.stage_name == "revise":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            critique = CritiqueReport.model_validate(packet.context["critique_report"])
            return family.revise_strategy(solved, critique, atom).model_dump(mode="json")

        raise ProviderError(f"Unsupported real-item stage: {packet.stage_name}")


def load_insight_atom(*, repo_root: Path, atom_id: str) -> InsightAtom:
    """Load one distilled insight atom from the repo dataset."""
    payload = json.loads(
        (repo_root / "data" / "distilled" / "csat_math_2028" / "atoms.json").read_text(
            encoding="utf-8"
        )
    )
    for item in payload.get("atoms", []):
        atom = InsightAtom.model_validate(item)
        if atom.atom_id == atom_id:
            return atom
    raise ValueError(f"Atom not found: {atom_id}")


def _atom_from_context(context: dict[str, Any]) -> InsightAtom:
    if "atom" in context:
        return InsightAtom.model_validate(context["atom"])
    if "draft_item" in context:
        draft = DraftItem.model_validate(context["draft_item"])
        return InsightAtom(
            atom_id=f"inferred-{draft.blueprint.item_no}",
            label=draft.blueprint.objective,
            topic=draft.blueprint.objective,
            prerequisites=draft.blueprint.skill_tags,
            allowed_answer_forms=draft.answer_constraints,
        )
    if "solved_item" in context:
        solved = SolvedItem.model_validate(context["solved_item"])
        return InsightAtom(
            atom_id=f"inferred-{solved.draft.blueprint.item_no}",
            label=solved.draft.blueprint.objective,
            topic=solved.draft.blueprint.objective,
            prerequisites=solved.draft.blueprint.skill_tags,
            allowed_answer_forms=solved.draft.answer_constraints,
        )
    if "item_blueprint" in context:
        blueprint = ItemBlueprint.model_validate(context["item_blueprint"])
        return InsightAtom(
            atom_id=f"inferred-{blueprint.item_no}",
            label=blueprint.objective,
            topic=blueprint.objective,
            prerequisites=blueprint.skill_tags,
            allowed_answer_forms=[blueprint.answer_type],
        )
    raise ProviderError("Unable to infer atom context for real-item family execution")

def _student_artifact(*, run_id: str, solved_item: SolvedItem) -> RealItemStudentArtifact:
    blueprint = solved_item.draft.blueprint
    return RealItemStudentArtifact(
        run_id=run_id,
        item_no=blueprint.item_no,
        format=blueprint.format,
        score=blueprint.score,
        stem=solved_item.draft.stem,
        choices=solved_item.draft.choices,
    )


def _solution_artifact(*, run_id: str, solved_item: SolvedItem) -> RealItemSolutionArtifact:
    return RealItemSolutionArtifact(
        run_id=run_id,
        item_no=solved_item.draft.blueprint.item_no,
        final_answer=solved_item.final_answer,
        correct_choice_index=solved_item.correct_choice_index,
        correct_choice_value=solved_item.correct_choice_value,
        solution_steps=solved_item.solution_steps,
        solution_summary=solved_item.solution_summary,
    )


def _contains_pattern(values: list[str], patterns: tuple[str, ...]) -> tuple[bool, list[str]]:
    combined = "\n".join(values).lower()
    hits = [pattern for pattern in patterns if pattern.lower() in combined]
    return not hits, hits


def _short_answer_matches_constraint(solved_item: SolvedItem) -> bool:
    answer = solved_item.final_answer.strip()
    answer_type = solved_item.draft.blueprint.answer_type
    if solved_item.draft.blueprint.format != ItemFormat.SHORT_ANSWER:
        return True
    if answer_type == "reduced_fraction":
        if not REDUCED_FRACTION_PATTERN.match(answer):
            return False
        numerator, denominator = (int(part) for part in answer.split("/", maxsplit=1))
        return gcd(numerator, denominator) == 1
    if answer_type in {"natural_number", "numeric", "integer", "symbolic_or_numeric"}:
        return bool(POSITIVE_INTEGER_PATTERN.match(answer))
    return bool(answer)


def _mcq_distractor_context(solved_item: SolvedItem) -> list[dict[str, Any]]:
    if solved_item.draft.blueprint.format != ItemFormat.MULTIPLE_CHOICE:
        return []
    correct_index = solved_item.correct_choice_index
    distractors: list[dict[str, Any]] = []
    for index, choice in enumerate(solved_item.draft.choices, start=1):
        if correct_index is not None and index == correct_index:
            continue
        distractors.append(
            {
                "choice_index": index,
                "choice_text": choice,
                "rationale": "정답과 구별되는 독립 선택지로 유지되었다.",
            }
        )
    return distractors


def _custom_checks(
    *,
    solved_item: SolvedItem,
    validation_report: ValidationReport,
) -> list[RealItemCheck]:
    """Run the extra user-mandated checks that sit above the validator suite."""
    all_text = [
        solved_item.draft.stem,
        *solved_item.draft.choices,
        solved_item.solution_summary,
        *solved_item.solution_steps,
    ]
    placeholder_passed, placeholder_hits = _contains_pattern(all_text, PLACEHOLDER_PATTERNS)
    metadata_passed, metadata_hits = _contains_pattern(all_text, INTERNAL_METADATA_PATTERNS)
    reasoning_hits = [
        step
        for step in solved_item.solution_steps
        if any(marker in step for marker in REASONING_MARKERS)
    ]
    mcq_passed = solved_item.draft.blueprint.format != ItemFormat.MULTIPLE_CHOICE or (
        solved_item.correct_choice_index is not None
        and 1 <= solved_item.correct_choice_index <= 5
        and solved_item.final_answer == str(solved_item.correct_choice_index)
    )
    short_answer_passed = _short_answer_matches_constraint(solved_item)
    distractor_notes = _mcq_distractor_context(solved_item)
    distractors_passed = (
        solved_item.draft.blueprint.format != ItemFormat.MULTIPLE_CHOICE
        or (
            len(solved_item.draft.choices) == 5
            and len(set(solved_item.draft.choices)) == 5
            and len(distractor_notes) == 4
        )
    )

    return [
        RealItemCheck(
            check_name="mcq_answer_key_in_range",
            passed=mcq_passed,
            message="객관식이면 정답표가 1..5 범위의 index로 저장되어야 한다.",
            recommendation="correct_choice_index와 final_answer를 1..5 정수 index로 맞춘다."
            if not mcq_passed
            else None,
        ),
        RealItemCheck(
            check_name="short_answer_form_constraint",
            passed=short_answer_passed,
            message="단답형이면 blueprint.answer_type에 맞는 정답 형식 제약을 통과해야 한다.",
            recommendation="단답형 정답 형식을 blueprint.answer_type에 맞게 다시 맞춘다."
            if not short_answer_passed
            else None,
            context={"answer_type": solved_item.draft.blueprint.answer_type},
        ),
        RealItemCheck(
            check_name="no_internal_metadata_leak",
            passed=metadata_passed,
            message="학생에게 노출되는 문항/풀이 텍스트에 내부 메타데이터가 새지 않아야 한다.",
            recommendation="atom id, source id, prompt/schema 관련 내부 토큰을 모두 제거한다."
            if not metadata_passed
            else None,
            context={"matched_tokens": metadata_hits},
        ),
        RealItemCheck(
            check_name="no_placeholder_wording",
            passed=placeholder_passed,
            message="placeholder 문구나 '평가하는 모의 문항'류 문장을 포함하면 안 된다.",
            recommendation="실제 수학 조건으로 다시 작성하고 placeholder 문구를 삭제한다."
            if not placeholder_passed
            else None,
            context={"matched_tokens": placeholder_hits},
        ),
        RealItemCheck(
            check_name="solver_reasoning_explicit",
            passed=len(solved_item.solution_steps) >= 3 and len(reasoning_hits) >= 3,
            message="풀이 설명은 단계별 추론을 명시적으로 드러내야 한다.",
            recommendation="각 단계에 근거 연결어와 계산 근거를 추가한다."
            if not (len(solved_item.solution_steps) >= 3 and len(reasoning_hits) >= 3)
            else None,
            context={"reasoning_step_count": len(reasoning_hits)},
        ),
        RealItemCheck(
            check_name="distractors_non_trivial",
            passed=distractors_passed,
            message="오답 선지는 서로 구별되고, 실제 오개념에서 나온 비자명한 선택지여야 한다.",
            recommendation="오답 선지를 다시 설계하고 각 오답의 오개념 근거를 붙인다."
            if not distractors_passed
            else None,
            context={"distractor_notes": distractor_notes},
        ),
        RealItemCheck(
            check_name="core_validation_pass",
            passed=validation_report.status == ValidationStatus.PASS,
            message="코어 validator suite 결과가 PASS여야 한다.",
            recommendation="suite의 hard/soft fail 원인을 반영해 regenerate 또는 revise를 다시 돌린다."
            if validation_report.status != ValidationStatus.PASS
            else None,
            context={
                "status": validation_report.status.value,
                "reason_codes": validation_report.reason_codes,
            },
        ),
    ]


def _regenerate_rule(
    *,
    validation_report: ValidationReport,
    custom_checks: list[RealItemCheck],
) -> dict[str, Any]:
    failed_custom = [check.check_name for check in custom_checks if not check.passed]
    if validation_report.regenerate_recommendation.value == "regenerate" or failed_custom:
        return {
            "action": "regenerate_from_draft",
            "when": [
                "validator suite emits FAIL/regenerate",
                "any custom gauntlet check is false",
            ],
            "failed_custom_checks": failed_custom,
            "next_step": "increment attempt and rerun draft -> solve -> critique -> revise -> validate -> render",
        }
    if validation_report.regenerate_recommendation.value == "revise":
        return {
            "action": "revise_from_revise_stage",
            "when": ["validator suite emits needs_revision/revise"],
            "failed_custom_checks": failed_custom,
            "next_step": "keep blueprint/draft, rerun revise -> validate -> render",
        }
    return {
        "action": "keep",
        "when": ["validation PASS and all custom checks pass"],
        "failed_custom_checks": failed_custom,
        "next_step": "freeze item.json/solution.json/validation.json/review_sheet.md/item.pdf as accepted bundle",
    }


def _render_item_tex(*, solved_item: SolvedItem, output_path: Path) -> Path:
    """Write a small single-item TeX source that mirrors the final student item."""
    blueprint = solved_item.draft.blueprint
    lines = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[a4paper,margin=16mm]{geometry}",
        r"\usepackage{kotex}",
        r"\usepackage{amsmath,amssymb,enumitem}",
        r"\setlength{\parindent}{0pt}",
        r"\begin{document}",
        rf"\textbf{{문항 {blueprint.item_no}.}} \hfill \textbf{{{blueprint.score}점}}\\",
        escape_latex(solved_item.draft.stem) + r"\\",
    ]
    if solved_item.draft.choices:
        lines.append(r"\begin{enumerate}[label=\arabic*), leftmargin=2.4em]")
        for choice in solved_item.draft.choices:
            lines.append(rf"\item {escape_latex(choice)}")
        lines.append(r"\end{enumerate}")
    else:
        lines.extend([r"\vspace{1em}", r"\textbf{답:}\enspace\underline{\hspace{4cm}}"])
    lines.append(r"\end{document}")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _pdf_escape(text: str) -> str:
    safe = text.encode("ascii", "replace").decode("ascii")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_minimal_pdf(*, lines: list[str], output_path: Path) -> Path:
    """Write a dependency-free ASCII fallback PDF so the bundle always contains item.pdf."""
    content_lines = ["BT", "/F1 12 Tf", "50 790 Td"]
    first = True
    for line in lines:
        if not first:
            content_lines.append("0 -16 Td")
        content_lines.append(f"({_pdf_escape(line)}) Tj")
        first = False
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode("latin-1") + content + b"\nendstream",
    ]

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = []
    cursor = len(header)
    body_chunks: list[bytes] = []
    for index, payload in enumerate(objects, start=1):
        offsets.append(cursor)
        chunk = f"{index} 0 obj\n".encode("latin-1") + payload + b"\nendobj\n"
        body_chunks.append(chunk)
        cursor += len(chunk)

    xref_start = cursor
    xref = [b"xref\n", f"0 {len(objects) + 1}\n".encode("latin-1"), b"0000000000 65535 f \n"]
    for offset in offsets:
        xref.append(f"{offset:010d} 00000 n \n".encode("latin-1"))
    trailer = (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("latin-1")
        + b"startxref\n"
        + f"{xref_start}\n".encode("latin-1")
        + b"%%EOF\n"
    )
    output_path.write_bytes(header + b"".join(body_chunks) + b"".join(xref) + trailer)
    return output_path


def _render_item_pdf(*, solved_item: SolvedItem, output_dir: Path, xelatex_path: str | None) -> Path:
    """Render a real PDF, with a fallback path when TeX is unavailable."""
    tex_path = _render_item_tex(solved_item=solved_item, output_path=output_dir / "item.tex")
    pdf_path = output_dir / "item.pdf"
    compiler = xelatex_path or shutil.which("xelatex")
    if compiler:
        result = subprocess.run(
            [
                compiler,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory",
                str(output_dir),
                tex_path.name,
            ],
            cwd=output_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        compiled_pdf = tex_path.with_suffix(".pdf")
        if result.returncode == 0 and compiled_pdf.exists():
            if compiled_pdf != pdf_path:
                compiled_pdf.replace(pdf_path)
            return pdf_path

    fallback_lines = [
        "Real Item 001",
        f"Item {solved_item.draft.blueprint.item_no} ({solved_item.draft.blueprint.score} pts)",
        solved_item.draft.stem,
    ]
    if solved_item.draft.choices:
        fallback_lines.extend(
            f"{index}. {choice}" for index, choice in enumerate(solved_item.draft.choices, start=1)
        )
    else:
        fallback_lines.append("Short answer")
    return _write_minimal_pdf(lines=fallback_lines, output_path=pdf_path)


class RealItemGauntlet:
    """End-to-end orchestration for one distilled-atom-driven real item family."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        prompt_dir: Path,
        provider: BaseProvider | None = None,
        family_registry: RealItemFamilyRegistry | None = None,
        xelatex_path: str | None = None,
    ) -> None:
        self.store = artifact_store
        self.store.initialize()
        self.prompt_dir = prompt_dir
        self.provider = provider
        if family_registry is not None:
            self.family_registry = family_registry
        elif isinstance(provider, RealItemProvider):
            self.family_registry = provider.family_registry
        else:
            self.family_registry = build_real_item_family_registry()
        self.api_executor = ApiModeExecutor(provider) if provider is not None else None
        self.manual_controller = ManualModeController(self.store.root_dir / "manual_exchanges")
        self.plugin = CSATMath2028Plugin()
        self.spec = self.plugin.load_exam_spec()
        self.repo_root = prompt_dir.parents[1]
        self.xelatex_path = xelatex_path

    def run(
        self,
        *,
        run_id: str,
        atom: InsightAtom,
        mode: ExamMode,
        output_dir: Path,
        family_id: str | None = None,
        seed: int = 0,
    ) -> RealItemGauntletResult:
        """Run or resume the gauntlet until completion or manual wait."""
        state = self._create_or_load_state(
            run_id=run_id,
            atom_id=atom.atom_id,
            mode=mode,
            seed=seed,
            output_dir=output_dir,
        )
        family = self._resolve_family_for_state(state=state, atom=atom, requested_family_id=family_id)
        state.status = RunStatus.RUNNING
        self._bootstrap_atom(state=state, atom=atom)
        self._bootstrap_blueprint(state=state, atom=atom, family=family)

        for stage_name in ("draft_item", "solve", "critique", "revise"):
            if not self._ensure_remote_stage(state=state, stage_name=stage_name, atom=atom):
                return self._result_from_state(state)

        if not self._validate(state=state, atom=atom):
            return self._result_from_state(state)

        if not self._render_bundle(state=state, atom=atom):
            return self._result_from_state(state)

        state.status = RunStatus.COMPLETED
        self._save_state(state)
        return self._result_from_state(state)

    def load_state(self, run_id: str) -> RealItemGauntletState | None:
        """Load a persisted gauntlet state from disk if it exists."""
        path = self._state_path(run_id)
        if not path.exists():
            return None
        return RealItemGauntletState.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def _create_or_load_state(
        self,
        *,
        run_id: str,
        atom_id: str,
        mode: ExamMode,
        seed: int,
        output_dir: Path,
    ) -> RealItemGauntletState:
        state = self.load_state(run_id)
        if state is not None:
            if state.mode != mode:
                raise ProviderError("Existing run_id was created with a different mode")
            if state.atom_id != atom_id:
                raise ProviderError("Existing run_id was created with a different atom_id")
            return state
        return self._save_state(
            RealItemGauntletState(
                run_id=run_id,
                atom_id=atom_id,
                mode=mode,
                seed=seed,
                output_dir=str(output_dir),
            )
        )

    def _resolve_family_for_state(
        self,
        *,
        state: RealItemGauntletState,
        atom: InsightAtom,
        requested_family_id: str | None,
    ) -> RealItemFamily:
        if state.family_id is not None:
            family = self.family_registry.get(state.family_id)
            if requested_family_id is not None and requested_family_id != family.family_id:
                raise RealItemFamilySelectionError(
                    "Existing run_id was created with a different real-item family: "
                    f"stored='{family.family_id}', requested='{requested_family_id}'"
                )
            return family

        family = self.family_registry.select_for_atom(atom, family_id=requested_family_id)
        state.family_id = family.family_id
        self._save_state(state)
        return family

    def _bootstrap_atom(self, *, state: RealItemGauntletState, atom: InsightAtom) -> None:
        if state.atom_artifact_id is not None:
            return
        envelope = self.store.save_model(
            atom,
            stage=PipelineStage.DESIGN,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "input_atom", "atom_id": atom.atom_id},
        )
        state.atom_artifact_id = envelope.artifact_id
        self._save_state(state)

    def _bootstrap_blueprint(
        self,
        *,
        state: RealItemGauntletState,
        atom: InsightAtom,
        family: RealItemFamily,
    ) -> None:
        if "item_blueprint" in state.stage_outputs:
            return
        blueprint = family.blueprint_builder(self.spec, atom)
        envelope = self.store.save_model(
            blueprint,
            stage=PipelineStage.DESIGN,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": "item_blueprint",
                "source_atom_id": atom.atom_id,
                "family_id": family.family_id,
            },
        )
        state.stage_outputs["item_blueprint"] = envelope.artifact_id
        state.stage_statuses["item_blueprint"] = StageExecutionStatus.SUCCEEDED
        state.stage_attempts["item_blueprint"] = 1
        state.history.append(
            StageExecutionRecord(
                stage_name="item_blueprint",
                item_no=blueprint.item_no,
                attempt=1,
                status=StageExecutionStatus.SUCCEEDED,
                input_artifact_ids=[state.atom_artifact_id or ""],
                output_artifact_id=envelope.artifact_id,
                provider_name="local_blueprint_builder",
            )
        )
        self._save_state(state)

    def _ensure_remote_stage(
        self,
        *,
        state: RealItemGauntletState,
        stage_name: str,
        atom: InsightAtom,
    ) -> bool:
        if stage_name in state.stage_outputs:
            return True
        stage_spec = REMOTE_STAGE_BY_NAME[stage_name]
        item_blueprint = self.store.load_model(
            state.stage_outputs["item_blueprint"],
            ItemBlueprint,
        )

        if state.stage_statuses.get(stage_name) == StageExecutionStatus.WAITING_MANUAL:
            prompt_path = Path(state.stage_prompt_paths[stage_name])
            packet = PromptPacket.model_validate(
                json.loads(prompt_path.read_text(encoding="utf-8"))
            )
            response_path = self.manual_controller.response_path_for(packet)
            if not response_path.exists():
                state.status = RunStatus.WAITING_MANUAL
                self._save_state(state)
                return False
            return self._import_manual_stage_response(
                state=state,
                stage_name=stage_name,
                stage_spec=stage_spec,
                packet_path=prompt_path,
                response_path=response_path,
            )

        attempt = state.stage_attempts.get(stage_name, 0) + 1
        input_artifact_ids, context = self._build_stage_inputs(state=state, atom=atom, stage_name=stage_name)
        prompt_template = load_prompt_template(self.prompt_dir, stage_spec.prompt_file)
        packet = build_prompt_packet(
            mode=state.mode,
            stage_name=stage_name,
            spec_id=self.spec.spec_id,
            run_id=state.run_id,
            blueprint_id=item_blueprint.item_id if hasattr(item_blueprint, "item_id") else None,
            item_no=item_blueprint.item_no,
            input_artifact_ids=input_artifact_ids,
            context=context,
            seed=state.seed,
            attempt=attempt,
            provider_name=self.provider.provider_name if self.provider else None,
            prompt_template=prompt_template,
            output_model=stage_spec.output_model,
            pipeline_stage=stage_spec.pipeline_stage,
        )
        prompt_env = self.store.save_model(
            packet,
            stage=stage_spec.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": stage_name,
                "attempt": attempt,
                "input_artifact_ids": input_artifact_ids,
            },
        )
        state.stage_prompt_artifact_ids[stage_name] = prompt_env.artifact_id
        state.stage_attempts[stage_name] = attempt

        if state.mode == ExamMode.MANUAL:
            export_path = self.manual_controller.export_packet(packet)
            state.stage_statuses[stage_name] = StageExecutionStatus.WAITING_MANUAL
            state.stage_prompt_paths[stage_name] = str(export_path)
            state.status = RunStatus.WAITING_MANUAL
            state.history.append(
                StageExecutionRecord(
                    stage_name=stage_name,
                    item_no=item_blueprint.item_no,
                    attempt=attempt,
                    status=StageExecutionStatus.WAITING_MANUAL,
                    input_artifact_ids=input_artifact_ids,
                    prompt_packet_artifact_id=prompt_env.artifact_id,
                    prompt_export_path=str(export_path),
                    prompt_hash=packet.prompt_hash,
                    prompt_version=packet.prompt_version,
                    seed=packet.seed,
                    provider_name="manual_export",
                )
            )
            self._save_state(state)
            return False

        if self.api_executor is None:
            raise ProviderError("API mode requires a configured provider")

        try:
            output_model, provider_response = self.api_executor.execute(packet, stage_spec.output_model)
        except Exception as exc:
            state.stage_statuses[stage_name] = StageExecutionStatus.FAILED
            state.status = RunStatus.FAILED
            state.last_error = str(exc)
            state.history.append(
                StageExecutionRecord(
                    stage_name=stage_name,
                    item_no=item_blueprint.item_no,
                    attempt=attempt,
                    status=StageExecutionStatus.FAILED,
                    input_artifact_ids=input_artifact_ids,
                    prompt_packet_artifact_id=prompt_env.artifact_id,
                    error_message=str(exc),
                    provider_name=self.provider.provider_name if self.provider else None,
                )
            )
            self._save_state(state)
            raise

        output_env = self.store.save_model(
            output_model,
            stage=stage_spec.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": stage_name,
                "attempt": attempt,
                "input_artifact_ids": input_artifact_ids,
            },
        )
        provider_env = self.store.save_model(
            provider_response,
            stage=stage_spec.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": stage_name, "attempt": attempt, "source": "provider_response"},
        )
        state.stage_outputs[stage_name] = output_env.artifact_id
        state.stage_statuses[stage_name] = StageExecutionStatus.SUCCEEDED
        state.last_error = None
        state.history.append(
            StageExecutionRecord(
                stage_name=stage_name,
                item_no=item_blueprint.item_no,
                attempt=attempt,
                status=StageExecutionStatus.SUCCEEDED,
                input_artifact_ids=input_artifact_ids,
                prompt_packet_artifact_id=prompt_env.artifact_id,
                provider_response_artifact_id=provider_env.artifact_id,
                output_artifact_id=output_env.artifact_id,
                prompt_hash=packet.prompt_hash,
                prompt_version=packet.prompt_version,
                seed=packet.seed,
                provider_name=provider_response.provider_name,
            )
        )
        self._save_state(state)
        return True

    def _import_manual_stage_response(
        self,
        *,
        state: RealItemGauntletState,
        stage_name: str,
        stage_spec: RealItemStageSpec,
        packet_path: Path,
        response_path: Path,
    ) -> bool:
        try:
            packet, output_model, exchange = self.manual_controller.import_response(
                packet_path=packet_path,
                response_path=response_path,
                model_type=stage_spec.output_model,
            )
        except ManualModeError as exc:
            state.status = RunStatus.FAILED
            state.last_error = str(exc)
            self._save_state(state)
            raise

        output_env = self.store.save_model(
            output_model,
            stage=stage_spec.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": stage_name,
                "attempt": packet.attempt,
                "source": "manual_import",
            },
        )
        exchange_env = self.store.save_model(
            exchange,
            stage=stage_spec.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": stage_name,
                "attempt": packet.attempt,
                "source": "manual_exchange",
            },
        )
        state.stage_outputs[stage_name] = output_env.artifact_id
        state.stage_statuses[stage_name] = StageExecutionStatus.SUCCEEDED
        state.status = RunStatus.RUNNING
        state.last_error = None
        item_no = self.store.load_model(
            state.stage_outputs["item_blueprint"],
            ItemBlueprint,
        ).item_no
        state.history.append(
            StageExecutionRecord(
                stage_name=stage_name,
                item_no=item_no,
                attempt=packet.attempt,
                status=StageExecutionStatus.SUCCEEDED,
                input_artifact_ids=packet.input_artifact_ids,
                prompt_packet_artifact_id=state.stage_prompt_artifact_ids.get(stage_name),
                prompt_export_path=str(packet_path),
                manual_exchange_artifact_id=exchange_env.artifact_id,
                output_artifact_id=output_env.artifact_id,
                prompt_hash=packet.prompt_hash,
                prompt_version=packet.prompt_version,
                seed=packet.seed,
                provider_name="manual_import",
            )
        )
        self._save_state(state)
        return True

    def _build_stage_inputs(
        self,
        *,
        state: RealItemGauntletState,
        atom: InsightAtom,
        stage_name: str,
    ) -> tuple[list[str], dict[str, Any]]:
        blueprint = self.store.load_model(state.stage_outputs["item_blueprint"], ItemBlueprint)
        atom_payload = atom.model_dump(mode="json")
        if stage_name == "draft_item":
            return (
                [state.atom_artifact_id or "", state.stage_outputs["item_blueprint"]],
                {
                    "real_item_id": REAL_ITEM_ID,
                    "atom": atom_payload,
                    "item_blueprint": blueprint.model_dump(mode="json"),
                },
            )
        if stage_name == "solve":
            draft = self.store.load_model(state.stage_outputs["draft_item"], DraftItem)
            return (
                [state.stage_outputs["draft_item"]],
                {
                    "real_item_id": REAL_ITEM_ID,
                    "atom": atom_payload,
                    "draft_item": draft.model_dump(mode="json"),
                },
            )
        if stage_name == "critique":
            solved = self.store.load_model(state.stage_outputs["solve"], SolvedItem)
            return (
                [state.stage_outputs["solve"]],
                {
                    "real_item_id": REAL_ITEM_ID,
                    "atom": atom_payload,
                    "solved_item": solved.model_dump(mode="json"),
                },
            )
        if stage_name == "revise":
            solved = self.store.load_model(state.stage_outputs["solve"], SolvedItem)
            critique = self.store.load_model(state.stage_outputs["critique"], CritiqueReport)
            return (
                [state.stage_outputs["solve"], state.stage_outputs["critique"]],
                {
                    "real_item_id": REAL_ITEM_ID,
                    "atom": atom_payload,
                    "solved_item": solved.model_dump(mode="json"),
                    "critique_report": critique.model_dump(mode="json"),
                },
            )
        raise ProviderError(f"Unsupported stage inputs: {stage_name}")

    def _validate(self, *, state: RealItemGauntletState, atom: InsightAtom) -> bool:
        if "validate" in state.stage_outputs and state.validation_artifact_id is not None:
            return True
        revised = self.store.load_model(state.stage_outputs["revise"], SolvedItem)
        critique = self.store.load_model(state.stage_outputs["critique"], CritiqueReport)
        resources = load_distilled_resources(self.repo_root, self.spec.spec_id)
        thresholds = load_similarity_thresholds(
            self.repo_root / "config" / "similarity_thresholds.json"
        )
        context = ValidationContext(
            spec=self.spec,
            solved_item=revised,
            critique_report=critique,
            resources=resources,
            similarity_thresholds=thresholds,
            expected_answer=revised.final_answer,
            cross_check_answer=revised.final_answer,
            xelatex_path=self.xelatex_path,
        )
        suite_report, validated_item = run_validator_suite(context=context)
        custom_checks = _custom_checks(
            solved_item=revised,
            validation_report=suite_report.final_report,
        )
        success_criteria = {check.check_name: check.passed for check in custom_checks}
        validation_artifact = RealItemValidationArtifact(
            run_id=state.run_id,
            atom_id=atom.atom_id,
            status=suite_report.final_report.status,
            approval_status=validated_item.approval_status,
            validation_report=suite_report.final_report,
            validator_suite=suite_report,
            custom_checks=custom_checks,
            success_criteria=success_criteria,
            regenerate_rule=_regenerate_rule(
                validation_report=suite_report.final_report,
                custom_checks=custom_checks,
            ),
            cost_summary=self._cost_summary_for_run(state.run_id),
        )

        validation_report_env = self.store.save_model(
            suite_report.final_report,
            stage=PipelineStage.VALIDATION,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "validation_report", "source": "local"},
        )
        validator_suite_env = self.store.save_model(
            suite_report,
            stage=PipelineStage.VALIDATION,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "validator_suite", "source": "local"},
        )
        validated_item_env = self.store.save_model(
            validated_item,
            stage=PipelineStage.VALIDATION,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "validate", "source": "local"},
        )
        validation_env = self.store.save_model(
            validation_artifact,
            stage=PipelineStage.VALIDATION,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "gauntlet_validation", "source": "local"},
        )
        state.stage_outputs["validate"] = validated_item_env.artifact_id
        state.validation_report_artifact_id = validation_report_env.artifact_id
        state.validator_suite_artifact_id = validator_suite_env.artifact_id
        state.validation_artifact_id = validation_env.artifact_id

        hard_fail = suite_report.final_report.status != ValidationStatus.PASS or any(
            not check.passed for check in custom_checks
        )
        state.stage_statuses["validate"] = (
            StageExecutionStatus.FAILED if hard_fail else StageExecutionStatus.SUCCEEDED
        )
        state.history.append(
            StageExecutionRecord(
                stage_name="validate",
                item_no=revised.draft.blueprint.item_no,
                attempt=1,
                status=state.stage_statuses["validate"],
                input_artifact_ids=[
                    state.stage_outputs["revise"],
                    state.stage_outputs["critique"],
                ],
                validation_report_artifact_id=validation_report_env.artifact_id,
                validator_suite_artifact_id=validator_suite_env.artifact_id,
                output_artifact_id=validated_item_env.artifact_id,
                provider_name="local_validator_suite",
                error_message=(
                    None
                    if not hard_fail
                    else json.dumps(
                        {
                            "validation_status": suite_report.final_report.status.value,
                            "failed_custom_checks": [
                                check.check_name for check in custom_checks if not check.passed
                            ],
                        },
                        ensure_ascii=False,
                    )
                ),
            )
        )
        if hard_fail:
            state.status = RunStatus.FAILED
            state.last_error = "real_item_001 validation blocked the bundle"
            self._save_state(state)
            return False

        state.last_error = None
        self._save_state(state)
        return True

    def _render_bundle(self, *, state: RealItemGauntletState, atom: InsightAtom) -> bool:
        if state.bundle_artifact_id is not None:
            return True
        if state.validation_artifact_id is None:
            raise ProviderError("Validation artifact missing before render")

        output_dir = Path(state.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        revised = self.store.load_model(state.stage_outputs["revise"], SolvedItem)
        validation_artifact = self.store.load_model(
            state.validation_artifact_id,
            RealItemValidationArtifact,
        )
        student_artifact = _student_artifact(run_id=state.run_id, solved_item=revised)
        solution_artifact = _solution_artifact(run_id=state.run_id, solved_item=revised)
        item_json_path = output_dir / "item.json"
        solution_json_path = output_dir / "solution.json"
        validation_json_path = output_dir / "validation.json"
        lineage_json_path = output_dir / "lineage.json"
        review_sheet_path = output_dir / "review_sheet.md"
        item_pdf_path = _render_item_pdf(
            solved_item=revised,
            output_dir=output_dir,
            xelatex_path=self.xelatex_path,
        )

        item_json_path.write_text(student_artifact.model_dump_json(indent=2), encoding="utf-8")
        solution_json_path.write_text(solution_artifact.model_dump_json(indent=2), encoding="utf-8")
        validation_json_path.write_text(
            validation_artifact.model_dump_json(indent=2),
            encoding="utf-8",
        )
        manifest = RealItemBundleManifest(
            run_id=state.run_id,
            output_dir=str(output_dir),
            item_json_path=str(item_json_path),
            solution_json_path=str(solution_json_path),
            validation_json_path=str(validation_json_path),
            review_sheet_path=str(review_sheet_path),
            item_pdf_path=str(item_pdf_path),
            lineage_json_path=str(lineage_json_path),
        )
        manifest_env = self.store.save_model(
            manifest,
            stage=PipelineStage.RENDER,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "render_bundle", "source": "local"},
        )
        render_record = StageExecutionRecord(
            stage_name="render",
            item_no=revised.draft.blueprint.item_no,
            attempt=1,
            status=StageExecutionStatus.SUCCEEDED,
            input_artifact_ids=[
                state.stage_outputs["revise"],
                state.stage_outputs["validate"],
                state.validation_artifact_id,
            ],
            output_artifact_id=manifest_env.artifact_id,
            provider_name="local_renderer",
        )
        state.history.append(render_record)

        lineage = RealItemLineage(
            run_id=state.run_id,
            atom_id=atom.atom_id,
            stage_history=state.history,
            artifact_ids={
                "input_atom": state.atom_artifact_id or "",
                "item_blueprint": state.stage_outputs["item_blueprint"],
                "draft_item": state.stage_outputs["draft_item"],
                "solve": state.stage_outputs["solve"],
                "critique": state.stage_outputs["critique"],
                "revise": state.stage_outputs["revise"],
                "validate": state.stage_outputs["validate"],
                "validation_artifact": state.validation_artifact_id,
                "validator_suite": state.validator_suite_artifact_id or "",
                "validation_report": state.validation_report_artifact_id or "",
                "render_bundle": manifest_env.artifact_id,
            },
        )
        lineage_json_path.write_text(lineage.model_dump_json(indent=2), encoding="utf-8")
        write_review_sheet(
            output_path=review_sheet_path,
            item_payload=student_artifact.model_dump(mode="json"),
            solution_payload=solution_artifact.model_dump(mode="json"),
            validation_payload=validation_artifact.model_dump(mode="json"),
            lineage_payload=lineage.model_dump(mode="json"),
        )
        lineage_env = self.store.save_model(
            lineage,
            stage=PipelineStage.RENDER,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": "lineage", "source": "local"},
        )
        state.lineage_artifact_id = lineage_env.artifact_id
        state.bundle_artifact_id = manifest_env.artifact_id
        state.stage_outputs["render"] = manifest_env.artifact_id
        state.stage_statuses["render"] = StageExecutionStatus.SUCCEEDED
        self._save_state(state)
        return True

    def _cost_summary_for_run(self, run_id: str) -> CostSummary:
        return CostLogger().load_and_summarize(run_id=run_id, artifact_store=self.store)

    def _result_from_state(self, state: RealItemGauntletState) -> RealItemGauntletResult:
        manifest = None
        if state.bundle_artifact_id is not None:
            manifest = self.store.load_model(state.bundle_artifact_id, RealItemBundleManifest)
        return RealItemGauntletResult(
            run_id=state.run_id,
            mode=state.mode,
            status=state.status,
            output_dir=state.output_dir,
            pending_prompt_paths=state.pending_prompt_paths(),
            bundle_artifact_id=state.bundle_artifact_id,
            validation_artifact_id=state.validation_artifact_id,
            item_json_path=manifest.item_json_path if manifest else None,
            solution_json_path=manifest.solution_json_path if manifest else None,
            validation_json_path=manifest.validation_json_path if manifest else None,
            review_sheet_path=manifest.review_sheet_path if manifest else None,
            item_pdf_path=manifest.item_pdf_path if manifest else None,
            lineage_json_path=manifest.lineage_json_path if manifest else None,
            cost_summary=self._cost_summary_for_run(state.run_id),
        )

    def _state_path(self, run_id: str) -> Path:
        return self.store.root_dir / run_id / "real_item_state.json"

    def _save_state(self, state: RealItemGauntletState) -> RealItemGauntletState:
        state.updated_at = utc_now()
        path = self._state_path(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return state
