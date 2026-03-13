"""Generated-exam pipeline built from persisted candidate bundles."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import Field

from src.assembly.candidate_pool import (
    CandidatePoolBuildError,
    CandidatePoolBuildResult,
    CandidatePoolCandidateBundle,
    build_slot_plan,
)
from src.assembly.mini_alpha import (
    MiniAlphaAssembler,
    MiniAlphaManifestInput,
    MiniAlphaMetrics,
    MiniAlphaSelectionRecord,
)
from src.config.settings import get_settings
from src.core.schemas import ApprovalStatus, StrictModel, ValidationStatus
from src.eval.discard_rate import HumanReviewRecord
from src.eval.review_feedback import candidate_blocked_from_selection
from src.render.latex_renderer import RenderJobResult


class GeneratedExamPipelineError(RuntimeError):
    """Raised when the generated-exam pipeline cannot assemble a bundle."""


class LoadedCandidatePool(StrictModel):
    """Resolved candidate-pool inputs for one generated exam run."""

    spec_id: str
    title: str
    candidate_pool_dir: str
    candidate_pool_manifest_path: str | None = None
    provider_name: str | None = None
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    candidates: list[CandidatePoolCandidateBundle] = Field(default_factory=list)


class GeneratedExamResult(StrictModel):
    """Artifact summary returned by the generated-exam pipeline."""

    run_id: str
    spec_id: str
    title: str
    slot_count: int
    output_dir: str
    candidate_pool_dir: str
    candidate_pool_manifest_path: str | None = None
    provider_name: str | None = None
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    candidate_count: int
    eligible_candidate_count: int
    candidate_manifest_path: str
    exam_bundle_path: str
    discard_report_path: str
    exam_tex_path: str
    exam_pdf_path: str | None = None
    answer_key_tex_path: str
    answer_key_pdf_path: str | None = None
    validation_report_tex_path: str
    validation_report_pdf_path: str | None = None
    render_result: RenderJobResult
    metrics: MiniAlphaMetrics
    selected: list[MiniAlphaSelectionRecord] = Field(default_factory=list)


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, StrictModel):
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _relative_path(*, target: Path, start: Path) -> str:
    return os.path.relpath(target.resolve(), start=start.resolve())


def _eligible_candidate_count(candidates: list[CandidatePoolCandidateBundle]) -> int:
    return sum(
        1
        for candidate in candidates
        if candidate.approval_status == ApprovalStatus.APPROVED
        and candidate.validation_status == ValidationStatus.PASS
        and not candidate_blocked_from_selection(candidate.review_summary)
    )


class GeneratedExamPipeline:
    """Assemble a generated exam directly from candidate-pool bundle outputs."""

    def __init__(
        self,
        *,
        template_dir: Path | None = None,
        xelatex_path: str | None = None,
    ) -> None:
        settings = get_settings()
        self.repo_root = settings.repo_root
        self.assembler = MiniAlphaAssembler(
            template_dir=template_dir or (self.repo_root / "src" / "render" / "templates"),
            xelatex_path=xelatex_path or (
                str(settings.xelatex_path) if settings.xelatex_path else None
            ),
        )

    def load_candidate_pool(
        self,
        candidate_pool_dir: Path,
        *,
        expected_provider_name: str | None = None,
    ) -> LoadedCandidatePool:
        """Load generated candidate bundles from a candidate-pool output directory."""
        resolved_dir = candidate_pool_dir.resolve()
        manifest_path = resolved_dir / "candidate_pool_manifest.json"

        if manifest_path.exists():
            manifest = CandidatePoolBuildResult.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            candidates = manifest.candidates
            title = manifest.title
            spec_id = manifest.spec_id
            manifest_ref = str(manifest_path)
            provider_name = manifest.provider_name
            provider_settings = manifest.provider_settings
        else:
            candidates = self._scan_candidate_bundles(resolved_dir)
            title = "Generated Candidate Pool"
            spec_id = self.assembler.spec.spec_id
            manifest_ref = None
            provider_name = None
            provider_settings = {}

        if not candidates:
            raise GeneratedExamPipelineError(
                f"No candidate bundles found under {resolved_dir.as_posix()}"
            )

        if spec_id != self.assembler.spec.spec_id:
            raise GeneratedExamPipelineError(
                f"Candidate pool spec_id={spec_id} does not match assembler spec_id={self.assembler.spec.spec_id}"
            )
        if (
            expected_provider_name is not None
            and provider_name is not None
            and provider_name != expected_provider_name
        ):
            raise GeneratedExamPipelineError(
                f"Candidate pool provider_name={provider_name} does not match expected {expected_provider_name}"
            )

        return LoadedCandidatePool(
            spec_id=spec_id,
            title=title,
            candidate_pool_dir=str(resolved_dir),
            candidate_pool_manifest_path=manifest_ref,
            provider_name=provider_name,
            provider_settings=provider_settings,
            candidates=candidates,
        )

    def build_candidate_manifest(
        self,
        *,
        candidate_pool: LoadedCandidatePool,
        output_dir: Path,
        title: str,
        slot_count: int,
    ) -> tuple[MiniAlphaManifestInput, Path]:
        """Build and persist a generated candidate manifest from candidate bundles."""
        if slot_count < 1:
            raise GeneratedExamPipelineError("slot_count must be at least 1")

        try:
            slots = build_slot_plan(candidate_pool.candidates, slot_count)
        except CandidatePoolBuildError as exc:
            raise GeneratedExamPipelineError(
                f"Candidate pool cannot satisfy slot_count={slot_count}: {exc}"
            ) from exc

        manifest = MiniAlphaManifestInput(
            spec_id=candidate_pool.spec_id,
            title=title,
            slots=slots,
            candidates=[
                self._manifest_candidate_input(
                    candidate=candidate,
                    output_dir=output_dir,
                )
                for candidate in candidate_pool.candidates
            ],
        )
        manifest_path = _write_json(
            output_dir / "candidate_manifest.json",
            manifest.model_dump(mode="json"),
        )
        _write_json(
            output_dir / "slot_plan.json",
            [slot.model_dump(mode="json") for slot in slots],
        )
        return manifest, manifest_path

    def run(
        self,
        *,
        run_id: str,
        candidate_pool_dir: Path,
        output_dir: Path,
        slot_count: int = 15,
        title: str | None = None,
        compile_pdf: bool = True,
        real_item_validation_path: Path | None = None,
        human_reviews: list[HumanReviewRecord] | None = None,
        expected_provider_name: str | None = None,
    ) -> GeneratedExamResult:
        """Assemble and render a generated exam from persisted candidate bundles."""
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        candidate_pool = self.load_candidate_pool(
            candidate_pool_dir,
            expected_provider_name=expected_provider_name,
        )
        manifest, manifest_path = self.build_candidate_manifest(
            candidate_pool=candidate_pool,
            output_dir=output_dir,
            title=title or candidate_pool.title,
            slot_count=slot_count,
        )
        manifest = self.assembler.load_manifest(manifest_path)

        assembly_result = self.assembler.assemble(
            run_id=run_id,
            manifest=manifest,
            output_dir=output_dir,
            compile_pdf=compile_pdf,
            real_item_validation_path=real_item_validation_path,
            human_reviews=human_reviews,
        )

        exam_bundle_path = _write_json(
            output_dir / "exam_bundle.json",
            json.loads(Path(assembly_result.bundle_json_path).read_text(encoding="utf-8")),
        )
        discard_report_path = _write_json(
            output_dir / "discard_report.json",
            json.loads(Path(assembly_result.discard_rate_report_path).read_text(encoding="utf-8")),
        )

        document_by_kind = {
            document.kind: document for document in assembly_result.render_result.documents
        }
        exam_doc = document_by_kind["exam"]
        answer_key_doc = document_by_kind["answer_key"]
        validation_doc = document_by_kind["validation_report"]

        return GeneratedExamResult(
            run_id=run_id,
            spec_id=candidate_pool.spec_id,
            title=manifest.title,
            slot_count=len(manifest.slots or []),
            output_dir=str(output_dir),
            candidate_pool_dir=candidate_pool.candidate_pool_dir,
            candidate_pool_manifest_path=candidate_pool.candidate_pool_manifest_path,
            provider_name=candidate_pool.provider_name,
            provider_settings=candidate_pool.provider_settings,
            candidate_count=len(candidate_pool.candidates),
            eligible_candidate_count=_eligible_candidate_count(candidate_pool.candidates),
            candidate_manifest_path=str(manifest_path),
            exam_bundle_path=str(exam_bundle_path),
            discard_report_path=str(discard_report_path),
            exam_tex_path=exam_doc.tex_path,
            exam_pdf_path=exam_doc.pdf_path,
            answer_key_tex_path=answer_key_doc.tex_path,
            answer_key_pdf_path=answer_key_doc.pdf_path,
            validation_report_tex_path=validation_doc.tex_path,
            validation_report_pdf_path=validation_doc.pdf_path,
            render_result=assembly_result.render_result,
            metrics=assembly_result.metrics,
            selected=assembly_result.selected,
        )

    def _manifest_candidate_input(
        self,
        *,
        candidate: CandidatePoolCandidateBundle,
        output_dir: Path,
    ) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "validated_item_path": _relative_path(
                target=Path(candidate.validated_item_path),
                start=output_dir,
            ),
            "validator_report_path": _relative_path(
                target=Path(candidate.validator_report_path),
                start=output_dir,
            ),
            "source_run_id": candidate.run_id,
            "source_atom_id": candidate.source_atom_id,
            "family_id": candidate.family_id,
            "source_item_id": candidate.source_item_id,
            "source_item_no": candidate.source_item_no,
            "atom_signatures": candidate.atom_signatures,
            "distractor_signatures": candidate.distractor_signatures,
            "review_summary": (
                candidate.review_summary.model_dump(mode="json")
                if candidate.review_summary is not None
                else None
            ),
        }

    def _scan_candidate_bundles(self, candidate_pool_dir: Path) -> list[CandidatePoolCandidateBundle]:
        bundle_paths = sorted(candidate_pool_dir.glob("candidates/*/candidate_bundle.json"))
        return [
            CandidatePoolCandidateBundle.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
            for path in bundle_paths
        ]
