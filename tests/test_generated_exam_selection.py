"""Selection-focused tests for the generated-exam pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolCandidateBundle
from src.assembly.mini_alpha import MiniAlphaSlotSpec
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
from src.pipeline.generated_exam import GeneratedExamPipeline
from src.validators.report import DifficultyEstimate, ValidatorSectionResult, ValidatorSuiteReport


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "src" / "render" / "templates"


def _sample_slots(sample_size: int = 15) -> list[MiniAlphaSlotSpec]:
    settings_payload = json.loads(
        (REPO_ROOT / "exam_specs" / "csat_math_2028.yaml").read_text(encoding="utf-8")
    )
    blueprints = settings_payload["default_item_blueprints"]
    last_index = len(blueprints) - 1
    sampled_indices: list[int] = []
    for slot_index in range(sample_size):
        raw_index = round(slot_index * last_index / max(sample_size - 1, 1))
        if sampled_indices and raw_index <= sampled_indices[-1]:
            raw_index = sampled_indices[-1] + 1
        sampled_indices.append(raw_index)

    slots: list[MiniAlphaSlotSpec] = []
    for slot_no, blueprint_index in enumerate(sampled_indices, start=1):
        blueprint = blueprints[blueprint_index]
        slots.append(
            MiniAlphaSlotSpec(
                slot_no=slot_no,
                sampled_from_item_no=blueprint["item_no"],
                domain=blueprint["domain"],
                format=ItemFormat(blueprint["format"]),
                score=blueprint["score"],
                difficulty=DifficultyBand(blueprint["difficulty"]),
                objective=blueprint["objective"],
                skill_tags=blueprint.get("skill_tags", []),
            )
        )
    return slots


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


def _write_candidate_bundle(
    *,
    root: Path,
    candidate_id: str,
    source_item_no: int,
    stem: str,
    domain: str = "algebra",
    item_format: ItemFormat = ItemFormat.MULTIPLE_CHOICE,
    score: int = 3,
    difficulty: DifficultyBand = DifficultyBand.STANDARD,
    objective: str | None = None,
    skill_tags: list[str] | None = None,
    choices: list[str] | None = None,
    solution_steps: list[str] | None = None,
    atom_signatures: list[str] | None = None,
    distractor_signatures: list[str] | None = None,
) -> CandidatePoolCandidateBundle:
    candidate_dir = root / "candidates" / candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)

    blueprint = ItemBlueprint(
        item_no=source_item_no,
        domain=domain,
        format=item_format,
        score=score,
        difficulty=difficulty,
        objective=objective or f"{candidate_id} objective",
        skill_tags=skill_tags or [f"{candidate_id}_skill", f"topic_{source_item_no}"],
        choice_count=5 if item_format == ItemFormat.MULTIPLE_CHOICE else None,
        answer_type="choice_index"
        if item_format == ItemFormat.MULTIPLE_CHOICE
        else "natural_number",
    )
    item_choices = (
        choices
        or [
            "조건 가",
            "조건 나",
            "조건 다",
            "조건 라",
            "조건 마",
        ]
        if item_format == ItemFormat.MULTIPLE_CHOICE
        else []
    )
    draft = DraftItem(
        blueprint=blueprint,
        stem=stem,
        choices=item_choices,
        rubric="generated exam fixture",
        answer_constraints=[blueprint.answer_type],
    )
    final_answer = "4" if item_format == ItemFormat.MULTIPLE_CHOICE else str(200 + source_item_no)
    solved = SolvedItem(
        draft=draft,
        final_answer=final_answer,
        correct_choice_index=4 if item_format == ItemFormat.MULTIPLE_CHOICE else None,
        correct_choice_value=item_choices[3] if item_format == ItemFormat.MULTIPLE_CHOICE else None,
        solution_steps=solution_steps
        or [
            f"{candidate_id} step 1 compares the transformed condition.",
            f"{candidate_id} step 2 isolates the decisive algebraic relation.",
            f"{candidate_id} step 3 confirms why choice 4 is the only valid answer.",
        ],
        solution_summary=f"{candidate_id} summary",
    )
    report = _fixture_report(item_no=source_item_no, difficulty=DifficultyBand.STANDARD)
    validated_item = ValidatedItem(
        solved=solved,
        validation=report.final_report,
        approval_status=ApprovalStatus.APPROVED,
    )

    validated_item_path = candidate_dir / "validated_item.json"
    validator_report_path = candidate_dir / "validator_report.json"
    candidate_bundle_path = candidate_dir / "candidate_bundle.json"
    validated_item_path.write_text(validated_item.model_dump_json(indent=2), encoding="utf-8")
    validator_report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    bundle = CandidatePoolCandidateBundle(
        candidate_id=candidate_id,
        run_id=f"fixture-run-{candidate_id}",
        gauntlet_status="succeeded",
        source_atom_id=f"atom-{candidate_id}",
        family_id="fixture-family",
        source_item_id=f"fixture-source-{source_item_no}",
        source_item_no=source_item_no,
        domain=blueprint.domain,
        difficulty=blueprint.difficulty.value,
        format=blueprint.format,
        score=blueprint.score,
        objective=blueprint.objective,
        skill_tags=blueprint.skill_tags,
        approval_status=validated_item.approval_status,
        validation_status=report.final_report.status,
        atom_signatures=atom_signatures or [f"atom_{candidate_id}"],
        distractor_signatures=distractor_signatures or [f"distractor_{candidate_id}_{index}" for index in range(1, 4)],
        candidate_dir=str(candidate_dir),
        validated_item_path=str(validated_item_path),
        validator_report_path=str(validator_report_path),
    )
    candidate_bundle_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return bundle


def test_generated_exam_uses_bundle_pool_and_avoids_overlap(tmp_path: Path) -> None:
    candidate_pool_dir = tmp_path / "candidate_pool_scan_only"
    slots = _sample_slots(sample_size=15)
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
        "비슷해 보이는 두 식을 분리해서 {objective}의 핵심 차이를 판정한다.",
        "누적된 조건을 다시 배열해 {objective}가 유지되는 순간만 찾는다.",
        "보조선을 머릿속에 그려 본 뒤 {objective}를 만족하는 관계를 고른다.",
        "역조건을 먼저 살핀 다음 {objective}가 가능한지 되짚어 본다.",
        "끝까지 남는 불변량을 추적해 {objective}를 완성하는 문제다.",
    ]
    step_descriptors = [
        "조건을 모아 핵심 관계를 세운다.",
        "불필요한 경우를 제거한다.",
        "필요한 성질만 남겨 비교한다.",
        "결론으로 이어지는 기준을 고른다.",
        "최종 판단을 확정한다.",
    ]
    surface_markers = [
        "적색",
        "청색",
        "녹색",
        "황색",
        "백색",
        "흑색",
        "은색",
        "금색",
        "자홍",
        "청록",
        "남색",
        "주황",
        "연두",
        "분홍",
        "회색",
    ]
    context_descriptors = [
        "표의 마지막 열에 남은 조건만 추려 검토한다.",
        "좌표평면에서 만나는 점의 의미를 다시 해석한다.",
        "수열의 앞뒤 항을 연결하는 규칙을 따로 정리한다.",
        "함수값의 증감이 바뀌는 경계만 모아 비교한다.",
        "로그식의 정의역을 먼저 분리해서 읽는다.",
        "도함수의 부호표를 짧게 다시 세운다.",
        "확률 표본공간을 둘로 나누어 계산한다.",
        "조건부 분포에서 빠진 칸을 역으로 채운다.",
        "절댓값 식의 경우를 끝까지 분리한다.",
        "삼각함수 그래프의 주기 이동을 먼저 확인한다.",
        "정적분 넓이 해석과 대수 계산을 분리해 본다.",
        "접선의 기울기 조건을 점의 위치와 함께 읽는다.",
        "부등식의 경계값을 대입해 반례를 걷어낸다.",
        "복합함수의 바깥 함수와 안쪽 함수를 따로 추적한다.",
        "서로 다른 두 조건이 동시에 성립하는 구간만 남긴다.",
    ]

    base_bundles: list[CandidatePoolCandidateBundle] = []
    for slot in slots:
        stem = stem_descriptors[(slot.slot_no - 1) % len(stem_descriptors)].format(
            objective=slot.objective
        )
        stem = (
            f"{stem} 기준 문항 {slot.sampled_from_item_no}의 수치 조건을 함께 비교하고 "
            f"{surface_markers[slot.slot_no - 1]} 표식을 통해 경우를 구분한다. "
            f"{context_descriptors[slot.slot_no - 1]}"
        )
        solution_steps = [
            f"{step_descriptors[(slot.slot_no + 0) % len(step_descriptors)]} {slot.objective}를 위한 핵심 조건을 정리한다.",
            f"{step_descriptors[(slot.slot_no + 1) % len(step_descriptors)]} {slot.domain} 맥락에서 필요한 비교만 남긴다.",
            f"{step_descriptors[(slot.slot_no + 2) % len(step_descriptors)]} {slot.objective}에 맞는 답을 확정한다.",
        ]
        base_bundles.append(
            _write_candidate_bundle(
                root=candidate_pool_dir,
                candidate_id=f"base-{slot.slot_no:02d}",
                source_item_no=slot.sampled_from_item_no,
                stem=stem,
                domain=slot.domain,
                item_format=slot.format,
                score=slot.score,
                difficulty=slot.difficulty,
                objective=slot.objective,
                skill_tags=[f"{slot.domain}_{slot.slot_no}", f"{slot.difficulty.value}_{slot.slot_no}"],
                solution_steps=solution_steps,
            )
        )

    duplicate_source = base_bundles[3]
    duplicate_payload = json.loads(
        Path(duplicate_source.validated_item_path).read_text(encoding="utf-8")
    )
    _write_candidate_bundle(
        root=candidate_pool_dir,
        candidate_id="dup-overlap",
        source_item_no=300,
        stem=duplicate_payload["solved"]["draft"]["stem"],
        domain=duplicate_payload["solved"]["draft"]["blueprint"]["domain"],
        item_format=ItemFormat(duplicate_payload["solved"]["draft"]["blueprint"]["format"]),
        score=duplicate_payload["solved"]["draft"]["blueprint"]["score"],
        difficulty=DifficultyBand(duplicate_payload["solved"]["draft"]["blueprint"]["difficulty"]),
        objective=duplicate_payload["solved"]["draft"]["blueprint"]["objective"],
        skill_tags=duplicate_payload["solved"]["draft"]["blueprint"]["skill_tags"],
        choices=duplicate_payload["solved"]["draft"]["choices"],
        solution_steps=duplicate_payload["solved"]["solution_steps"],
        atom_signatures=duplicate_source.atom_signatures,
        distractor_signatures=duplicate_source.distractor_signatures,
    )

    collision_payload = json.loads(
        Path(base_bundles[4].validated_item_path).read_text(encoding="utf-8")
    )
    _write_candidate_bundle(
        root=candidate_pool_dir,
        candidate_id="hard-collision",
        source_item_no=301,
        stem=collision_payload["solved"]["draft"]["stem"],
        domain=collision_payload["solved"]["draft"]["blueprint"]["domain"],
        item_format=ItemFormat(collision_payload["solved"]["draft"]["blueprint"]["format"]),
        score=collision_payload["solved"]["draft"]["blueprint"]["score"],
        difficulty=DifficultyBand(collision_payload["solved"]["draft"]["blueprint"]["difficulty"]),
        objective=collision_payload["solved"]["draft"]["blueprint"]["objective"],
        skill_tags=collision_payload["solved"]["draft"]["blueprint"]["skill_tags"],
        choices=collision_payload["solved"]["draft"]["choices"],
        solution_steps=collision_payload["solved"]["solution_steps"],
        atom_signatures=["atom_hard_collision"],
        distractor_signatures=["distractor_hard_collision_1", "distractor_hard_collision_2"],
    )

    _write_candidate_bundle(
        root=candidate_pool_dir,
        candidate_id="metadata-leak",
        source_item_no=302,
        stem="artifact_id 문자열이 학생 노출 텍스트에 섞인 잘못된 후보다.",
        domain="algebra",
        item_format=ItemFormat.MULTIPLE_CHOICE,
        score=3,
        difficulty=DifficultyBand.BASIC,
        atom_signatures=["atom_metadata_leak"],
        distractor_signatures=["distractor_metadata_leak_1", "distractor_metadata_leak_2"],
    )
    _write_candidate_bundle(
        root=candidate_pool_dir,
        candidate_id="reserve-standard-clean",
        source_item_no=401,
        stem="추가 표준 후보는 대수 영역에서 서로 다른 관계식을 배열해 조건 충돌을 제거하는 문항이다.",
        domain="algebra",
        item_format=ItemFormat.MULTIPLE_CHOICE,
        score=3,
        difficulty=DifficultyBand.STANDARD,
        objective="추가 표준 대수 조건 판정",
        skill_tags=["algebra_reserve_standard", "standard_reserve"],
        solution_steps=[
            "추가 표준 후보의 핵심 조건을 정리한다.",
            "대수 관계식에서 불필요한 경우를 제거한다.",
            "남은 조건으로 정답 선택지를 확정한다.",
        ],
        atom_signatures=["atom_reserve_standard_clean"],
        distractor_signatures=["distractor_reserve_standard_1", "distractor_reserve_standard_2"],
    )
    _write_candidate_bundle(
        root=candidate_pool_dir,
        candidate_id="reserve-basic-clean",
        source_item_no=402,
        stem="추가 기본 후보는 정의역과 부호 조건을 차례로 확인해 올바른 경우만 남기는 문항이다.",
        domain="algebra",
        item_format=ItemFormat.MULTIPLE_CHOICE,
        score=3,
        difficulty=DifficultyBand.BASIC,
        objective="추가 기본 대수 조건 판정",
        skill_tags=["algebra_reserve_basic", "basic_reserve"],
        solution_steps=[
            "정의역 조건을 먼저 정리한다.",
            "부호 조건과 일치하지 않는 경우를 제거한다.",
            "남은 조건으로 최종 답을 확정한다.",
        ],
        atom_signatures=["atom_reserve_basic_clean"],
        distractor_signatures=["distractor_reserve_basic_1", "distractor_reserve_basic_2"],
    )

    pipeline = GeneratedExamPipeline(template_dir=TEMPLATE_DIR)
    result = pipeline.run(
        run_id="generated-exam-selection-test",
        candidate_pool_dir=candidate_pool_dir,
        output_dir=tmp_path / "generated_exam",
        slot_count=15,
        title="Generated Exam Selection Fixture",
        compile_pdf=False,
    )

    selected_ids = [selection.candidate_id for selection in result.selected]
    assert len(selected_ids) == 15
    assert "dup-overlap" not in selected_ids
    assert "hard-collision" not in selected_ids
    assert "metadata-leak" not in selected_ids
    assert result.metrics.metadata_leaks == 0
    assert result.metrics.hard_similarity_collisions == 0

    candidate_manifest = json.loads(Path(result.candidate_manifest_path).read_text(encoding="utf-8"))
    discard_report = json.loads(Path(result.discard_report_path).read_text(encoding="utf-8"))
    exam_tex = Path(result.exam_tex_path).read_text(encoding="utf-8")

    assert result.candidate_pool_manifest_path is None
    assert len(candidate_manifest["slots"]) == 15
    assert len(candidate_manifest["candidates"]) == 20
    assert discard_report["selected_count"] == 15
    assert discard_report["reserve_count"] == 4
    assert discard_report["auto_discarded_count"] == 1

    assert "Generated Exam Selection Fixture" in exam_tex
    assert "artifact_id" not in exam_tex
    assert "source_atom_id" not in exam_tex
