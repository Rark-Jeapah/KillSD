"""Tests for review-driven filtering and discard/regenerate feedback artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from src.assembly.mini_alpha import (
    MiniAlphaAssembler,
    MiniAlphaCandidateInput,
    MiniAlphaManifestInput,
    _sample_blueprints,
)
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
from src.eval.review_feedback import (
    CandidateReviewSummary,
    HumanReviewDecision,
    HumanReviewRecord,
    load_human_review_records,
)
from src.eval.review_ops import (
    export_generated_exam_review_packet,
    sync_generated_exam_reviews,
)
from src.validators.report import DifficultyEstimate, ValidatorSectionResult, ValidatorSuiteReport


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "src" / "render" / "templates"


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


def _write_candidate(
    *,
    root: Path,
    slot,
    candidate_id: str,
    source_item_no: int,
    objective: str | None = None,
) -> tuple[Path, Path]:
    stem_descriptors = [
        "{objective}를 판단하기 위해 숨은 조건을 먼저 읽어내야 한다.",
        "그래프에서 얻은 정보를 바탕으로 {objective}의 결론을 고르는 문제다.",
        "{objective}가 성립하려면 어떤 범위가 필요한지 살피는 상황이다.",
        "주어진 관계를 정리한 뒤 {objective}에 맞는 값을 판정해야 한다.",
        "여러 조건을 합쳐 {objective}가 언제 가능한지 추론하는 문항이다.",
        "표현이 바뀐 식을 비교하여 {objective}의 핵심 결론을 찾는다.",
        "단계별 성질을 연결해 {objective}에 도달하는 과정을 묻는다.",
        "경우를 나누어 본 뒤 {objective}에 맞는 답만 남기는 문제다.",
        "조건 사이의 충돌 여부를 점검하며 {objective}를 완성해야 한다.",
        "마지막까지 남는 관계를 이용해 {objective}의 결론을 확정한다.",
    ]
    step_descriptors = [
        "조건을 모아 핵심 관계를 세운다",
        "불필요한 경우를 제거한다",
        "필요한 성질만 남겨 비교한다",
        "결론으로 이어지는 기준을 고른다",
        "최종 판단을 확정한다",
    ]
    blueprint = ItemBlueprint(
        item_no=source_item_no,
        domain=slot.domain,
        format=slot.format,
        score=slot.score,
        difficulty=slot.difficulty,
        objective=objective or slot.objective,
        skill_tags=[f"{candidate_id}_skill"],
        choice_count=5 if slot.format == ItemFormat.MULTIPLE_CHOICE else None,
        answer_type="choice_index" if slot.format == ItemFormat.MULTIPLE_CHOICE else "natural_number",
    )
    draft = DraftItem(
        blueprint=blueprint,
        stem=stem_descriptors[(slot.slot_no - 1) % len(stem_descriptors)].format(
            objective=blueprint.objective
        ),
        choices=["조건 가", "조건 나", "조건 다", "조건 라", "조건 마"]
        if slot.format == ItemFormat.MULTIPLE_CHOICE
        else [],
        rubric="fixture rubric",
        answer_constraints=[blueprint.answer_type],
    )
    solved = SolvedItem(
        draft=draft,
        final_answer="4" if slot.format == ItemFormat.MULTIPLE_CHOICE else str(200 + source_item_no),
        correct_choice_index=4 if slot.format == ItemFormat.MULTIPLE_CHOICE else None,
        correct_choice_value="조건 라" if slot.format == ItemFormat.MULTIPLE_CHOICE else None,
        solution_steps=[
            f"{step_descriptors[(slot.slot_no + 0) % len(step_descriptors)]}.",
            f"{blueprint.objective}에 맞는 핵심 성질을 확인한다.",
            f"{step_descriptors[(slot.slot_no + 2) % len(step_descriptors)]}.",
        ],
        solution_summary=f"{candidate_id} summary",
    )
    report = _fixture_report(item_no=source_item_no, difficulty=slot.difficulty)
    validated = ValidatedItem(
        solved=solved,
        validation=report.final_report,
        approval_status=ApprovalStatus.APPROVED,
    )
    validated_path = root / f"{candidate_id}.validated.json"
    report_path = root / f"{candidate_id}.report.json"
    validated_path.write_text(validated.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return validated_path, report_path


def test_review_feedback_loop_blocks_rejected_candidates_and_refreshes_reports(tmp_path: Path) -> None:
    assembler = MiniAlphaAssembler(template_dir=TEMPLATE_DIR)
    slots = _sample_blueprints(assembler.spec, sample_size=10)
    candidate_root = tmp_path / "candidates"
    candidate_root.mkdir(parents=True, exist_ok=True)

    manifest_candidates: list[MiniAlphaCandidateInput] = []
    blocked_review = HumanReviewRecord(
        candidate_id="slot-1-base",
        decision=HumanReviewDecision.REJECT,
        reason_code="historical.reject",
        notes="이전 검토에서 폐기된 후보",
    )
    blocked_summary = CandidateReviewSummary(
        total_labels=1,
        actionable_labels=1,
        accept_count=0,
        revise_count=0,
        reject_count=1,
        latest_decision=HumanReviewDecision.REJECT,
        latest_reason_code="historical.reject",
        latest_review=blocked_review,
        blocked_from_selection=True,
    )

    for slot in slots:
        validated_path, report_path = _write_candidate(
            root=candidate_root,
            slot=slot,
            candidate_id=f"slot-{slot.slot_no}-base",
            source_item_no=slot.sampled_from_item_no,
        )
        manifest_candidates.append(
            MiniAlphaCandidateInput(
                candidate_id=f"slot-{slot.slot_no}-base",
                validated_item_path=str(validated_path),
                validator_report_path=str(report_path),
                source_item_no=slot.sampled_from_item_no,
                source_atom_id=f"atom-slot-{slot.slot_no}-base",
                family_id="fixture-family",
                source_item_id=f"source-{slot.sampled_from_item_no}",
                atom_signatures=[f"atom_slot_{slot.slot_no}_base"],
                distractor_signatures=[f"distractor_slot_{slot.slot_no}_base"],
                review_summary=blocked_summary if slot.slot_no == 1 else None,
            )
        )

    alt_validated_path, alt_report_path = _write_candidate(
        root=candidate_root,
        slot=slots[0],
        candidate_id="slot-1-alt",
        source_item_no=901,
        objective="대체 후보의 조건 판정",
    )
    manifest_candidates.append(
        MiniAlphaCandidateInput(
            candidate_id="slot-1-alt",
            validated_item_path=str(alt_validated_path),
            validator_report_path=str(alt_report_path),
            source_item_no=901,
            source_atom_id="atom-slot-1-alt",
            family_id="fixture-family",
            source_item_id="source-901",
            atom_signatures=["atom_slot_1_alt"],
            distractor_signatures=["distractor_slot_1_alt"],
        )
    )

    manifest = MiniAlphaManifestInput(
        title="Review Feedback Fixture",
        slots=slots,
        candidates=manifest_candidates,
    )
    manifest_path = tmp_path / "mini_alpha_manifest.input.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    result = assembler.assemble(
        run_id="review-feedback-loop",
        manifest=assembler.load_manifest(manifest_path),
        output_dir=tmp_path / "out",
        compile_pdf=False,
    )
    (Path(result.output_dir) / "candidate_manifest.json").write_text(
        assembler.load_manifest(manifest_path).model_dump_json(indent=2),
        encoding="utf-8",
    )

    selected_ids = [selection.candidate_id for selection in result.selected]
    assert "slot-1-base" not in selected_ids
    assert "slot-1-alt" in selected_ids

    packet_result = export_generated_exam_review_packet(
        output_dir=Path(result.output_dir),
        packet_dir=tmp_path / "packet",
    )
    packet_entries = [
        json.loads(line)
        for line in Path(packet_result.jsonl_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labels_by_candidate = {entry["candidate_id"]: entry for entry in packet_entries}
    labels_by_candidate["slot-1-alt"]["review_label"].update(
        {
            "decision": "reject",
            "reason_code": "wording.awkward",
            "difficulty_label": "standard",
            "wording_naturalness": 1,
            "distractor_quality": 2,
            "curriculum_fit": 4,
            "notes": "문항 문장이 부자연스럽다.",
        }
    )
    labels_by_candidate["slot-2-base"]["review_label"].update(
        {
            "decision": "revise",
            "reason_code": "distractor.weak",
            "difficulty_label": "standard",
            "wording_naturalness": 3,
            "distractor_quality": 1,
            "curriculum_fit": 4,
            "notes": "오답 매력을 높여야 한다.",
        }
    )
    Path(packet_result.jsonl_path).write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in packet_entries) + "\n",
        encoding="utf-8",
    )

    import_result = sync_generated_exam_reviews(
        output_dir=Path(result.output_dir),
        incoming_reviews=load_human_review_records(Path(packet_result.jsonl_path)),
    )

    assert import_result.imported_count == 2

    discard_report = json.loads(Path(result.discard_rate_report_path).read_text(encoding="utf-8"))
    regenerate_payload = json.loads(Path(result.regenerate_candidates_path).read_text(encoding="utf-8"))
    feedback_report = json.loads((Path(result.output_dir) / "review_feedback_report.json").read_text(encoding="utf-8"))
    candidate_outcomes = json.loads((Path(result.output_dir) / "candidate_outcomes.json").read_text(encoding="utf-8"))

    assert discard_report["human_discarded_count"] == 1
    assert discard_report["human_revision_count"] == 1
    assert discard_report["review_feedback"]["top_reason_codes"][0]["reason_code"] == "wording.awkward"
    assert discard_report["review_feedback"]["family_reject_rates"][0]["key"] == "fixture-family"
    assert feedback_report["regenerate_priority_list"][0]["source_atom_id"] == "atom-slot-1-alt"

    assert [item["candidate_id"] for item in regenerate_payload[:2]] == ["slot-1-alt", "slot-2-base"]
    assert regenerate_payload[0]["reason_code"] == "wording.awkward"
    assert regenerate_payload[0]["priority_score"] > regenerate_payload[1]["priority_score"]

    blocked_outcome = next(
        outcome for outcome in candidate_outcomes if outcome["candidate_id"] == "slot-1-base"
    )
    assert blocked_outcome["outcome"] == "auto_discarded"
    assert "review_rejected" in blocked_outcome["reasons"]
