"""Tests for the single-item real_item_001 gauntlet."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.schemas import ExamMode, PromptPacket
from src.core.storage import ArtifactStore
from src.orchestrator.real_item_gauntlet import (
    REAL_ITEM_DEFAULT_ATOM_ID,
    RealItemGauntlet,
    RealItemProvider,
    load_insight_atom,
)
from src.orchestrator.state_machine import RunStatus


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = REPO_ROOT / "src" / "prompts"


def _gauntlet(tmp_path: Path, provider: RealItemProvider | None) -> RealItemGauntlet:
    store = ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db")
    return RealItemGauntlet(
        artifact_store=store,
        prompt_dir=PROMPT_DIR,
        provider=provider,
    )


def test_real_item_gauntlet_api_mode_end_to_end(tmp_path: Path) -> None:
    atom = load_insight_atom(repo_root=REPO_ROOT, atom_id=REAL_ITEM_DEFAULT_ATOM_ID)
    gauntlet = _gauntlet(tmp_path, RealItemProvider())

    result = gauntlet.run(
        run_id="real-item-api",
        atom=atom,
        mode=ExamMode.API,
        output_dir=tmp_path / "bundle",
        seed=17,
    )

    assert result.status == RunStatus.COMPLETED
    assert result.validation_artifact_id is not None
    assert result.item_json_path is not None
    assert result.solution_json_path is not None
    assert result.validation_json_path is not None
    assert result.review_sheet_path is not None
    assert result.item_pdf_path is not None
    assert result.lineage_json_path is not None
    assert Path(result.item_json_path).exists()
    assert Path(result.solution_json_path).exists()
    assert Path(result.validation_json_path).exists()
    assert Path(result.review_sheet_path).exists()
    assert Path(result.item_pdf_path).exists()
    assert Path(result.lineage_json_path).exists()
    assert result.cost_summary.estimated_cost_usd > 0

    item_payload = json.loads(Path(result.item_json_path).read_text(encoding="utf-8"))
    solution_payload = json.loads(Path(result.solution_json_path).read_text(encoding="utf-8"))
    validation_payload = json.loads(Path(result.validation_json_path).read_text(encoding="utf-8"))

    assert item_payload["item_id"] == "real_item_001"
    assert len(item_payload["choices"]) == 5
    assert "모의 문항" not in item_payload["stem"]
    assert "placeholder" not in item_payload["stem"].lower()
    assert solution_payload["final_answer"] == "4"
    assert solution_payload["correct_choice_index"] == 4
    assert len(solution_payload["solution_steps"]) >= 4
    assert any("따라서" in step or "이므로" in step for step in solution_payload["solution_steps"])
    assert validation_payload["status"] == "pass"
    assert validation_payload["success_criteria"]["mcq_answer_key_in_range"] is True
    assert validation_payload["success_criteria"]["no_internal_metadata_leak"] is True
    assert validation_payload["success_criteria"]["no_placeholder_wording"] is True
    assert validation_payload["success_criteria"]["solver_reasoning_explicit"] is True
    assert validation_payload["success_criteria"]["distractors_non_trivial"] is True
    assert validation_payload["regenerate_rule"]["action"] == "keep"


def test_real_item_gauntlet_manual_mode_uses_same_contract(tmp_path: Path) -> None:
    atom = load_insight_atom(repo_root=REPO_ROOT, atom_id=REAL_ITEM_DEFAULT_ATOM_ID)
    gauntlet = _gauntlet(tmp_path, None)
    provider = RealItemProvider()
    output_dir = tmp_path / "manual-bundle"

    result = gauntlet.run(
        run_id="real-item-manual",
        atom=atom,
        mode=ExamMode.MANUAL,
        output_dir=output_dir,
        seed=7,
    )

    max_rounds = 8
    rounds = 0
    while result.status == RunStatus.WAITING_MANUAL and rounds < max_rounds:
        assert result.pending_prompt_paths
        packet_path = Path(result.pending_prompt_paths[0])
        packet = PromptPacket.model_validate(json.loads(packet_path.read_text(encoding="utf-8")))
        response = provider.invoke(packet)
        response_path = gauntlet.manual_controller.response_path_for(packet)
        response_path.write_text(
            json.dumps(response.output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result = gauntlet.run(
            run_id="real-item-manual",
            atom=atom,
            mode=ExamMode.MANUAL,
            output_dir=output_dir,
            seed=7,
        )
        rounds += 1

    assert rounds <= max_rounds
    assert result.status == RunStatus.COMPLETED
    assert result.item_json_path is not None
    assert result.solution_json_path is not None
    assert result.validation_json_path is not None

    item_payload = json.loads(Path(result.item_json_path).read_text(encoding="utf-8"))
    solution_payload = json.loads(Path(result.solution_json_path).read_text(encoding="utf-8"))
    validation_payload = json.loads(Path(result.validation_json_path).read_text(encoding="utf-8"))

    assert item_payload["choices"][3] == "a \\ge 12"
    assert solution_payload["correct_choice_value"] == "a \\ge 12"
    assert validation_payload["status"] == "pass"
    assert validation_payload["success_criteria"]["core_validation_pass"] is True

    manual_state = gauntlet.load_state("real-item-manual")
    assert manual_state is not None
    exported_packets = set(manual_state.stage_prompt_paths)
    assert exported_packets == {"draft_item", "solve", "critique", "revise"}
