"""MCQ answer-key schema and render tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.schemas import (
    ApprovalStatus,
    DraftItem,
    ItemBlueprint,
    ItemFormat,
    RenderBundle,
    SolvedItem,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    ValidatedItem,
    DifficultyBand,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.render.latex_renderer import LaTeXRenderer
from src.validators.format_validator import validate_format
from src.validators.report import DifficultyEstimate, ValidatorSectionResult, ValidatorSuiteReport


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "src" / "render" / "templates"


def _mcq_blueprint(item_no: int = 1) -> ItemBlueprint:
    return ItemBlueprint(
        item_no=item_no,
        domain="algebra",
        format=ItemFormat.MULTIPLE_CHOICE,
        score=3,
        difficulty=DifficultyBand.STANDARD,
        objective="객관식 정답 형식 검증",
        skill_tags=["algebra"],
        choice_count=5,
        answer_type="choice_index",
    )


def _mcq_draft(item_no: int = 1) -> DraftItem:
    blueprint = _mcq_blueprint(item_no=item_no)
    return DraftItem(
        blueprint=blueprint,
        stem="정답 형식을 검증하는 객관식 문항이다.",
        choices=["11", "22", "33", "44", "55"],
        rubric="보기와 정답 인덱스를 함께 검증한다.",
        answer_constraints=["choice_index"],
    )


def _render_bundle_for_answer_key() -> tuple[RenderBundle, list[ValidatorSuiteReport]]:
    blueprint = CSATMath2028Plugin().build_default_blueprint()
    validated_items: list[ValidatedItem] = []
    reports: list[ValidatorSuiteReport] = []

    for item_blueprint in blueprint.item_blueprints:
        if item_blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            choices = [f"VALUE_{item_blueprint.item_no}_{index}" for index in range(1, 6)]
            correct_choice_index = 4
            final_answer = "4"
            correct_choice_value = choices[3]
        else:
            choices = []
            correct_choice_index = None
            correct_choice_value = None
            final_answer = str(200 + item_blueprint.item_no)

        solved = SolvedItem(
            draft=DraftItem(
                blueprint=item_blueprint,
                stem=f"{item_blueprint.item_no}번 정답표 렌더링 검증용 문항이다.",
                choices=choices,
                rubric="렌더링 테스트",
                answer_constraints=[item_blueprint.answer_type],
            ),
            final_answer=final_answer,
            correct_choice_index=correct_choice_index,
            correct_choice_value=correct_choice_value,
            solution_steps=["풀이를 정리한다."],
            solution_summary="정답표 검증용 풀이",
        )
        final_report = ValidationReport(
            item_no=item_blueprint.item_no,
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
        validated_items.append(
            ValidatedItem(
                solved=solved,
                validation=final_report,
                approval_status=ApprovalStatus.APPROVED,
            )
        )
        reports.append(
            ValidatorSuiteReport(
                spec_id=blueprint.spec_id,
                item_no=item_blueprint.item_no,
                sections=[ValidatorSectionResult(validator_name="fixture", findings=[], metrics={})],
                difficulty_estimate=DifficultyEstimate(
                    expected_step_count=1,
                    concept_count=1,
                    branching_factor=1.0,
                    solver_disagreement_score=0.0,
                    predicted_band=item_blueprint.difficulty.value,
                ),
                final_report=final_report,
            )
        )

    return (
        RenderBundle(
            spec_id=blueprint.spec_id,
            blueprint_id=blueprint.blueprint_id,
            items=validated_items,
            student_metadata={
                "title": "MCQ Answer Key Fixture",
                "duration_minutes": "100",
                "total_score": "100",
            },
            internal_metadata={},
            output_targets=["answer_key_pdf"],
            answer_key={
                item.solved.draft.blueprint.item_no: item.solved.final_answer for item in validated_items
            },
        ),
        reports,
    )


def test_mcq_solved_item_requires_choice_index_and_value() -> None:
    draft = _mcq_draft()

    with pytest.raises(ValueError, match="correct_choice_index"):
        SolvedItem(
            draft=draft,
            final_answer="3",
            solution_steps=["풀이를 정리한다."],
            solution_summary="인덱스 없는 정답",
        )


def test_format_validator_flags_non_integer_mcq_answer_key() -> None:
    spec = CSATMath2028Plugin().load_exam_spec()
    draft = _mcq_draft()
    solved_item = SolvedItem.model_construct(
        draft=draft,
        final_answer="44",
        correct_choice_index=4,
        correct_choice_value="44",
        solution_steps=["풀이를 정리한다."],
        solution_summary="레거시 값 기반 정답",
    )

    result = validate_format(solved_item=solved_item, spec=spec)

    failure = next(
        finding for finding in result.findings if finding.reason_code == "format.mcq_answer_key_not_integer"
    )
    assert failure.passed is False
    assert failure.message == "MCQ answer key must be integer 1..5"


def test_answer_key_renders_choice_index_not_choice_value(tmp_path: Path) -> None:
    bundle, _ = _render_bundle_for_answer_key()
    renderer = LaTeXRenderer(template_dir=TEMPLATE_DIR)

    document = renderer.render_answer_key(
        bundle=bundle,
        output_dir=tmp_path,
        compile_pdf=False,
    )
    source = Path(document.tex_path).read_text(encoding="utf-8")

    assert "1 & 4 & 2" in source
    assert "VALUE_1_4" not in source
