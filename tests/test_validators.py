"""Tests for the validator layer."""

from __future__ import annotations

from pathlib import Path

from src.core.schemas import (
    CritiqueReport,
    DifficultyBand,
    FailureLevel,
    ItemBlueprint,
    ItemFormat,
    SolvedItem,
    DraftItem,
    ValidationStatus,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.validators.answer_validator import validate_answer
from src.validators.curriculum_validator import validate_curriculum
from src.validators.difficulty_estimator import estimate_difficulty, validate_difficulty_proxy
from src.validators.format_validator import validate_format
from src.validators.render_validator import validate_render
from src.validators.report import (
    ValidationContext,
    load_distilled_resources,
    load_similarity_thresholds,
    run_validator_suite,
)
from src.validators.similarity_validator import validate_similarity


REPO_ROOT = Path(__file__).resolve().parents[1]


def _solved_item(
    *,
    item_no: int = 1,
    domain: str = "algebra",
    item_format: ItemFormat = ItemFormat.MULTIPLE_CHOICE,
    score: int = 3,
    difficulty: DifficultyBand = DifficultyBand.STANDARD,
    objective: str = "로그식 결합과 정의역 제한",
    skill_tags: list[str] | None = None,
    stem: str = "로그 방정식과 정의역을 함께 판단하는 문항이다.",
    choices: list[str] | None = None,
    final_answer: str = "4",
    answer_constraints: list[str] | None = None,
    solution_steps: list[str] | None = None,
) -> SolvedItem:
    blueprint = ItemBlueprint(
        item_no=item_no,
        domain=domain,
        format=item_format,
        score=score,
        difficulty=difficulty,
        objective=objective,
        skill_tags=skill_tags or ["logarithm", "equation"],
        choice_count=5 if item_format == ItemFormat.MULTIPLE_CHOICE else None,
        answer_type="natural_number" if item_format == ItemFormat.SHORT_ANSWER else "choice_index",
    )
    draft = DraftItem(
        blueprint=blueprint,
        stem=stem,
        choices=choices or (["1", "2", "3", "4", "5"] if item_format == ItemFormat.MULTIPLE_CHOICE else []),
        rubric="풀이 구조를 검증한다.",
        answer_constraints=answer_constraints or [blueprint.answer_type],
    )
    return SolvedItem(
        draft=draft,
        final_answer=final_answer,
        correct_choice_index=int(final_answer) if item_format == ItemFormat.MULTIPLE_CHOICE else None,
        correct_choice_value=(
            draft.choices[int(final_answer) - 1] if item_format == ItemFormat.MULTIPLE_CHOICE else None
        ),
        solution_steps=solution_steps
        or ["정의역을 확인한다.", "식을 정리한다.", "정답을 선택한다."],
        solution_summary="기본 풀이가 완성되었다.",
    )


def test_format_validator_catches_non_natural_short_answer() -> None:
    spec = CSATMath2028Plugin().load_exam_spec()
    solved_item = _solved_item(
        item_no=22,
        domain="probability_statistics",
        item_format=ItemFormat.SHORT_ANSWER,
        final_answer="2/3",
        objective="조건부확률 계산",
        skill_tags=["conditional_probability"],
        stem="조건부확률 단답형 문항이다.",
        choices=[],
    )
    result = validate_format(solved_item=solved_item, spec=spec)

    failure = next(finding for finding in result.findings if finding.reason_code == "format.short_answer_not_natural")
    assert failure.passed is False
    assert failure.failure_level == FailureLevel.HARD


def test_validator_suite_rejects_placeholder_wording_in_student_text() -> None:
    spec = CSATMath2028Plugin().load_exam_spec()
    resources = load_distilled_resources(REPO_ROOT, spec.spec_id)
    thresholds = load_similarity_thresholds(REPO_ROOT / "config" / "similarity_thresholds.json")
    critique_report = CritiqueReport(
        item_no=1,
        summary="placeholder probe",
        findings=[],
        requires_revision=False,
    )
    solved_item = _solved_item(
        stem="로그식을 평가하는 모의 문항 1번이다.",
        choices=["1", "2", "3", "4", "5"],
        final_answer="4",
    )
    context = ValidationContext(
        spec=spec,
        solved_item=solved_item,
        critique_report=critique_report,
        resources=resources,
        similarity_thresholds=thresholds,
    )

    suite_report, validated_item = run_validator_suite(context=context)

    failure = next(
        finding for finding in suite_report.final_report.findings if finding.reason_code == "format.placeholder_wording"
    )
    assert failure.passed is False
    assert failure.failure_level == FailureLevel.HARD
    assert suite_report.final_report.status == ValidationStatus.FAIL
    assert validated_item.approval_status.value == "rejected"


def test_curriculum_validator_detects_forbidden_topic() -> None:
    spec = CSATMath2028Plugin().load_exam_spec()
    solved_item = _solved_item(
        stem="벡터와 기하를 결합한 문항이다.",
        objective="vector geometry",
        skill_tags=["vector"],
    )
    resources = load_distilled_resources(REPO_ROOT, spec.spec_id)
    result = validate_curriculum(
        solved_item=solved_item,
        spec=spec,
        allowed_topics=resources.allowed_topics,
        forbidden_topics=resources.forbidden_topics,
    )

    failure = next(
        finding for finding in result.findings if finding.reason_code == "curriculum.forbidden_topic_detected"
    )
    assert failure.passed is False


def test_answer_validator_symbolic_and_cross_check() -> None:
    solved_item = _solved_item(
        item_format=ItemFormat.SHORT_ANSWER,
        final_answer="x+x",
        objective="동치식 정리",
        skill_tags=["expression"],
        choices=[],
    )
    result = validate_answer(
        solved_item=solved_item,
        expected_answer="2*x",
        cross_check_answer="x-x",
    )

    reference_check = next(f for f in result.findings if f.reason_code == "answer.reference_mismatch")
    cross_check = next(f for f in result.findings if f.reason_code == "answer.cross_check_disagreement")
    assert reference_check.passed is True
    assert cross_check.passed is False


def test_similarity_validator_flags_near_duplicate_fixture() -> None:
    resources = load_distilled_resources(REPO_ROOT, "csat_math_2028")
    thresholds = load_similarity_thresholds(REPO_ROOT / "config" / "similarity_thresholds.json")
    solved_item = _solved_item(
        item_no=2,
        domain="calculus_1",
        objective="도함수 계산과 꼭짓점 활용",
        skill_tags=["derivative", "critical point", "monotonicity"],
        stem="함수 f(x)=x^3-3x^2+ax가 구간 전체에서 감소하지 않도록 하는 실수 a의 범위를 추론하는 문항이다.",
        choices=["a≤0", "0≤a≤3", "a≥3", "a≥1", "a≤3"],
        final_answer="3",
        solution_steps=[
            "f'(x)=3x^2-6x+a를 구한다.",
            "꼭짓점 x=1에서 도함수의 최솟값을 확인한다.",
            "a≥3을 얻고 정답을 확정한다.",
        ],
    )
    result = validate_similarity(
        solved_item=solved_item,
        existing_item_cards=resources.item_cards,
        existing_fingerprints=resources.fingerprints,
        existing_solution_graphs=resources.solution_graphs,
        thresholds=thresholds,
    )

    assert any(not finding.passed for finding in result.findings)


def test_render_validator_detects_broken_math_and_missing_assets() -> None:
    solved_item = _solved_item(
        stem="식 $x+1 를 만족하는 값을 구하라.",
        solution_steps=["중괄호 { 가 닫히지 않는다."],
    )
    result = validate_render(
        solved_item=solved_item,
        asset_root=REPO_ROOT / "data" / "distilled" / "csat_math_2028" / "assets",
        asset_refs=["missing-diagram.pdf"],
    )

    failed_codes = {finding.reason_code for finding in result.findings if not finding.passed}
    assert "render.unbalanced_inline_math" in failed_codes
    assert "render.missing_diagram_asset" in failed_codes


def test_render_validator_skips_compile_when_xelatex_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("CSAT_XELATEX_PATH", raising=False)
    monkeypatch.setattr("src.validators.render_validator.shutil.which", lambda _: None)

    result = validate_render(
        solved_item=_solved_item(stem="한글 문장과 수식 x+1을 함께 포함한 문항이다."),
        asset_root=None,
        asset_refs=[],
    )

    compile_finding = next(
        finding for finding in result.findings if finding.check_name == "latex_compile_dry_run"
    )
    failed_codes = {finding.reason_code for finding in result.findings if not finding.passed}

    assert compile_finding.passed is True
    assert compile_finding.reason_code == "render.latex_compile_ok"
    assert "compile dry-run skipped" in compile_finding.message
    assert "render.latex_compile_failed" not in failed_codes


def test_difficulty_estimator_and_suite_report() -> None:
    spec = CSATMath2028Plugin().load_exam_spec()
    resources = load_distilled_resources(REPO_ROOT, spec.spec_id)
    thresholds = load_similarity_thresholds(REPO_ROOT / "config" / "similarity_thresholds.json")
    critique_report = CritiqueReport(
        item_no=1,
        summary="구조상 수정 필요 없음",
        findings=[],
        requires_revision=False,
    )
    solved_item = _solved_item(
        item_no=1,
        domain="algebra",
        item_format=ItemFormat.MULTIPLE_CHOICE,
        final_answer="4",
        solution_steps=["정의역 확인", "로그 결합", "방정식 풀이", "선택지 대응"],
    )
    estimate = estimate_difficulty(
        solved_item=solved_item,
        critique_report=critique_report,
        cross_check_answer="4",
    )
    difficulty_result = validate_difficulty_proxy(
        solved_item=solved_item,
        difficulty_estimate=estimate,
    )
    context = ValidationContext(
        spec=spec,
        solved_item=solved_item,
        critique_report=critique_report,
        resources=resources,
        similarity_thresholds=thresholds,
        cross_check_answer="4",
        expected_answer="4",
    )
    suite_report, validated_item = run_validator_suite(context=context)

    assert estimate.expected_step_count == 4
    assert "predicted_band" in difficulty_result.metrics
    assert suite_report.final_report.status == ValidationStatus.PASS
    assert validated_item.validation.regenerate_recommendation.value == "keep"
