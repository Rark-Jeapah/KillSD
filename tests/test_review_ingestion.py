"""Tests for offline review packet export/import against candidate pools."""

from __future__ import annotations

import json
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolBuildResult, CandidatePoolCandidateBundle
from src.assembly.mini_alpha import MiniAlphaCandidateInput, MiniAlphaManifestInput
from src.core.schemas import (
    ApprovalStatus,
    DifficultyBand,
    DraftItem,
    ItemBlueprint,
    ItemFormat,
    SolvedItem,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    ValidatedItem,
)
from src.eval.review_feedback import HumanReviewDecision, load_human_review_records
from src.eval.review_ops import (
    export_candidate_pool_review_packet,
    sync_candidate_pool_reviews,
)
from src.orchestrator.state_machine import RunStatus
from src.validators.report import DifficultyEstimate, ValidatorSectionResult, ValidatorSuiteReport


def _fixture_report(*, item_no: int, difficulty: DifficultyBand) -> ValidatorSuiteReport:
    final_report = ValidationReport(
        item_no=item_no,
        status=ValidationStatus.PASS,
        findings=[
            ValidationFinding(
                check_name="fixture_pass",
                passed=True,
                severity=ValidationSeverity.INFO,
                message="fixture pass",
                validator_name="test_fixture",
            )
        ],
        summary="fixture pass",
    )
    return ValidatorSuiteReport(
        spec_id="csat_math_2028",
        item_no=item_no,
        sections=[
            ValidatorSectionResult(
                validator_name="fixture_validator",
                findings=final_report.findings,
                metrics={"fixture": True},
            )
        ],
        difficulty_estimate=DifficultyEstimate(
            expected_step_count=3,
            concept_count=2,
            branching_factor=1.5,
            solver_disagreement_score=0.0,
            predicted_band=difficulty.value,
        ),
        final_report=final_report,
    )


def _write_bundle(
    *,
    root: Path,
    candidate_id: str,
    source_item_no: int,
    objective: str,
) -> CandidatePoolCandidateBundle:
    candidate_dir = root / "candidates" / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    blueprint = ItemBlueprint(
        item_no=source_item_no,
        domain="algebra",
        format=ItemFormat.MULTIPLE_CHOICE,
        score=3,
        difficulty=DifficultyBand.STANDARD,
        objective=objective,
        skill_tags=[f"{candidate_id}_skill"],
        choice_count=5,
        answer_type="choice_index",
    )
    draft = DraftItem(
        blueprint=blueprint,
        stem=f"{objective}에 맞는 조건을 판정하는 문항이다.",
        choices=["조건 가", "조건 나", "조건 다", "조건 라", "조건 마"],
        rubric="fixture rubric",
        answer_constraints=["choice_index"],
    )
    solved = SolvedItem(
        draft=draft,
        final_answer="4",
        correct_choice_index=4,
        correct_choice_value="조건 라",
        solution_steps=["핵심 조건을 정리한다.", "불필요한 경우를 제거한다.", "정답을 확정한다."],
        solution_summary=f"{candidate_id} summary",
    )
    report = _fixture_report(item_no=source_item_no, difficulty=DifficultyBand.STANDARD)
    validated = ValidatedItem(
        solved=solved,
        validation=report.final_report,
        approval_status=ApprovalStatus.APPROVED,
    )
    validated_item_path = candidate_dir / "validated_item.json"
    validator_report_path = candidate_dir / "validator_report.json"
    validated_item_path.write_text(validated.model_dump_json(indent=2), encoding="utf-8")
    validator_report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    bundle = CandidatePoolCandidateBundle(
        candidate_id=candidate_id,
        run_id=f"fixture-{candidate_id}",
        gauntlet_status="completed",
        source_atom_id=f"atom-{candidate_id}",
        family_id="fixture-family",
        source_item_id=f"source-{source_item_no}",
        source_item_no=source_item_no,
        domain="algebra",
        difficulty=DifficultyBand.STANDARD.value,
        format=ItemFormat.MULTIPLE_CHOICE,
        score=3,
        objective=objective,
        skill_tags=[f"{candidate_id}_skill"],
        approval_status=ApprovalStatus.APPROVED,
        validation_status=ValidationStatus.PASS,
        atom_signatures=[f"atom_{candidate_id}"],
        distractor_signatures=[f"distractor_{candidate_id}_1", f"distractor_{candidate_id}_2"],
        candidate_dir=str(candidate_dir),
        validated_item_path=str(validated_item_path),
        validator_report_path=str(validator_report_path),
    )
    (candidate_dir / "candidate_bundle.json").write_text(
        bundle.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return bundle


def test_candidate_pool_review_packet_ingests_labels_and_updates_manifests(tmp_path: Path) -> None:
    candidate_pool_dir = tmp_path / "candidate_pool"
    bundle_a = _write_bundle(
        root=candidate_pool_dir,
        candidate_id="cand-a",
        source_item_no=11,
        objective="로그식의 정의역 판정",
    )
    bundle_b = _write_bundle(
        root=candidate_pool_dir,
        candidate_id="cand-b",
        source_item_no=12,
        objective="연립조건에서 가능한 범위 판정",
    )

    mini_alpha_manifest_path = candidate_pool_dir / "mini_alpha_candidate_manifest.json"
    mini_alpha_manifest = MiniAlphaManifestInput(
        title="Candidate Pool Fixture",
        candidates=[
            MiniAlphaCandidateInput(
                candidate_id=bundle.candidate_id,
                validated_item_path=str(Path(bundle.validated_item_path).relative_to(candidate_pool_dir)),
                validator_report_path=str(
                    Path(bundle.validator_report_path).relative_to(candidate_pool_dir)
                ),
                source_atom_id=bundle.source_atom_id,
                family_id=bundle.family_id,
                source_item_id=bundle.source_item_id,
                source_item_no=bundle.source_item_no,
                atom_signatures=bundle.atom_signatures,
                distractor_signatures=bundle.distractor_signatures,
            )
            for bundle in (bundle_a, bundle_b)
        ],
    )
    mini_alpha_manifest_path.write_text(
        mini_alpha_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )

    candidate_pool_manifest = CandidatePoolBuildResult(
        spec_id="csat_math_2028",
        title="Candidate Pool Fixture",
        output_dir=str(candidate_pool_dir),
        status=RunStatus.COMPLETED,
        provider_name="deterministic",
        provider_settings={},
        candidate_count=2,
        eligible_candidate_count=2,
        slot_count=1,
        candidate_pool_manifest_path=str(candidate_pool_dir / "candidate_pool_manifest.json"),
        mini_alpha_manifest_path=str(mini_alpha_manifest_path),
        candidates=[bundle_a, bundle_b],
    )
    (candidate_pool_dir / "candidate_pool_manifest.json").write_text(
        candidate_pool_manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )

    export_result = export_candidate_pool_review_packet(
        candidate_pool_dir=candidate_pool_dir,
        output_dir=tmp_path / "packet",
    )
    packet_entries = [
        json.loads(line)
        for line in Path(export_result.jsonl_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    packet_entries[0]["review_label"].update(
        {
            "decision": "reject",
            "reason_code": "wording.awkward",
            "difficulty_label": "standard",
            "wording_naturalness": 1,
            "distractor_quality": 2,
            "curriculum_fit": 4,
            "notes": "문장이 어색해서 다시 생성해야 한다.",
        }
    )
    packet_entries[1]["review_label"].update({"decision": "accept"})
    Path(export_result.jsonl_path).write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in packet_entries) + "\n",
        encoding="utf-8",
    )

    import_result = sync_candidate_pool_reviews(
        candidate_pool_dir=candidate_pool_dir,
        incoming_reviews=load_human_review_records(Path(export_result.jsonl_path)),
    )

    assert import_result.imported_count == 2

    updated_manifest = CandidatePoolBuildResult.model_validate(
        json.loads((candidate_pool_dir / "candidate_pool_manifest.json").read_text(encoding="utf-8"))
    )
    assert updated_manifest.eligible_candidate_count == 1
    assert updated_manifest.candidates[0].review_summary is not None
    assert updated_manifest.candidates[0].review_summary.latest_decision == HumanReviewDecision.REJECT
    assert updated_manifest.candidates[1].review_summary is not None
    assert updated_manifest.candidates[1].review_summary.latest_decision == HumanReviewDecision.ACCEPT

    updated_mini_alpha = MiniAlphaManifestInput.model_validate(
        json.loads(mini_alpha_manifest_path.read_text(encoding="utf-8"))
    )
    candidate_by_id = {candidate.candidate_id: candidate for candidate in updated_mini_alpha.candidates}
    assert candidate_by_id["cand-a"].review_summary is not None
    assert candidate_by_id["cand-a"].review_summary.blocked_from_selection is True

    feedback_report = json.loads(
        (candidate_pool_dir / "review_feedback_report.json").read_text(encoding="utf-8")
    )
    assert feedback_report["rejected_candidate_count"] == 1
    assert feedback_report["top_reason_codes"][0]["reason_code"] == "wording.awkward"
    assert feedback_report["family_reject_rates"][0]["key"] == "fixture-family"
    assert feedback_report["regenerate_priority_list"][0]["source_atom_id"] == "atom-cand-a"
