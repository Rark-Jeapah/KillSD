"""State-machine orchestrator for staged exam generation."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from src.core.schemas import (
    CritiqueReport,
    ExamBlueprint,
    ExamMode,
    ExamSpec,
    PromptPacket,
    RenderBundle,
    SolvedItem,
    StrictModel,
    ValidationReport,
    ValidatedItem,
    utc_now,
)
from src.core.storage import ArtifactStore
from src.orchestrator.api_mode import ApiModeExecutor
from src.orchestrator.manual_mode import ManualModeController, ManualModeError
from src.orchestrator.stages import (
    STAGE_DEFINITIONS,
    assemble_render_bundle,
    build_prompt_packet,
    get_stage_definition,
    load_prompt_template,
    stage_key,
    validate_item_locally,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.providers.base import BaseProvider, ProviderError


class StageExecutionStatus(str, Enum):
    """Execution status for a single stage attempt."""

    WAITING_MANUAL = "waiting_manual"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStatus(str, Enum):
    """High-level run status."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_MANUAL = "waiting_manual"
    FAILED = "failed"
    COMPLETED = "completed"


class StageExecutionRecord(StrictModel):
    """Lineage record for one stage attempt."""

    record_id: str = Field(default_factory=lambda: f"stg-{uuid4().hex[:12]}")
    stage_name: str
    item_no: int | None = None
    attempt: int
    status: StageExecutionStatus
    input_artifact_ids: list[str] = Field(default_factory=list)
    prompt_packet_artifact_id: str | None = None
    prompt_export_path: str | None = None
    provider_response_artifact_id: str | None = None
    manual_exchange_artifact_id: str | None = None
    validation_report_artifact_id: str | None = None
    validator_suite_artifact_id: str | None = None
    output_artifact_id: str | None = None
    prompt_hash: str | None = None
    prompt_version: str | None = None
    seed: int | None = None
    provider_name: str | None = None
    error_message: str | None = None
    recorded_at: datetime = Field(default_factory=utc_now)


class OrchestrationState(StrictModel):
    """Persisted state for one orchestration run."""

    run_id: str
    spec_id: str
    mode: ExamMode
    seed: int
    orchestrator_version: str
    status: RunStatus = RunStatus.PENDING
    exam_spec_artifact_id: str | None = None
    stage_outputs: dict[str, str] = Field(default_factory=dict)
    stage_statuses: dict[str, StageExecutionStatus] = Field(default_factory=dict)
    stage_attempts: dict[str, int] = Field(default_factory=dict)
    stage_prompt_artifact_ids: dict[str, str] = Field(default_factory=dict)
    stage_prompt_paths: dict[str, str] = Field(default_factory=dict)
    render_bundle_artifact_id: str | None = None
    history: list[StageExecutionRecord] = Field(default_factory=list)
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    def pending_prompt_paths(self) -> list[str]:
        """Return prompt export paths currently awaiting manual input."""
        pending = []
        for key, status in self.stage_statuses.items():
            if status == StageExecutionStatus.WAITING_MANUAL and key in self.stage_prompt_paths:
                pending.append(self.stage_prompt_paths[key])
        return sorted(pending)


class StateMachineError(Exception):
    """Raised when the orchestration state machine cannot proceed."""


class GenerationStateMachine:
    """Stage-based generation orchestrator with manual and API modes."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        prompt_dir: Path,
        provider: BaseProvider | None = None,
        orchestrator_version: str = "0.1.0",
    ) -> None:
        self.store = artifact_store
        self.store.initialize()
        self.prompt_dir = prompt_dir
        self.provider = provider
        self.api_executor = ApiModeExecutor(provider) if provider is not None else None
        self.manual_controller = ManualModeController(self.store.root_dir / "manual_exchanges")
        self.orchestrator_version = orchestrator_version
        self.plugin = CSATMath2028Plugin()
        self.spec = self.plugin.load_exam_spec()
        self.repo_root = prompt_dir.parents[1]

    def run_plan(self, *, run_id: str, mode: ExamMode, seed: int = 0) -> OrchestrationState:
        """Run only the exam blueprint planning stage."""
        state = self._create_or_load_state(run_id=run_id, mode=mode, seed=seed)
        state.status = RunStatus.RUNNING
        self._bootstrap_exam_spec(state)
        if not self._ensure_stage(state, "exam_blueprint", item_no=None):
            return self._save_state(state)
        state.status = RunStatus.COMPLETED
        return self._save_state(state)

    def run_item_draft(
        self, *, run_id: str, item_no: int, mode: ExamMode, seed: int = 0
    ) -> OrchestrationState:
        """Run up to the draft stage for a single item."""
        state = self._create_or_load_state(run_id=run_id, mode=mode, seed=seed)
        state.status = RunStatus.RUNNING
        self._bootstrap_exam_spec(state)
        for stage_name in ("exam_blueprint", "item_blueprint", "draft_item"):
            scoped_item_no = item_no if stage_name != "exam_blueprint" else None
            if not self._ensure_stage(state, stage_name, item_no=scoped_item_no):
                return self._save_state(state)
        state.status = RunStatus.COMPLETED
        return self._save_state(state)

    def run_exam(self, *, run_id: str, mode: ExamMode, seed: int = 0) -> OrchestrationState:
        """Run the full exam generation state machine."""
        state = self._create_or_load_state(run_id=run_id, mode=mode, seed=seed)
        state.status = RunStatus.RUNNING
        self._bootstrap_exam_spec(state)

        if not self._ensure_stage(state, "exam_blueprint", item_no=None):
            return self._save_state(state)

        for item_no in range(1, self.spec.total_items + 1):
            for stage_name in (
                "item_blueprint",
                "draft_item",
                "solve",
                "critique",
                "revise",
                "validate",
            ):
                if not self._ensure_stage(state, stage_name, item_no=item_no):
                    return self._save_state(state)

        if not self._ensure_stage(state, "assemble", item_no=None):
            return self._save_state(state)

        state.render_bundle_artifact_id = state.stage_outputs.get("assemble")
        state.status = RunStatus.COMPLETED
        return self._save_state(state)

    def import_manual_exchange(
        self, *, run_id: str, packet_path: Path, response_path: Path
    ) -> OrchestrationState:
        """Import a manual response file and attach it to the orchestration state."""
        state = self.load_state(run_id)
        if state is None:
            raise StateMachineError(f"No orchestration state found for run_id={run_id}")

        packet = PromptPacket.model_validate(json.loads(packet_path.read_text(encoding="utf-8")))
        if packet.run_id != run_id:
            raise StateMachineError("packet_path run_id does not match the target run_id")

        stage_def = get_stage_definition(packet.stage_name)
        try:
            packet, output_model, exchange = self.manual_controller.import_response(
                packet_path=packet_path,
                response_path=response_path,
                model_type=stage_def.output_model,
            )
        except ManualModeError as exc:
            raise StateMachineError(str(exc)) from exc

        key = stage_key(packet.stage_name, packet.item_no)
        output_env = self.store.save_model(
            output_model,
            stage=stage_def.pipeline_stage,
            run_id=run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": packet.stage_name,
                "attempt": packet.attempt,
                "mode": packet.mode.value,
                "source": "manual_import",
            },
        )
        exchange_env = self.store.save_model(
            exchange,
            stage=stage_def.pipeline_stage,
            run_id=run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": packet.stage_name,
                "attempt": packet.attempt,
                "source": "manual_exchange",
            },
        )
        state.stage_outputs[key] = output_env.artifact_id
        state.stage_statuses[key] = StageExecutionStatus.SUCCEEDED
        state.stage_attempts[key] = max(state.stage_attempts.get(key, 0), packet.attempt)
        state.last_error = None
        state.history.append(
            StageExecutionRecord(
                stage_name=packet.stage_name,
                item_no=packet.item_no,
                attempt=packet.attempt,
                status=StageExecutionStatus.SUCCEEDED,
                input_artifact_ids=packet.input_artifact_ids,
                prompt_packet_artifact_id=state.stage_prompt_artifact_ids.get(key),
                prompt_export_path=str(packet_path),
                manual_exchange_artifact_id=exchange_env.artifact_id,
                output_artifact_id=output_env.artifact_id,
                prompt_hash=packet.prompt_hash,
                prompt_version=packet.prompt_version,
                seed=packet.seed,
                provider_name="manual_import",
            )
        )
        state.status = RunStatus.PENDING
        return self._save_state(state)

    def export_pending_exchanges(self, *, run_id: str) -> list[str]:
        """Return prompt packet files currently waiting for manual responses."""
        state = self.load_state(run_id)
        if state is None:
            raise StateMachineError(f"No orchestration state found for run_id={run_id}")
        return state.pending_prompt_paths()

    def load_state(self, run_id: str) -> OrchestrationState | None:
        """Load a persisted orchestration state if it exists."""
        path = self._state_path(run_id)
        if not path.exists():
            return None
        return OrchestrationState.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _create_or_load_state(
        self, *, run_id: str, mode: ExamMode, seed: int
    ) -> OrchestrationState:
        state = self.load_state(run_id)
        if state is not None:
            if state.mode != mode:
                raise StateMachineError("Existing run_id was created with a different mode")
            return state
        state = OrchestrationState(
            run_id=run_id,
            spec_id=self.spec.spec_id,
            mode=mode,
            seed=seed,
            orchestrator_version=self.orchestrator_version,
        )
        return self._save_state(state)

    def _bootstrap_exam_spec(self, state: OrchestrationState) -> None:
        if state.exam_spec_artifact_id is not None:
            return
        envelope = self.store.save_model(
            self.spec,
            stage=get_stage_definition("exam_blueprint").pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"source": "orchestrator_bootstrap"},
        )
        state.exam_spec_artifact_id = envelope.artifact_id
        self._save_state(state)

    def _ensure_stage(
        self, state: OrchestrationState, stage_name: str, item_no: int | None
    ) -> bool:
        stage_def = get_stage_definition(stage_name)
        key = stage_key(stage_name, item_no)
        if key in state.stage_outputs:
            return True

        if state.stage_statuses.get(key) == StageExecutionStatus.WAITING_MANUAL:
            state.status = RunStatus.WAITING_MANUAL
            return False

        attempt = state.stage_attempts.get(key, 0) + 1
        input_artifact_ids, context, blueprint_id = self._build_stage_inputs(
            state, stage_name=stage_name, item_no=item_no
        )

        if not stage_def.remote:
            return self._execute_local_stage(
                state=state,
                stage_name=stage_name,
                item_no=item_no,
                stage_key_value=key,
                input_artifact_ids=input_artifact_ids,
            )

        prompt_template = load_prompt_template(self.prompt_dir, stage_def.prompt_file or "")
        packet = build_prompt_packet(
            mode=state.mode,
            stage_name=stage_name,
            spec_id=self.spec.spec_id,
            run_id=state.run_id,
            blueprint_id=blueprint_id,
            item_no=item_no,
            input_artifact_ids=input_artifact_ids,
            context=context,
            seed=state.seed,
            attempt=attempt,
            provider_name=self.provider.provider_name if self.provider else None,
            prompt_template=prompt_template,
            output_model=stage_def.output_model,
            pipeline_stage=stage_def.pipeline_stage,
        )
        prompt_env = self.store.save_model(
            packet,
            stage=stage_def.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={
                "stage_name": stage_name,
                "attempt": attempt,
                "prompt_hash": packet.prompt_hash,
                "prompt_version": packet.prompt_version,
            },
        )
        state.stage_prompt_artifact_ids[key] = prompt_env.artifact_id
        state.stage_attempts[key] = attempt

        if state.mode == ExamMode.MANUAL:
            export_path = self.manual_controller.export_packet(packet)
            state.stage_statuses[key] = StageExecutionStatus.WAITING_MANUAL
            state.stage_prompt_paths[key] = str(export_path)
            state.status = RunStatus.WAITING_MANUAL
            state.history.append(
                StageExecutionRecord(
                    stage_name=stage_name,
                    item_no=item_no,
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
            raise StateMachineError("API mode requires a configured provider")

        try:
            output_model, provider_response = self.api_executor.execute(packet, stage_def.output_model)
            output_env = self.store.save_model(
                output_model,
                stage=stage_def.pipeline_stage,
                run_id=state.run_id,
                spec_id=self.spec.spec_id,
                metadata={
                    "stage_name": stage_name,
                    "attempt": attempt,
                    "provider_name": provider_response.provider_name,
                    "prompt_hash": packet.prompt_hash,
                },
            )
            provider_env = self.store.save_model(
                provider_response,
                stage=stage_def.pipeline_stage,
                run_id=state.run_id,
                spec_id=self.spec.spec_id,
                metadata={
                    "stage_name": stage_name,
                    "attempt": attempt,
                    "source": "provider_response",
                },
            )
        except (ProviderError, Exception) as exc:
            state.stage_statuses[key] = StageExecutionStatus.FAILED
            state.status = RunStatus.FAILED
            state.last_error = str(exc)
            state.history.append(
                StageExecutionRecord(
                    stage_name=stage_name,
                    item_no=item_no,
                    attempt=attempt,
                    status=StageExecutionStatus.FAILED,
                    input_artifact_ids=input_artifact_ids,
                    prompt_packet_artifact_id=prompt_env.artifact_id,
                    prompt_hash=packet.prompt_hash,
                    prompt_version=packet.prompt_version,
                    seed=packet.seed,
                    provider_name=self.provider.provider_name if self.provider else None,
                    error_message=str(exc),
                )
            )
            self._save_state(state)
            raise StateMachineError(str(exc)) from exc

        state.stage_outputs[key] = output_env.artifact_id
        state.stage_statuses[key] = StageExecutionStatus.SUCCEEDED
        state.last_error = None
        state.history.append(
            StageExecutionRecord(
                stage_name=stage_name,
                item_no=item_no,
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

    def _execute_local_stage(
        self,
        *,
        state: OrchestrationState,
        stage_name: str,
        item_no: int | None,
        stage_key_value: str,
        input_artifact_ids: list[str],
    ) -> bool:
        stage_def = get_stage_definition(stage_name)
        attempt = state.stage_attempts.get(stage_key_value, 0) + 1

        if stage_name == "validate":
            solved_item = self._load_output(state, "revise", item_no, SolvedItem)
            critique_report = self._load_output(state, "critique", item_no, CritiqueReport)
            suite_report, output_model = validate_item_locally(
                solved_item=solved_item,
                critique_report=critique_report,
                spec=self.spec,
                repo_root=self.repo_root,
            )
            validation_report_env = self.store.save_model(
                suite_report.final_report,
                stage=stage_def.pipeline_stage,
                run_id=state.run_id,
                spec_id=self.spec.spec_id,
                metadata={"stage_name": "validation_report", "item_no": item_no, "source": "local"},
            )
            validator_suite_env = self.store.save_model(
                suite_report,
                stage=stage_def.pipeline_stage,
                run_id=state.run_id,
                spec_id=self.spec.spec_id,
                metadata={"stage_name": "validator_suite", "item_no": item_no, "source": "local"},
            )
        elif stage_name == "assemble":
            exam_blueprint = self._load_output(state, "exam_blueprint", None, ExamBlueprint)
            validated_items = [
                self._load_output(state, "validate", index, ValidatedItem)
                for index in range(1, self.spec.total_items + 1)
            ]
            output_model = assemble_render_bundle(
                spec=self.spec,
                exam_blueprint=exam_blueprint,
                validated_items=validated_items,
            )
        else:
            raise StateMachineError(f"Unsupported local stage: {stage_name}")

        output_env = self.store.save_model(
            output_model,
            stage=stage_def.pipeline_stage,
            run_id=state.run_id,
            spec_id=self.spec.spec_id,
            metadata={"stage_name": stage_name, "attempt": attempt, "source": "local"},
        )
        state.stage_attempts[stage_key_value] = attempt

        if stage_name == "validate" and output_model.validation.status.value != "pass":
            state.stage_statuses[stage_key_value] = StageExecutionStatus.FAILED
            state.status = RunStatus.FAILED
            state.last_error = (
                f"Validation blocked item {item_no}: "
                f"{output_model.validation.regenerate_recommendation.value} "
                f"{','.join(output_model.validation.reason_codes)}"
            )
            state.history.append(
                StageExecutionRecord(
                    stage_name=stage_name,
                    item_no=item_no,
                    attempt=attempt,
                    status=StageExecutionStatus.FAILED,
                    input_artifact_ids=input_artifact_ids,
                    validation_report_artifact_id=validation_report_env.artifact_id,
                    validator_suite_artifact_id=validator_suite_env.artifact_id,
                    output_artifact_id=output_env.artifact_id,
                    provider_name="local",
                    error_message=state.last_error,
                )
            )
            self._save_state(state)
            return False

        state.stage_outputs[stage_key_value] = output_env.artifact_id
        state.stage_statuses[stage_key_value] = StageExecutionStatus.SUCCEEDED
        state.last_error = None
        state.history.append(
            StageExecutionRecord(
                stage_name=stage_name,
                item_no=item_no,
                attempt=attempt,
                status=StageExecutionStatus.SUCCEEDED,
                input_artifact_ids=input_artifact_ids,
                validation_report_artifact_id=(
                    validation_report_env.artifact_id if stage_name == "validate" else None
                ),
                validator_suite_artifact_id=(
                    validator_suite_env.artifact_id if stage_name == "validate" else None
                ),
                output_artifact_id=output_env.artifact_id,
                provider_name="local",
            )
        )
        self._save_state(state)
        return True

    def _build_stage_inputs(
        self, state: OrchestrationState, *, stage_name: str, item_no: int | None
    ) -> tuple[list[str], dict[str, object], str | None]:
        if stage_name == "exam_blueprint":
            return [state.exam_spec_artifact_id or ""], {"exam_spec": self.spec.model_dump(mode="json")}, None

        exam_blueprint = self._load_output(state, "exam_blueprint", None, ExamBlueprint)
        blueprint_id = exam_blueprint.blueprint_id
        if stage_name == "item_blueprint":
            return (
                [state.stage_outputs["exam_blueprint"]],
                {"exam_blueprint": exam_blueprint.model_dump(mode="json"), "item_no": item_no},
                blueprint_id,
            )

        if stage_name == "assemble":
            validated_ids = [
                state.stage_outputs[stage_key("validate", index)]
                for index in range(1, self.spec.total_items + 1)
            ]
            return (
                [state.stage_outputs["exam_blueprint"], *validated_ids],
                {},
                blueprint_id,
            )

        item_blueprint = self._load_output(state, "item_blueprint", item_no, stage_def_output("item_blueprint"))
        if stage_name == "draft_item":
            return (
                [state.stage_outputs[stage_key("item_blueprint", item_no)]],
                {"item_blueprint": item_blueprint.model_dump(mode="json")},
                blueprint_id,
            )

        draft_item = self._load_output(state, "draft_item", item_no, stage_def_output("draft_item"))
        if stage_name == "solve":
            return (
                [state.stage_outputs[stage_key("draft_item", item_no)]],
                {"draft_item": draft_item.model_dump(mode="json")},
                blueprint_id,
            )

        solved_item = self._load_output(state, "solve", item_no, stage_def_output("solve"))
        if stage_name == "critique":
            return (
                [state.stage_outputs[stage_key("solve", item_no)]],
                {"solved_item": solved_item.model_dump(mode="json")},
                blueprint_id,
            )

        critique_report = self._load_output(state, "critique", item_no, CritiqueReport)
        if stage_name == "revise":
            return (
                [
                    state.stage_outputs[stage_key("solve", item_no)],
                    state.stage_outputs[stage_key("critique", item_no)],
                ],
                {
                    "solved_item": solved_item.model_dump(mode="json"),
                    "critique_report": critique_report.model_dump(mode="json"),
                },
                blueprint_id,
            )

        if stage_name == "validate":
            return (
                [
                    state.stage_outputs[stage_key("revise", item_no)],
                    state.stage_outputs[stage_key("critique", item_no)],
                ],
                {},
                blueprint_id,
            )

        raise StateMachineError(f"Unsupported stage input construction: {stage_name}")

    def _load_output(self, state: OrchestrationState, stage_name: str, item_no: int | None, model_type):
        artifact_id = state.stage_outputs.get(stage_key(stage_name, item_no))
        if artifact_id is None:
            raise StateMachineError(f"Missing prerequisite output for {stage_name}:{item_no}")
        return self.store.load_model(artifact_id, model_type)

    def _state_path(self, run_id: str) -> Path:
        return self.store.root_dir / run_id / "orchestrator_state.json"

    def _save_state(self, state: OrchestrationState) -> OrchestrationState:
        state.updated_at = utc_now()
        path = self._state_path(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return state


def stage_def_output(stage_name: str):
    """Return the output model class for a stage name."""
    return get_stage_definition(stage_name).output_model
