"""Tests for the mini-alpha assembly workflow."""

from __future__ import annotations

import json
from pathlib import Path

from src.assembly.mini_alpha import MiniAlphaAssembler, MiniAlphaManifestInput, _sample_blueprints
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
from src.eval.discard_rate import HumanReviewDecision, HumanReviewRecord
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


def _candidate_payload(
    *,
    slot,
    candidate_id: str,
    source_item_no: int,
    stem: str | None = None,
    choices: list[str] | None = None,
    solution_steps: list[str] | None = None,
    skill_tags: list[str] | None = None,
) -> tuple[ValidatedItem, ValidatorSuiteReport]:
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
    stem_text = stem_descriptors[(slot.slot_no - 1) % len(stem_descriptors)].format(objective=slot.objective)
    blueprint = ItemBlueprint(
        item_no=source_item_no,
        domain=slot.domain,
        format=slot.format,
        score=slot.score,
        difficulty=slot.difficulty,
        objective=slot.objective,
        skill_tags=skill_tags or [f"{slot.domain}_{candidate_id}", f"{slot.difficulty.value}_{candidate_id}"],
        choice_count=5 if slot.format == ItemFormat.MULTIPLE_CHOICE else None,
        answer_type="choice_index" if slot.format == ItemFormat.MULTIPLE_CHOICE else "natural_number",
    )
    if slot.format == ItemFormat.MULTIPLE_CHOICE:
        candidate_choices = choices or [
            "조건 가",
            "조건 나",
            "조건 다",
            "조건 라",
            "조건 마",
        ]
        correct_choice_index = 4
        final_answer = "4"
        correct_choice_value = candidate_choices[correct_choice_index - 1]
    else:
        candidate_choices = []
        correct_choice_index = None
        final_answer = str(200 + source_item_no)
        correct_choice_value = None

    draft = DraftItem(
        blueprint=blueprint,
        stem=stem
        or stem_text,
        choices=candidate_choices,
        rubric="mini alpha fixture",
        answer_constraints=[blueprint.answer_type],
    )
    solved = SolvedItem(
        draft=draft,
        final_answer=final_answer,
        correct_choice_index=correct_choice_index,
        correct_choice_value=correct_choice_value,
        solution_steps=solution_steps
        or [
            f"{step_descriptors[(slot.slot_no + 0) % len(step_descriptors)]}.",
            f"{slot.objective}에 맞는 핵심 성질을 확인한다.",
            f"{step_descriptors[(slot.slot_no + 2) % len(step_descriptors)]}.",
        ],
        solution_summary=f"{candidate_id} 풀이 요약",
    )
    validated = ValidatedItem(
        solved=solved,
        validation=_fixture_report(item_no=source_item_no, difficulty=slot.difficulty).final_report,
        approval_status=ApprovalStatus.APPROVED,
    )
    report = _fixture_report(item_no=source_item_no, difficulty=slot.difficulty)
    return validated, report


def _write_candidate(
    *,
    root: Path,
    slot,
    candidate_id: str,
    source_item_no: int,
    atom_signatures: list[str] | None = None,
    distractor_signatures: list[str] | None = None,
    stem: str | None = None,
    choices: list[str] | None = None,
    solution_steps: list[str] | None = None,
    skill_tags: list[str] | None = None,
) -> dict[str, object]:
    validated, report = _candidate_payload(
        slot=slot,
        candidate_id=candidate_id,
        source_item_no=source_item_no,
        stem=stem,
        choices=choices,
        solution_steps=solution_steps,
        skill_tags=skill_tags,
    )
    validated_path = root / f"{candidate_id}.validated.json"
    report_path = root / f"{candidate_id}.report.json"
    validated_path.write_text(validated.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return {
        "candidate_id": candidate_id,
        "validated_item_path": str(validated_path),
        "validator_report_path": str(report_path),
        "source_item_no": source_item_no,
        "atom_signatures": atom_signatures or [],
        "distractor_signatures": distractor_signatures or [],
    }


def test_mini_alpha_assembles_artifacts_and_reports(tmp_path: Path) -> None:
    assembler = MiniAlphaAssembler(template_dir=TEMPLATE_DIR)
    slots = _sample_blueprints(assembler.spec, sample_size=10)
    candidate_dir = tmp_path / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    manifest_candidates: list[dict[str, object]] = []
    selected_source: dict[int, dict[str, object]] = {}

    for slot in slots:
        candidate_id = f"slot-{slot.slot_no}-base"
        entry = _write_candidate(
            root=candidate_dir,
            slot=slot,
            candidate_id=candidate_id,
            source_item_no=slot.sampled_from_item_no,
            atom_signatures=[f"atom_{slot.slot_no}_core"],
            distractor_signatures=[f"dst_{slot.slot_no}_{index}" for index in range(1, 4)],
        )
        manifest_candidates.append(entry)
        selected_source[slot.slot_no] = entry

    slot4 = slots[3]
    slot5 = slots[4]
    slot6 = slots[5]

    # This candidate should be avoided because it reuses atom and distractor signatures
    # from the selected slot-4 item.
    manifest_candidates.append(
        _write_candidate(
            root=candidate_dir,
            slot=slot5,
            candidate_id="slot-5-duplicate",
            source_item_no=205,
            atom_signatures=["atom_4_core"],
            distractor_signatures=["dst_4_1", "dst_4_2", "dst_4_3"],
            skill_tags=["shared_derivative_pattern"],
        )
    )

    # This candidate should be avoided because it is a hard similarity collision with slot 5.
    slot5_validated = json.loads(
        Path(selected_source[slot5.slot_no]["validated_item_path"]).read_text(encoding="utf-8")
    )
    manifest_candidates.append(
        _write_candidate(
            root=candidate_dir,
            slot=slot6,
            candidate_id="slot-6-collision",
            source_item_no=206,
            atom_signatures=["atom_6_collision"],
            distractor_signatures=["dst_6_collision"],
            stem=slot5_validated["solved"]["draft"]["stem"],
            choices=slot5_validated["solved"]["draft"]["choices"],
            solution_steps=slot5_validated["solved"]["solution_steps"],
            skill_tags=["collision_pattern"],
        )
    )

    # This candidate should be auto-discarded due to metadata leak even though it otherwise fits.
    manifest_candidates.append(
        _write_candidate(
            root=candidate_dir,
            slot=slot4,
            candidate_id="slot-4-metadata-leak",
            source_item_no=404,
            atom_signatures=["atom_bad_metadata"],
            distractor_signatures=["dst_bad_metadata"],
            stem="artifact_id 가 학생 노출 텍스트에 섞인 잘못된 문항이다.",
            skill_tags=["metadata_leak_candidate"],
        )
    )

    manifest = MiniAlphaManifestInput(
        title="Mini Alpha Fixture",
        candidates=manifest_candidates,  # type: ignore[arg-type]
    )
    manifest_path = tmp_path / "mini_alpha_manifest.input.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    gate_path = tmp_path / "real_item_validation.json"
    gate_path.write_text(
        json.dumps(
            {
                "item_id": "real_item_001",
                "status": "pass",
                "approval_status": "approved",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    human_reviews = [
        HumanReviewRecord(
            item_no=2,
            candidate_id="slot-2-base",
            decision=HumanReviewDecision.DISCARD,
            reasons=["human_reject: clarity"],
            notes="조건 서술을 다시 써야 한다.",
        ),
        HumanReviewRecord(
            item_no=9,
            candidate_id="slot-9-base",
            decision=HumanReviewDecision.REVISE,
            reasons=["human_reject: distractor"],
            notes="오답 매력이 약하다.",
        ),
    ]

    result = assembler.assemble(
        run_id="mini-alpha-test",
        manifest=assembler.load_manifest(manifest_path),
        output_dir=tmp_path / "out",
        compile_pdf=False,
        real_item_validation_path=gate_path,
        human_reviews=human_reviews,
    )

    assert result.metrics.structure_errors == 0
    assert result.metrics.answer_errors == 0
    assert result.metrics.metadata_leaks == 0
    assert result.metrics.hard_similarity_collisions == 0
    assert result.discard_rate_report.auto_discarded_count == 1
    assert result.discard_rate_report.human_reviewed_count == 2
    assert result.discard_rate_report.human_discarded_count == 1
    assert result.discard_rate_report.human_discard_rate == 0.5

    selected_ids = [selection.candidate_id for selection in result.selected]
    assert len(selected_ids) == 10
    assert "slot-5-duplicate" not in selected_ids
    assert "slot-6-collision" not in selected_ids
    assert "slot-4-metadata-leak" not in selected_ids

    output_dir = Path(result.output_dir)
    exam_tex = output_dir / "exam.tex"
    answer_key_tex = output_dir / "answer_key.tex"
    validation_tex = output_dir / "validation_report.tex"
    review_packet = Path(result.review_packet_path)
    human_review_template = Path(result.human_review_template_path)
    discard_report = Path(result.discard_rate_report_path)
    regenerate_candidates = Path(result.regenerate_candidates_path)
    bundle_json = Path(result.bundle_json_path)
    manifest_json = Path(result.manifest_path)

    assert exam_tex.exists()
    assert answer_key_tex.exists()
    assert validation_tex.exists()
    assert review_packet.exists()
    assert human_review_template.exists()
    assert discard_report.exists()
    assert regenerate_candidates.exists()
    assert bundle_json.exists()
    assert manifest_json.exists()

    exam_source = exam_tex.read_text(encoding="utf-8")
    review_source = review_packet.read_text(encoding="utf-8")
    regenerate_payload = json.loads(regenerate_candidates.read_text(encoding="utf-8"))
    discard_payload = json.loads(discard_report.read_text(encoding="utf-8"))

    assert "Mini Alpha Fixture" in exam_source
    assert "1번부터 7번까지는 5지선다형, 8번부터 10번까지는 단답형이다." in exam_source
    assert "Mini Alpha Review Packet" in review_source
    assert discard_payload["collection_ready"] is True
    assert [item["candidate_id"] for item in regenerate_payload] == ["slot-2-base", "slot-9-base"]
    assert regenerate_payload[0]["suggested_action"] == "regenerate"
    assert regenerate_payload[1]["suggested_action"] == "revise_or_regenerate"
    assert len(result.render_result.documents) == 3
    assert all(document.compiled is False for document in result.render_result.documents)
