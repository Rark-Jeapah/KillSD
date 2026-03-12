"""Regression suite for intentionally invalid validator fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.core.schemas import (
    CritiqueReport,
    DifficultyBand,
    DraftItem,
    ItemBlueprint,
    ItemFormat,
    SolvedItem,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.validators.difficulty_estimator import validate_difficulty_variance
from src.validators.reason_codes import REASON_CODE_REGISTRY
from src.validators.report import (
    DifficultyEstimate,
    ValidationContext,
    build_validation_report,
    load_distilled_resources,
    load_similarity_thresholds,
    run_validator_suite,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "invalid_items"
SPEC = CSATMath2028Plugin().load_exam_spec()
RESOURCES = load_distilled_resources(REPO_ROOT, SPEC.spec_id)
THRESHOLDS = load_similarity_thresholds(REPO_ROOT / "config" / "similarity_thresholds.json")
STATUS_PREFIX = {
    "fail": "Rejected:",
    "needs_revision": "Needs revision:",
}
RECOMMENDATION_BY_STATUS = {
    "fail": "regenerate",
    "needs_revision": "revise",
}


def _load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_blueprint(payload: dict[str, Any]) -> ItemBlueprint:
    return ItemBlueprint(
        item_no=payload["item_no"],
        domain=payload["domain"],
        format=ItemFormat(payload["format"]),
        score=payload["score"],
        difficulty=DifficultyBand(payload["difficulty"]),
        objective=payload["objective"],
        skill_tags=payload.get("skill_tags", []),
        choice_count=payload.get("choice_count"),
        answer_type=payload.get("answer_type", "choice_index"),
    )


def _build_draft(payload: dict[str, Any], *, blueprint: ItemBlueprint) -> DraftItem:
    kwargs = {
        "blueprint": blueprint,
        "stem": payload["stem"],
        "choices": payload.get("choices", []),
        "rubric": payload["rubric"],
        "answer_constraints": payload.get("answer_constraints", [blueprint.answer_type]),
    }
    if payload.get("unsafe_construct", False):
        return DraftItem.model_construct(**kwargs)
    return DraftItem(**kwargs)


def _build_solved_item(payload: dict[str, Any]) -> SolvedItem:
    blueprint = _build_blueprint(payload["blueprint"])
    draft = _build_draft(payload["draft"], blueprint=blueprint)
    solved_kwargs = {
        "draft": draft,
        "final_answer": payload["solved"]["final_answer"],
        "correct_choice_index": payload["solved"].get("correct_choice_index"),
        "correct_choice_value": payload["solved"].get("correct_choice_value"),
        "solution_steps": payload["solved"]["solution_steps"],
        "solution_summary": payload["solved"]["solution_summary"],
    }
    if payload["solved"].get("unsafe_construct", False):
        return SolvedItem.model_construct(**solved_kwargs)
    return SolvedItem(**solved_kwargs)


def _materialize_assets(tmp_path: Path, fixture: dict[str, Any]) -> Path | None:
    context_payload = fixture.get("context", {})
    asset_refs = context_payload.get("asset_refs", [])
    asset_files = context_payload.get("asset_files", [])
    if not asset_refs and not asset_files:
        return None

    asset_root = tmp_path / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)
    for asset_file in asset_files:
        candidate = asset_root / asset_file["path"]
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(asset_file["content"], encoding="utf-8")
    return asset_root


def _run_item_fixture(fixture: dict[str, Any], *, tmp_path: Path):
    solved_item = _build_solved_item(fixture["item"])
    asset_root = _materialize_assets(tmp_path, fixture)
    resources = RESOURCES.model_copy(
        update={"diagram_asset_root": str(asset_root) if asset_root is not None else None}
    )
    context_payload = fixture.get("context", {})
    validation_context = ValidationContext.model_construct(
        spec=SPEC,
        solved_item=solved_item,
        critique_report=CritiqueReport(
            item_no=solved_item.draft.blueprint.item_no,
            summary="invalid fixture",
            findings=[],
            requires_revision=False,
        ),
        resources=resources,
        similarity_thresholds=THRESHOLDS,
        cross_check_answer=context_payload.get("cross_check_answer"),
        expected_answer=context_payload.get("expected_answer"),
        asset_refs=context_payload.get("asset_refs", []),
    )
    suite_report, _ = run_validator_suite(context=validation_context)
    return suite_report.final_report


def _run_difficulty_set_fixture(fixture: dict[str, Any]):
    estimates = [
        DifficultyEstimate.model_validate(estimate_payload)
        for estimate_payload in fixture["estimates"]
    ]
    section = validate_difficulty_variance(estimates=estimates)
    return build_validation_report(item_no=0, sections=[section])


FIXTURE_PATHS = sorted(FIXTURE_DIR.glob("*.json"))


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda path: path.stem)
def test_invalid_fixture_reason_codes_are_stable(fixture_path: Path, tmp_path: Path) -> None:
    fixture = _load_fixture(fixture_path)
    expected_codes = set(fixture["expected_reason_codes"])

    assert expected_codes, f"{fixture_path.name} must declare at least one expected reason code"
    assert expected_codes <= REASON_CODE_REGISTRY.keys()

    if fixture["kind"] == "item":
        report = _run_item_fixture(fixture, tmp_path=tmp_path)
    elif fixture["kind"] == "difficulty_set":
        report = _run_difficulty_set_fixture(fixture)
    else:  # pragma: no cover - defensive guard for future fixture types
        raise AssertionError(f"Unsupported invalid fixture kind: {fixture['kind']}")

    failed_codes = {finding.reason_code for finding in report.findings if not finding.passed}

    assert failed_codes == expected_codes
    assert report.status.value == fixture["expected_status"]
    assert report.hard_fail is fixture["expected_hard_fail"]
    assert report.soft_fail is fixture["expected_soft_fail"]
    assert report.summary.startswith(STATUS_PREFIX[fixture["expected_status"]])
    assert report.regenerate_recommendation.value == RECOMMENDATION_BY_STATUS[fixture["expected_status"]]
    for reason_code in sorted(expected_codes):
        assert reason_code in report.summary
