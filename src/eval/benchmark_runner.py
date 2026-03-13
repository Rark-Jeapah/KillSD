"""Release-hardening benchmark runner for end-to-end exam generation."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from pydantic import Field

from src.assembly.exam_assembler import ExamAssembler
from src.config.settings import get_settings
from src.core.schemas import ExamMode, PipelineStage, PromptPacket, StrictModel, utc_now
from src.core.storage import ArtifactStore
from src.eval.cost_logger import CostLogger, CostSummary
from src.eval.scorecard import (
    BenchmarkScorecard,
    ModeComparisonReport,
    ReproducibilityReport,
    RunScorecard,
    build_benchmark_scorecard,
    build_run_scorecard,
)
from src.orchestrator.state_machine import GenerationStateMachine, OrchestrationState
from src.providers import build_provider
from src.providers.base import BaseProvider, ProviderError, ProviderResponse
from src.render.contracts import RendererConfig
from src.render.latex_renderer import LaTeXRenderer, RenderJobResult
from src.security.secrets import SecretsResolver


class BenchmarkRunnerError(Exception):
    """Raised when a benchmark dataset or case cannot be executed."""


class BenchmarkCase(StrictModel):
    """One benchmark scenario."""

    case_id: str
    run_id_prefix: str
    mode: ExamMode
    seed: int
    provider_name: str = "mock"
    compile_pdf: bool = False
    max_retries: int = 1
    rollback_on_failure: bool = True
    compare_group: str | None = None
    reproducibility_group: str | None = None


class BenchmarkDataset(StrictModel):
    """Collection of benchmark scenarios."""

    dataset_id: str
    spec_id: str
    cases: list[BenchmarkCase]


class BenchmarkAttemptReport(StrictModel):
    """Result of one benchmark attempt."""

    case_id: str
    run_id: str
    mode: ExamMode
    seed: int
    attempt_index: int
    succeeded: bool
    rolled_back_to_run_id: str | None = None
    duration_seconds: float
    cost_summary: CostSummary
    scorecard: RunScorecard | None = None
    render_result: RenderJobResult | None = None
    error_message: str | None = None
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class BenchmarkReport(StrictModel):
    """Aggregate benchmark execution report."""

    dataset_id: str
    spec_id: str
    output_dir: str
    started_at: str
    completed_at: str
    attempts: list[BenchmarkAttemptReport]
    mode_comparisons: list[ModeComparisonReport]
    reproducibility_reports: list[ReproducibilityReport]
    scorecard: BenchmarkScorecard


class BenchmarkRunner:
    """Run benchmark datasets against the orchestrator and renderer."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        prompt_dir: Path | None = None,
        template_dir: Path | None = None,
        secrets_resolver: SecretsResolver | None = None,
    ) -> None:
        settings = get_settings()
        self.settings = settings
        self.store = artifact_store or ArtifactStore(
            root_dir=settings.artifact_root,
            db_path=settings.database_path,
        )
        self.store.initialize()
        self.prompt_dir = prompt_dir or settings.repo_root / "src" / "prompts"
        self.template_dir = template_dir or settings.repo_root / "src" / "render" / "templates"
        self.secrets = secrets_resolver or SecretsResolver()
        self.cost_logger = CostLogger()
        self.assembler = ExamAssembler(artifact_store=self.store)
        self.renderer = LaTeXRenderer(
            template_dir=self.template_dir,
            config=RendererConfig(
                xelatex_path=str(settings.xelatex_path) if settings.xelatex_path is not None else None
            ),
        )

    def load_dataset(self, dataset_path: Path) -> BenchmarkDataset:
        """Load a benchmark dataset fixture from JSON."""
        return BenchmarkDataset.model_validate(json.loads(dataset_path.read_text(encoding="utf-8")))

    def run_dataset(self, *, dataset: BenchmarkDataset, output_dir: Path) -> BenchmarkReport:
        """Execute all benchmark cases and write a report to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        previous_attempts = self._load_previous_attempts(output_dir)
        started_at = utc_now().isoformat()
        attempts: list[BenchmarkAttemptReport] = []

        for case in dataset.cases:
            attempts.append(
                self._run_case(
                    case=case,
                    output_dir=output_dir,
                    rollback_target_run_id=previous_attempts.get(case.case_id),
                )
            )

        successful_attempts = [attempt for attempt in attempts if attempt.succeeded and attempt.scorecard]
        case_by_id = {case.case_id: case for case in dataset.cases}
        mode_comparisons = self._build_mode_comparisons(
            successful_attempts,
            case_by_id=case_by_id,
        )
        reproducibility_reports = self._build_reproducibility_reports(
            successful_attempts,
            case_by_id=case_by_id,
        )
        scorecard = build_benchmark_scorecard(
            dataset_id=dataset.dataset_id,
            total_case_count=len(dataset.cases),
            run_scorecards=[attempt.scorecard for attempt in successful_attempts if attempt.scorecard],
            mode_comparisons=mode_comparisons,
            reproducibility_reports=reproducibility_reports,
        )
        report = BenchmarkReport(
            dataset_id=dataset.dataset_id,
            spec_id=dataset.spec_id,
            output_dir=str(output_dir),
            started_at=started_at,
            completed_at=utc_now().isoformat(),
            attempts=attempts,
            mode_comparisons=mode_comparisons,
            reproducibility_reports=reproducibility_reports,
            scorecard=scorecard,
        )
        self._write_json(output_dir / "benchmark_report.json", report.model_dump(mode="json"))
        return report

    def _run_case(
        self,
        *,
        case: BenchmarkCase,
        output_dir: Path,
        rollback_target_run_id: str | None,
    ) -> BenchmarkAttemptReport:
        last_failure: BenchmarkAttemptReport | None = None

        for attempt_index in range(1, case.max_retries + 1):
            run_id = f"{case.run_id_prefix}__{case.mode.value}__seed_{case.seed}__try_{attempt_index}"
            attempt_dir = output_dir / case.case_id / f"attempt_{attempt_index}"
            machine = GenerationStateMachine(
                artifact_store=self.store,
                prompt_dir=self.prompt_dir,
                provider=self._build_provider(case.provider_name),
            )
            started = perf_counter()
            manual_responses: list[ProviderResponse] = []
            render_result: RenderJobResult | None = None

            try:
                if case.mode == ExamMode.API:
                    state = machine.run_exam(run_id=run_id, mode=case.mode, seed=case.seed)
                    cost_summary = self.cost_logger.load_and_summarize(
                        run_id=run_id,
                        artifact_store=self.store,
                    )
                else:
                    state, manual_responses = self._run_manual_exam(
                        machine=machine,
                        run_id=run_id,
                        seed=case.seed,
                        provider_name=case.provider_name,
                    )
                    cost_summary = self.cost_logger.summarize_responses(manual_responses)

                bundle, summary = self.assembler.bundle_for_run(run_id=run_id, force=True)
                validator_reports = self.assembler.load_validator_suite_reports(run_id=run_id)
                render_result = self.renderer.render_exam_set(
                    run_id=run_id,
                    bundle=bundle,
                    bundle_artifact_id=summary.bundle_artifact_id,
                    validator_reports=validator_reports,
                    validator_suite_artifact_ids=summary.validator_suite_artifact_ids,
                    output_dir=attempt_dir,
                    compile_pdf=case.compile_pdf,
                )
                self.store.save_model(
                    render_result,
                    stage=PipelineStage.RENDER,
                    run_id=run_id,
                    spec_id=bundle.spec_id,
                    metadata={
                        "source": "benchmark_runner",
                        "case_id": case.case_id,
                        "attempt_index": attempt_index,
                    },
                )
                self._assert_compiled_documents(case=case, render_result=render_result)
                scorecard = build_run_scorecard(
                    state=state,
                    validator_reports=validator_reports,
                    render_result=render_result,
                    artifact_store=self.store,
                    compile_pdf=case.compile_pdf,
                )
                attempt = BenchmarkAttemptReport(
                    case_id=case.case_id,
                    run_id=run_id,
                    mode=case.mode,
                    seed=case.seed,
                    attempt_index=attempt_index,
                    succeeded=scorecard.passed,
                    duration_seconds=round(perf_counter() - started, 3),
                    cost_summary=cost_summary,
                    scorecard=scorecard,
                    render_result=render_result,
                )
                self._write_json(attempt_dir / "attempt_report.json", attempt.model_dump(mode="json"))
                if attempt.succeeded:
                    return attempt
                last_failure = attempt
            except Exception as exc:
                cost_summary = self.cost_logger.summarize_responses(manual_responses)
                attempt = BenchmarkAttemptReport(
                    case_id=case.case_id,
                    run_id=run_id,
                    mode=case.mode,
                    seed=case.seed,
                    attempt_index=attempt_index,
                    succeeded=False,
                    duration_seconds=round(perf_counter() - started, 3),
                    cost_summary=cost_summary,
                    render_result=render_result,
                    error_message=str(exc),
                )
                self._write_json(attempt_dir / "attempt_report.json", attempt.model_dump(mode="json"))
                last_failure = attempt

        if last_failure is None:
            raise BenchmarkRunnerError(f"Benchmark case produced no attempts: {case.case_id}")
        if case.rollback_on_failure:
            last_failure.rolled_back_to_run_id = rollback_target_run_id
        return last_failure

    def _run_manual_exam(
        self,
        *,
        machine: GenerationStateMachine,
        run_id: str,
        seed: int,
        provider_name: str,
    ) -> tuple[OrchestrationState, list[ProviderResponse]]:
        provider = self._build_provider(provider_name)
        responses: list[ProviderResponse] = []
        state = machine.run_exam(run_id=run_id, mode=ExamMode.MANUAL, seed=seed)
        while state.status.value == "waiting_manual":
            for packet_path_str in state.pending_prompt_paths():
                packet_path = Path(packet_path_str)
                packet = PromptPacket.model_validate(json.loads(packet_path.read_text(encoding="utf-8")))
                response = provider.invoke(packet)
                response_path = machine.manual_controller.response_path_for(packet)
                response_path.parent.mkdir(parents=True, exist_ok=True)
                response_path.write_text(
                    json.dumps(response.output, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                responses.append(response)
                state = machine.import_manual_exchange(
                    run_id=run_id,
                    packet_path=packet_path,
                    response_path=response_path,
                )
            state = machine.run_exam(run_id=run_id, mode=ExamMode.MANUAL, seed=seed)
        return state, responses

    def _build_provider(self, provider_name: str) -> BaseProvider:
        try:
            return build_provider(provider_name, secrets_resolver=self.secrets)
        except ProviderError as exc:
            raise BenchmarkRunnerError(str(exc)) from exc

    def _build_mode_comparisons(
        self,
        successful_attempts: list[BenchmarkAttemptReport],
        *,
        case_by_id: dict[str, BenchmarkCase],
    ) -> list[ModeComparisonReport]:
        attempts_by_group: dict[str, dict[str, BenchmarkAttemptReport]] = {}
        for attempt in successful_attempts:
            case = case_by_id.get(attempt.case_id)
            if case is None or case.compare_group is None:
                continue
            attempts_by_group.setdefault(case.compare_group, {})[attempt.mode.value] = attempt

        reports: list[ModeComparisonReport] = []
        for group_id, grouped_attempts in sorted(attempts_by_group.items()):
            api_attempt = grouped_attempts.get("api")
            manual_attempt = grouped_attempts.get("manual")
            if api_attempt is None or manual_attempt is None:
                continue
            differences = self._compare_runs(
                left_run_id=api_attempt.run_id,
                right_run_id=manual_attempt.run_id,
                include_lineage=False,
            )
            reports.append(
                ModeComparisonReport(
                    group_id=group_id,
                    api_run_id=api_attempt.run_id,
                    manual_run_id=manual_attempt.run_id,
                    equivalent=not differences,
                    differences=differences,
                )
            )
        return reports

    def _build_reproducibility_reports(
        self,
        successful_attempts: list[BenchmarkAttemptReport],
        *,
        case_by_id: dict[str, BenchmarkCase],
    ) -> list[ReproducibilityReport]:
        attempts_by_group: dict[str, list[BenchmarkAttemptReport]] = {}
        for attempt in successful_attempts:
            case = case_by_id.get(attempt.case_id)
            if case is None or case.reproducibility_group is None:
                continue
            attempts_by_group.setdefault(case.reproducibility_group, []).append(attempt)

        reports: list[ReproducibilityReport] = []
        for group_id, grouped_attempts in sorted(attempts_by_group.items()):
            if len(grouped_attempts) < 2:
                continue
            baseline, replay = sorted(grouped_attempts, key=lambda attempt: attempt.case_id)[:2]
            differences = self._compare_runs(
                left_run_id=baseline.run_id,
                right_run_id=replay.run_id,
                include_lineage=True,
            )
            reports.append(
                ReproducibilityReport(
                    group_id=group_id,
                    baseline_run_id=baseline.run_id,
                    replay_run_id=replay.run_id,
                    seed=baseline.seed,
                    equivalent=not differences,
                    differences=differences,
                )
            )
        return reports

    def _compare_runs(
        self,
        *,
        left_run_id: str,
        right_run_id: str,
        include_lineage: bool,
    ) -> list[str]:
        left_bundle, _ = self.assembler.bundle_for_run(run_id=left_run_id, force=False)
        right_bundle, _ = self.assembler.bundle_for_run(run_id=right_run_id, force=False)
        left_state = self._load_state(left_run_id)
        right_state = self._load_state(right_run_id)

        differences: list[str] = []
        if self._normalize_bundle(left_bundle) != self._normalize_bundle(right_bundle):
            differences.append("normalized_render_bundle_mismatch")
        if self._prompt_signature(left_state) != self._prompt_signature(right_state):
            differences.append("prompt_signature_mismatch")
        if include_lineage and self._lineage_signature(left_state) != self._lineage_signature(right_state):
            differences.append("artifact_lineage_signature_mismatch")
        return differences

    def _normalize_bundle(self, bundle) -> dict[str, object]:
        return {
            "spec_id": bundle.spec_id,
            "student_metadata": bundle.student_metadata,
            "internal_metadata": bundle.internal_metadata,
            "answer_key": sorted(bundle.answer_key.items()),
            "items": [
                {
                    "item_no": item.solved.draft.blueprint.item_no,
                    "domain": item.solved.draft.blueprint.domain,
                    "format": item.solved.draft.blueprint.format.value,
                    "score": item.solved.draft.blueprint.score,
                    "difficulty": item.solved.draft.blueprint.difficulty.value,
                    "objective": item.solved.draft.blueprint.objective,
                    "skill_tags": sorted(item.solved.draft.blueprint.skill_tags),
                    "stem": item.solved.draft.stem,
                    "choices": item.solved.draft.choices,
                    "final_answer": item.solved.final_answer,
                    "correct_choice_index": item.solved.correct_choice_index,
                    "correct_choice_value": item.solved.correct_choice_value,
                    "validation_status": item.validation.status.value,
                    "reason_codes": item.validation.reason_codes,
                }
                for item in bundle.items
            ],
        }

    def _assert_compiled_documents(
        self, *, case: BenchmarkCase, render_result: RenderJobResult
    ) -> None:
        """Enforce benchmark compile expectations for release-gate runs."""
        if not case.compile_pdf:
            return
        failures: list[str] = []
        for document in render_result.documents:
            if not document.compiled or document.pdf_path is None:
                failures.append(
                    f"{document.kind}(compiled={document.compiled}, pdf_path={document.pdf_path})"
                )
                continue
            if not Path(document.pdf_path).exists():
                failures.append(f"{document.kind}(missing_pdf={document.pdf_path})")
        if failures:
            raise BenchmarkRunnerError(
                "compile_pdf=true requires compiled PDFs for every rendered document: "
                + ", ".join(failures)
            )

    def _lineage_signature(self, state: OrchestrationState) -> list[dict[str, object]]:
        signature: list[dict[str, object]] = []
        for record in state.history:
            signature.append(
                {
                    "stage_name": record.stage_name,
                    "item_no": record.item_no,
                    "attempt": record.attempt,
                    "status": record.status.value,
                    "input_count": len(record.input_artifact_ids),
                    "prompt_version": record.prompt_version,
                    "prompt_hash": record.prompt_hash,
                    "provider_name": record.provider_name,
                    "has_validation_report": bool(record.validation_report_artifact_id),
                    "has_validator_suite": bool(record.validator_suite_artifact_id),
                }
            )
        return signature

    def _prompt_signature(
        self, state: OrchestrationState
    ) -> list[tuple[str, int | None, int, str | None, str | None]]:
        signature = {
            (record.stage_name, record.item_no, record.attempt, record.prompt_version, record.prompt_hash)
            for record in state.history
            if record.stage_name in {"exam_blueprint", "item_blueprint", "draft_item", "solve", "critique", "revise"}
            and record.prompt_version is not None
            and record.prompt_hash is not None
        }
        return sorted(signature)

    def _load_previous_attempts(self, output_dir: Path) -> dict[str, str]:
        report_path = output_dir / "benchmark_report.json"
        if not report_path.exists():
            return {}
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        report = BenchmarkReport.model_validate(payload)
        previous: dict[str, str] = {}
        for attempt in report.attempts:
            if attempt.succeeded:
                previous[attempt.case_id] = attempt.run_id
        return previous

    def _load_state(self, run_id: str) -> OrchestrationState:
        path = self.store.root_dir / run_id / "orchestrator_state.json"
        if not path.exists():
            raise BenchmarkRunnerError(f"Orchestrator state missing: {run_id}")
        return OrchestrationState.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


BenchmarkAttemptReport.model_rebuild()
BenchmarkReport.model_rebuild()
