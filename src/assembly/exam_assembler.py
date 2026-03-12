"""Assembly helpers for completed exam runs."""

from __future__ import annotations

import json

from src.assembly.orderer import OrderingError, OrderingMetrics, order_validated_items
from src.core.schemas import ExamBlueprint, RenderBundle, StrictModel, ValidatedItem, utc_now
from src.core.storage import ArtifactStore
from src.orchestrator.state_machine import (
    OrchestrationState,
    StageExecutionRecord,
    StageExecutionStatus,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.validators.report import ValidatorSuiteReport


class AssemblySummary(StrictModel):
    """Artifact-friendly summary returned by the exam assembler."""

    run_id: str
    spec_id: str
    bundle_artifact_id: str
    blueprint_artifact_id: str
    validated_item_artifact_ids: list[str]
    validator_suite_artifact_ids: list[str]
    metrics: OrderingMetrics


class ExamAssembler:
    """Assemble a render bundle from validated item artifacts."""

    def __init__(self, *, artifact_store: ArtifactStore) -> None:
        self.store = artifact_store
        self.plugin = CSATMath2028Plugin()
        self.spec = self.plugin.load_exam_spec()

    def assemble_from_run(self, *, run_id: str, force: bool = False) -> AssemblySummary:
        """Load orchestrator outputs for a run and produce a RenderBundle artifact."""
        state = self._load_state(run_id)
        bundle_artifact_id = state.render_bundle_artifact_id
        if bundle_artifact_id and not force:
            bundle_artifact_id = state.render_bundle_artifact_id
        else:
            bundle_artifact_id = self._assemble_bundle(state=state)
            state.stage_outputs["assemble"] = bundle_artifact_id
            state.stage_statuses["assemble"] = StageExecutionStatus.SUCCEEDED
            state.render_bundle_artifact_id = bundle_artifact_id
            self._save_state(state)

        blueprint_artifact_id = state.stage_outputs["exam_blueprint"]
        validated_item_artifact_ids = [
            state.stage_outputs[f"validate:{item_no}"] for item_no in range(1, self.spec.total_items + 1)
        ]
        validator_suite_artifact_ids = self.validator_suite_artifact_ids(run_id=run_id)
        exam_blueprint = self.store.load_model(blueprint_artifact_id, ExamBlueprint)
        validated_items = [
            self.store.load_model(artifact_id, ValidatedItem)
            for artifact_id in validated_item_artifact_ids
        ]
        _, metrics = order_validated_items(exam_blueprint, validated_items)
        return AssemblySummary(
            run_id=run_id,
            spec_id=self.spec.spec_id,
            bundle_artifact_id=bundle_artifact_id,
            blueprint_artifact_id=blueprint_artifact_id,
            validated_item_artifact_ids=validated_item_artifact_ids,
            validator_suite_artifact_ids=validator_suite_artifact_ids,
            metrics=metrics,
        )

    def load_bundle(self, artifact_id: str) -> RenderBundle:
        """Load a previously assembled render bundle artifact."""
        return self.store.load_model(artifact_id, RenderBundle)

    def bundle_for_run(self, *, run_id: str, force: bool = False) -> tuple[RenderBundle, AssemblySummary]:
        """Assemble, then load the render bundle for a run."""
        summary = self.assemble_from_run(run_id=run_id, force=force)
        return self.load_bundle(summary.bundle_artifact_id), summary

    def load_validator_suite_reports(self, *, run_id: str) -> list[ValidatorSuiteReport]:
        """Load the latest validator suite reports for each item."""
        artifact_ids = self.validator_suite_artifact_ids(run_id=run_id)
        return [self.store.load_model(artifact_id, ValidatorSuiteReport) for artifact_id in artifact_ids]

    def validator_suite_artifact_ids(self, *, run_id: str) -> list[str]:
        """Return the latest validator suite artifact id for each item in order."""
        state = self._load_state(run_id)
        artifact_ids: list[str] = []
        for item_no in range(1, self.spec.total_items + 1):
            record = self._latest_validate_record(state=state, item_no=item_no)
            if record.validator_suite_artifact_id is None:
                raise OrderingError(f"Validator suite artifact missing for item {item_no}")
            artifact_ids.append(record.validator_suite_artifact_id)
        return artifact_ids

    def _assemble_bundle(self, *, state: OrchestrationState) -> str:
        blueprint_artifact_id = state.stage_outputs.get("exam_blueprint")
        if blueprint_artifact_id is None:
            raise OrderingError("Missing exam blueprint artifact")
        exam_blueprint = self.store.load_model(blueprint_artifact_id, ExamBlueprint)
        validated_items = [
            self.store.load_model(state.stage_outputs[f"validate:{item_no}"], ValidatedItem)
            for item_no in range(1, self.spec.total_items + 1)
        ]
        ordered_items, metrics = order_validated_items(exam_blueprint, validated_items)
        bundle = RenderBundle(
            spec_id=self.spec.spec_id,
            blueprint_id=exam_blueprint.blueprint_id,
            generated_at=utc_now(),
            items=ordered_items,
            student_metadata={
                "title": self.spec.title,
                "duration_minutes": str(self.spec.duration_minutes),
                "total_score": str(self.spec.total_score),
            },
            internal_metadata={
                "topic_coverage": json.dumps(metrics.topic_coverage, ensure_ascii=False),
                "difficulty_curve": ",".join(metrics.difficulty_curve),
                "score_distribution": json.dumps(metrics.score_distribution, ensure_ascii=False),
            },
            output_targets=["exam_pdf", "answer_key_pdf", "validation_report_pdf"],
            answer_key={
                item.solved.draft.blueprint.item_no: item.solved.final_answer for item in ordered_items
            },
            asset_refs=[],
        )
        env = self.store.save_model(
            bundle,
            stage=self.spec.pipeline_stages[-2],
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "source": "exam_assembler",
                "blueprint_artifact_id": blueprint_artifact_id,
                "validated_item_artifact_ids": [
                    state.stage_outputs[f"validate:{item_no}"] for item_no in range(1, self.spec.total_items + 1)
                ],
            },
        )
        state.history.append(
            StageExecutionRecord(
                stage_name="assemble",
                attempt=state.stage_attempts.get("assemble", 0) + 1,
                status=StageExecutionStatus.SUCCEEDED,
                input_artifact_ids=[
                    blueprint_artifact_id,
                    *[
                        state.stage_outputs[f"validate:{item_no}"]
                        for item_no in range(1, self.spec.total_items + 1)
                    ],
                ],
                output_artifact_id=env.artifact_id,
                provider_name="exam_assembler",
            )
        )
        state.stage_attempts["assemble"] = state.stage_attempts.get("assemble", 0) + 1
        return env.artifact_id

    def _load_state(self, run_id: str) -> OrchestrationState:
        path = self.store.root_dir / run_id / "orchestrator_state.json"
        if not path.exists():
            raise OrderingError(f"Orchestrator state not found for run_id={run_id}")
        return OrchestrationState.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _save_state(self, state: OrchestrationState) -> None:
        path = self.store.root_dir / state.run_id / "orchestrator_state.json"
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def _latest_validate_record(
        self, *, state: OrchestrationState, item_no: int
    ) -> StageExecutionRecord:
        for record in reversed(state.history):
            if (
                record.stage_name == "validate"
                and record.item_no == item_no
                and record.status == StageExecutionStatus.SUCCEEDED
            ):
                return record
        raise OrderingError(f"Successful validate record not found for item {item_no}")
