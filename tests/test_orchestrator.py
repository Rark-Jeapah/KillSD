"""End-to-end tests for the generation orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.schemas import ExamMode, PromptPacket, RenderBundle
from src.core.storage import ArtifactStore
from src.orchestrator.state_machine import GenerationStateMachine, RunStatus
from src.providers.mock_provider import MockProvider


PROMPT_DIR = Path(__file__).resolve().parents[1] / "src" / "prompts"


def test_api_mode_e2e_with_mock_provider(tmp_path: Path) -> None:
    store = ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db")
    machine = GenerationStateMachine(
        artifact_store=store,
        prompt_dir=PROMPT_DIR,
        provider=MockProvider(),
    )

    state = machine.run_exam(run_id="api-e2e", mode=ExamMode.API, seed=11)

    assert state.status == RunStatus.COMPLETED
    assert state.render_bundle_artifact_id is not None
    render_bundle = store.load_model(state.render_bundle_artifact_id, RenderBundle)
    assert len(render_bundle.items) == 30
    assert render_bundle.answer_key[1] == "1"
    assert render_bundle.items[0].solved.correct_choice_index == 1
    assert any(record.stage_name == "assemble" for record in state.history)
    assert any(record.prompt_hash for record in state.history if record.prompt_hash is not None)


def test_manual_mode_export_import_resume(tmp_path: Path) -> None:
    store = ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db")
    machine = GenerationStateMachine(
        artifact_store=store,
        prompt_dir=PROMPT_DIR,
        provider=MockProvider(),
    )

    state = machine.run_plan(run_id="manual-e2e", mode=ExamMode.MANUAL, seed=7)

    assert state.status == RunStatus.WAITING_MANUAL
    pending_paths = state.pending_prompt_paths()
    assert len(pending_paths) == 1

    packet_path = Path(pending_paths[0])
    packet = PromptPacket.model_validate(json.loads(packet_path.read_text(encoding="utf-8")))
    response = MockProvider().invoke(packet)
    response_path = machine.manual_controller.response_path_for(packet)
    response_path.write_text(json.dumps(response.output, ensure_ascii=False, indent=2), encoding="utf-8")

    imported_state = machine.import_manual_exchange(
        run_id="manual-e2e",
        packet_path=packet_path,
        response_path=response_path,
    )
    assert "exam_blueprint" in imported_state.stage_outputs

    resumed_state = machine.run_plan(run_id="manual-e2e", mode=ExamMode.MANUAL, seed=7)
    assert resumed_state.status == RunStatus.COMPLETED

    item_state = machine.run_item_draft(
        run_id="manual-e2e",
        item_no=1,
        mode=ExamMode.MANUAL,
        seed=7,
    )
    assert item_state.status == RunStatus.WAITING_MANUAL
    assert any("item_blueprint__item_1" in path for path in item_state.pending_prompt_paths())
