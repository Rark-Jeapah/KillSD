"""Benchmark pass/fail scorecards and audit helpers."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from src.core.schemas import FailureLevel, StrictModel
from src.core.storage import ArtifactStore
from src.orchestrator.state_machine import OrchestrationState
from src.render.latex_renderer import RenderJobResult
from src.validators.report import ValidatorSuiteReport


REMOTE_STAGE_NAMES = {
    "exam_blueprint",
    "item_blueprint",
    "draft_item",
    "solve",
    "critique",
    "revise",
}


class ScoreCheck(StrictModel):
    """One release-gate check with pass/fail status."""

    name: str
    passed: bool
    detail: str


class ArtifactAudit(StrictModel):
    """Reference integrity for a benchmark run."""

    referenced_artifact_ids: list[str] = Field(default_factory=list)
    missing_artifact_ids: list[str] = Field(default_factory=list)
    passed: bool = True


class PromptVersionAudit(StrictModel):
    """Prompt version and hash stability audit."""

    stage_versions: dict[str, list[str]] = Field(default_factory=dict)
    stage_hashes: dict[str, list[str]] = Field(default_factory=dict)
    missing_prompt_metadata: list[str] = Field(default_factory=list)
    passed: bool = True


class ModeComparisonReport(StrictModel):
    """Comparison report for manual vs API outputs."""

    group_id: str
    api_run_id: str
    manual_run_id: str
    equivalent: bool
    differences: list[str] = Field(default_factory=list)


class ReproducibilityReport(StrictModel):
    """Comparison report for same-seed replays."""

    group_id: str
    baseline_run_id: str
    replay_run_id: str
    seed: int
    equivalent: bool
    differences: list[str] = Field(default_factory=list)


class RunScorecard(StrictModel):
    """Run-level release gate summary."""

    run_id: str
    mode: str
    structure_errors: int
    answer_errors: int
    render_errors: int
    hard_similarity_collisions: int
    prompt_version_audit: PromptVersionAudit
    artifact_audit: ArtifactAudit
    checks: list[ScoreCheck]
    passed: bool


class BenchmarkScorecard(StrictModel):
    """Aggregate benchmark scorecard across multiple runs."""

    dataset_id: str
    case_count: int
    successful_case_count: int
    structure_errors: int
    answer_errors: int
    render_errors: int
    hard_similarity_collisions: int
    seed_reproducible: bool
    artifact_lineage_reproducible: bool
    manual_api_equivalent: bool
    checks: list[ScoreCheck]
    passed: bool


def build_artifact_audit(
    *, state: OrchestrationState, artifact_store: ArtifactStore
) -> ArtifactAudit:
    """Verify that every referenced artifact id can still be resolved."""
    referenced_ids = {
        artifact_id
        for artifact_id in [
            state.exam_spec_artifact_id,
            state.render_bundle_artifact_id,
            *state.stage_outputs.values(),
            *state.stage_prompt_artifact_ids.values(),
        ]
        if artifact_id
    }
    for record in state.history:
        for artifact_id in (
            [*record.input_artifact_ids]
            + [
                record.prompt_packet_artifact_id,
                record.provider_response_artifact_id,
                record.manual_exchange_artifact_id,
                record.validation_report_artifact_id,
                record.validator_suite_artifact_id,
                record.output_artifact_id,
            ]
        ):
            if artifact_id:
                referenced_ids.add(artifact_id)

    missing_ids: list[str] = []
    for artifact_id in sorted(referenced_ids):
        try:
            artifact_store.load_artifact(artifact_id)
        except Exception:
            missing_ids.append(artifact_id)

    return ArtifactAudit(
        referenced_artifact_ids=sorted(referenced_ids),
        missing_artifact_ids=missing_ids,
        passed=not missing_ids,
    )


def build_prompt_version_audit(state: OrchestrationState) -> PromptVersionAudit:
    """Verify that prompt version/hash metadata is present and stable per stage."""
    stage_versions: dict[str, set[str]] = {}
    stage_hashes: dict[str, set[str]] = {}
    missing: list[str] = []

    for record in state.history:
        if record.stage_name not in REMOTE_STAGE_NAMES:
            continue
        label = f"{record.stage_name}:{record.item_no}" if record.item_no is not None else record.stage_name
        if not record.prompt_version or not record.prompt_hash:
            missing.append(label)
            continue
        stage_versions.setdefault(record.stage_name, set()).add(record.prompt_version)
        stage_hashes.setdefault(record.stage_name, set()).add(record.prompt_hash)

    passed = not missing and all(len(values) == 1 for values in stage_versions.values()) and all(
        len(values) == 1 for values in stage_hashes.values()
    )
    return PromptVersionAudit(
        stage_versions={stage: sorted(values) for stage, values in stage_versions.items()},
        stage_hashes={stage: sorted(values) for stage, values in stage_hashes.items()},
        missing_prompt_metadata=sorted(missing),
        passed=passed,
    )


def build_run_scorecard(
    *,
    state: OrchestrationState,
    validator_reports: list[ValidatorSuiteReport],
    render_result: RenderJobResult | None,
    artifact_store: ArtifactStore,
    compile_pdf: bool,
) -> RunScorecard:
    """Build a release-gate scorecard for one benchmarked run."""
    structure_errors = 0
    answer_errors = 0
    render_errors = 0
    hard_similarity_collisions = 0

    for report in validator_reports:
        for finding in report.final_report.findings:
            if finding.passed:
                continue
            if finding.reason_code.startswith(("format.", "curriculum.")):
                structure_errors += 1
            if finding.reason_code.startswith("answer."):
                answer_errors += 1
            if finding.reason_code.startswith("render."):
                render_errors += 1
            if finding.reason_code.startswith("similarity.") and finding.failure_level == FailureLevel.HARD:
                hard_similarity_collisions += 1

    if render_result is not None:
        for document in render_result.documents:
            document_path = Path(document.tex_path)
            if not document_path.exists():
                render_errors += 1
                continue
            if compile_pdf and (
                not document.compiled
                or document.pdf_path is None
                or not Path(document.pdf_path).exists()
            ):
                render_errors += 1

    artifact_audit = build_artifact_audit(state=state, artifact_store=artifact_store)
    prompt_audit = build_prompt_version_audit(state)
    checks = [
        ScoreCheck(
            name="구조 오류 0",
            passed=structure_errors == 0,
            detail=f"structural findings={structure_errors}",
        ),
        ScoreCheck(
            name="정답 오류 0",
            passed=answer_errors == 0,
            detail=f"answer findings={answer_errors}",
        ),
        ScoreCheck(
            name="render 오류 0",
            passed=render_errors == 0,
            detail=f"render findings={render_errors}",
        ),
        ScoreCheck(
            name="hard similarity collision 0",
            passed=hard_similarity_collisions == 0,
            detail=f"hard similarity collisions={hard_similarity_collisions}",
        ),
        ScoreCheck(
            name="prompt version audit",
            passed=prompt_audit.passed,
            detail=f"missing_prompt_metadata={len(prompt_audit.missing_prompt_metadata)}",
        ),
        ScoreCheck(
            name="artifact lineage audit",
            passed=artifact_audit.passed,
            detail=f"missing_artifacts={len(artifact_audit.missing_artifact_ids)}",
        ),
    ]
    return RunScorecard(
        run_id=state.run_id,
        mode=state.mode.value,
        structure_errors=structure_errors,
        answer_errors=answer_errors,
        render_errors=render_errors,
        hard_similarity_collisions=hard_similarity_collisions,
        prompt_version_audit=prompt_audit,
        artifact_audit=artifact_audit,
        checks=checks,
        passed=all(check.passed for check in checks),
    )


def build_benchmark_scorecard(
    *,
    dataset_id: str,
    total_case_count: int,
    run_scorecards: list[RunScorecard],
    mode_comparisons: list[ModeComparisonReport],
    reproducibility_reports: list[ReproducibilityReport],
) -> BenchmarkScorecard:
    """Aggregate run-level scorecards into one release gate."""
    structure_errors = sum(scorecard.structure_errors for scorecard in run_scorecards)
    answer_errors = sum(scorecard.answer_errors for scorecard in run_scorecards)
    render_errors = sum(scorecard.render_errors for scorecard in run_scorecards)
    hard_similarity_collisions = sum(
        scorecard.hard_similarity_collisions for scorecard in run_scorecards
    )
    seed_reproducible = bool(reproducibility_reports) and all(
        report.equivalent for report in reproducibility_reports
    )
    artifact_lineage_reproducible = (
        all(scorecard.artifact_audit.passed for scorecard in run_scorecards)
        and (not reproducibility_reports or all(report.equivalent for report in reproducibility_reports))
    )
    manual_api_equivalent = bool(mode_comparisons) and all(
        comparison.equivalent for comparison in mode_comparisons
    )
    checks = [
        ScoreCheck(
            name="구조 오류 0",
            passed=structure_errors == 0,
            detail=f"structural findings={structure_errors}",
        ),
        ScoreCheck(
            name="정답 오류 0",
            passed=answer_errors == 0,
            detail=f"answer findings={answer_errors}",
        ),
        ScoreCheck(
            name="render 오류 0",
            passed=render_errors == 0,
            detail=f"render findings={render_errors}",
        ),
        ScoreCheck(
            name="hard similarity collision 0",
            passed=hard_similarity_collisions == 0,
            detail=f"hard similarity collisions={hard_similarity_collisions}",
        ),
        ScoreCheck(
            name="seed 재현 가능",
            passed=seed_reproducible,
            detail=f"replay_reports={len(reproducibility_reports)}",
        ),
        ScoreCheck(
            name="artifact lineage 재현 가능",
            passed=artifact_lineage_reproducible,
            detail=f"run_audits={len(run_scorecards)}",
        ),
        ScoreCheck(
            name="manual/api 모드 동등성 확인",
            passed=manual_api_equivalent,
            detail=f"mode_comparisons={len(mode_comparisons)}",
        ),
    ]
    return BenchmarkScorecard(
        dataset_id=dataset_id,
        case_count=total_case_count,
        successful_case_count=sum(1 for scorecard in run_scorecards if scorecard.passed),
        structure_errors=structure_errors,
        answer_errors=answer_errors,
        render_errors=render_errors,
        hard_similarity_collisions=hard_similarity_collisions,
        seed_reproducible=seed_reproducible,
        artifact_lineage_reproducible=artifact_lineage_reproducible,
        manual_api_equivalent=manual_api_equivalent,
        checks=checks,
        passed=all(check.passed for check in checks),
    )
