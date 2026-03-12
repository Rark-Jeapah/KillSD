"""Schema smoke tests for the CSAT mathematics MVP."""

from __future__ import annotations

from src.core.schemas import (
    ApprovalStatus,
    DraftItem,
    ExamMode,
    ItemBlueprint,
    ItemFormat,
    ManualExchangePacket,
    PipelineStage,
    PromptPacket,
    SolvedItem,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    ValidatedItem,
    DifficultyBand,
)


def _sample_blueprint() -> ItemBlueprint:
    return ItemBlueprint(
        item_no=1,
        domain="algebra",
        format=ItemFormat.MULTIPLE_CHOICE,
        score=2,
        difficulty=DifficultyBand.BASIC,
        objective="기본 검증용 문항",
        skill_tags=["polynomial"],
        choice_count=5,
    )


def test_prompt_packet_and_manual_exchange_roundtrip() -> None:
    packet = PromptPacket(
        mode=ExamMode.MANUAL,
        stage=PipelineStage.GENERATION,
        spec_id="csat_math_2028",
        run_id="run-001",
        item_no=1,
        instructions=["문항 초안을 생성하라."],
        expected_output_model="DraftItem",
    )

    exchange = ManualExchangePacket(prompt_packet=packet)
    payload = exchange.model_dump(mode="json")
    restored = ManualExchangePacket.model_validate(payload)

    assert restored.prompt_packet.mode == ExamMode.MANUAL
    assert restored.status.value == "pending"


def test_validated_item_alignment() -> None:
    blueprint = _sample_blueprint()
    draft = DraftItem(
        blueprint=blueprint,
        stem="다항식의 계수를 구하시오.",
        choices=["1", "2", "3", "4", "5"],
        rubric="조건식을 이용해 계수를 계산한다.",
    )
    solved = SolvedItem(
        draft=draft,
        final_answer="3",
        correct_choice_index=3,
        correct_choice_value="3",
        solution_steps=["식을 정리한다.", "계수를 비교한다."],
        solution_summary="계수 비교로 답을 구한다.",
    )
    report = ValidationReport(
        item_no=1,
        status=ValidationStatus.PASS,
        findings=[
            ValidationFinding(
                check_name="format_check",
                passed=True,
                severity=ValidationSeverity.INFO,
                message="형식 검증 통과",
            )
        ],
        summary="모든 자동 검증 통과",
    )
    validated = ValidatedItem(
        solved=solved,
        validation=report,
        approval_status=ApprovalStatus.APPROVED,
    )

    assert validated.validation.status == ValidationStatus.PASS
    assert validated.approval_status == ApprovalStatus.APPROVED
