"""Tests for the registry-driven real_item_001 gauntlet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.core.schemas import ExamMode, PromptPacket
from src.core.storage import ArtifactStore
from src.distill.atom_extractor import InsightAtom
from src.orchestrator.real_item_families import RealItemFamilySelectionError
from src.orchestrator.real_item_gauntlet import (
    REAL_ITEM_DEFAULT_ATOM_ID,
    RealItemGauntlet,
    RealItemProvider,
    load_insight_atom,
)
from src.orchestrator.state_machine import RunStatus


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = REPO_ROOT / "src" / "prompts"


def _gauntlet(root: Path, provider: RealItemProvider | None) -> RealItemGauntlet:
    store = ArtifactStore(root_dir=root / "artifacts", db_path=root / "app.db")
    return RealItemGauntlet(
        artifact_store=store,
        prompt_dir=PROMPT_DIR,
        provider=provider,
    )


def _run_manual_to_completion(
    *,
    gauntlet: RealItemGauntlet,
    atom: InsightAtom,
    run_id: str,
    output_dir: Path,
    seed: int,
) -> Any:
    provider = RealItemProvider()
    result = gauntlet.run(
        run_id=run_id,
        atom=atom,
        mode=ExamMode.MANUAL,
        output_dir=output_dir,
        seed=seed,
    )

    rounds = 0
    while result.status == RunStatus.WAITING_MANUAL and rounds < 8:
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
            run_id=run_id,
            atom=atom,
            mode=ExamMode.MANUAL,
            output_dir=output_dir,
            seed=seed,
        )
        rounds += 1

    assert rounds <= 8
    return result


def _bundle_contract(result: Any) -> dict[str, Any]:
    item_payload = json.loads(Path(result.item_json_path).read_text(encoding="utf-8"))
    solution_payload = json.loads(Path(result.solution_json_path).read_text(encoding="utf-8"))
    validation_payload = json.loads(Path(result.validation_json_path).read_text(encoding="utf-8"))
    return {
        "item": {
            "item_id": item_payload["item_id"],
            "item_no": item_payload["item_no"],
            "format": item_payload["format"],
            "score": item_payload["score"],
            "stem": item_payload["stem"],
            "choices": item_payload["choices"],
        },
        "solution": {
            "item_id": solution_payload["item_id"],
            "item_no": solution_payload["item_no"],
            "final_answer": solution_payload["final_answer"],
            "correct_choice_index": solution_payload["correct_choice_index"],
            "correct_choice_value": solution_payload["correct_choice_value"],
            "solution_steps": solution_payload["solution_steps"],
            "solution_summary": solution_payload["solution_summary"],
        },
        "validation": {
            "item_id": validation_payload["item_id"],
            "atom_id": validation_payload["atom_id"],
            "status": validation_payload["status"],
            "approval_status": validation_payload["approval_status"],
            "success_criteria": validation_payload["success_criteria"],
            "regenerate_rule": validation_payload["regenerate_rule"],
            "custom_checks": [
                {
                    "check_name": check["check_name"],
                    "passed": check["passed"],
                }
                for check in validation_payload["custom_checks"]
            ],
        },
    }


@pytest.mark.parametrize(
    ("atom_id", "expected_family_id", "expected_format"),
    [
        (REAL_ITEM_DEFAULT_ATOM_ID, "calculus_derivative_vertex_mcq", "multiple_choice"),
        ("atom-311a529ea04c", "algebra_log_domain_filter_mcq", "multiple_choice"),
        ("atom-c2ed46456b9d", "algebra_log_quadratic_filter_mcq", "multiple_choice"),
        ("atom-5480edcc0dcb", "probability_conditional_cases_short", "short_answer"),
        ("atom-0ce427cc63df", "probability_conditional_ratio_short", "short_answer"),
    ],
)
def test_real_item_gauntlet_routes_supported_families(
    tmp_path: Path,
    atom_id: str,
    expected_family_id: str,
    expected_format: str,
) -> None:
    atom = load_insight_atom(repo_root=REPO_ROOT, atom_id=atom_id)
    gauntlet = _gauntlet(tmp_path, RealItemProvider())
    run_id = f"route-{expected_family_id}"

    result = gauntlet.run(
        run_id=run_id,
        atom=atom,
        mode=ExamMode.API,
        output_dir=tmp_path / expected_family_id,
        seed=17,
    )

    assert result.status == RunStatus.COMPLETED
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

    state = gauntlet.load_state(run_id)
    assert state is not None
    assert state.family_id == expected_family_id

    contract = _bundle_contract(result)
    assert contract["item"]["item_id"] == "real_item_001"
    assert contract["item"]["format"] == expected_format
    assert contract["validation"]["status"] == "pass"
    assert contract["validation"]["regenerate_rule"]["action"] == "keep"
    assert contract["validation"]["success_criteria"]["core_validation_pass"] is True
    assert contract["validation"]["success_criteria"]["no_internal_metadata_leak"] is True
    assert contract["validation"]["success_criteria"]["no_placeholder_wording"] is True
    if expected_format == "multiple_choice":
        assert len(contract["item"]["choices"]) == 5
        assert contract["solution"]["correct_choice_index"] is not None
        assert contract["solution"]["correct_choice_value"] is not None
    else:
        assert contract["item"]["choices"] == []
        assert contract["solution"]["correct_choice_index"] is None
        assert contract["solution"]["correct_choice_value"] is None


@pytest.mark.parametrize("atom_id", [REAL_ITEM_DEFAULT_ATOM_ID, "atom-0ce427cc63df"])
def test_real_item_gauntlet_manual_and_api_are_equivalent(
    tmp_path: Path,
    atom_id: str,
) -> None:
    atom = load_insight_atom(repo_root=REPO_ROOT, atom_id=atom_id)

    api_gauntlet = _gauntlet(tmp_path / "api", RealItemProvider())
    api_result = api_gauntlet.run(
        run_id=f"api-{atom_id}",
        atom=atom,
        mode=ExamMode.API,
        output_dir=tmp_path / "api-bundle",
        seed=7,
    )

    manual_gauntlet = _gauntlet(tmp_path / "manual", None)
    manual_result = _run_manual_to_completion(
        gauntlet=manual_gauntlet,
        atom=atom,
        run_id=f"manual-{atom_id}",
        output_dir=tmp_path / "manual-bundle",
        seed=7,
    )

    assert api_result.status == RunStatus.COMPLETED
    assert manual_result.status == RunStatus.COMPLETED
    assert _bundle_contract(api_result) == _bundle_contract(manual_result)

    manual_state = manual_gauntlet.load_state(f"manual-{atom_id}")
    assert manual_state is not None
    assert set(manual_state.stage_prompt_paths) == {"draft_item", "solve", "critique", "revise"}


def test_real_item_gauntlet_errors_cleanly_when_no_family_matches(tmp_path: Path) -> None:
    unsupported_atom = InsightAtom(
        atom_id="atom-unsupported-family",
        label="unsupported topic",
        topic="matrix_inverse",
        prerequisites=["matrix"],
        allowed_answer_forms=["choice_index"],
    )
    gauntlet = _gauntlet(tmp_path, RealItemProvider())

    with pytest.raises(RealItemFamilySelectionError, match="No real-item family matches"):
        gauntlet.run(
            run_id="unsupported-family",
            atom=unsupported_atom,
            mode=ExamMode.API,
            output_dir=tmp_path / "unsupported",
            seed=3,
        )
