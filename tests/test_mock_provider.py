"""Tests for deterministic, non-placeholder mock provider content."""

from __future__ import annotations

import json

from src.core.schemas import ExamMode, ItemFormat, PipelineStage, PromptPacket
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.providers.mock_provider import MockProvider


SPEC = CSATMath2028Plugin().load_exam_spec()
MCQ_BLUEPRINT = next(
    blueprint for blueprint in SPEC.default_item_blueprints if blueprint.format == ItemFormat.MULTIPLE_CHOICE
)
SHORT_ANSWER_BLUEPRINT = next(
    blueprint for blueprint in SPEC.default_item_blueprints if blueprint.format == ItemFormat.SHORT_ANSWER
)
STAGE_PIPELINES = {
    "draft_item": PipelineStage.GENERATION,
    "solve": PipelineStage.SOLVING,
    "critique": PipelineStage.VALIDATION,
    "revise": PipelineStage.REVISION,
}
BANNED_TOKENS = ("placeholder", "모의 문항", "평가하는 문항")


def _packet(*, stage_name: str, item_no: int, seed: int, context: dict[str, object]) -> PromptPacket:
    return PromptPacket(
        mode=ExamMode.API,
        stage=STAGE_PIPELINES[stage_name],
        stage_name=stage_name,
        spec_id=SPEC.spec_id,
        run_id="mock-provider-test",
        item_no=item_no,
        instructions=["fixture"],
        context=context,
        expected_output_model=stage_name,
        seed=seed,
    )


def _without_ids(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if not key.endswith("_id") and key not in {"draft_id", "solved_id", "critique_id"}
    }


def test_mock_provider_outputs_are_non_placeholder_and_deterministic() -> None:
    provider = MockProvider()

    for blueprint in (MCQ_BLUEPRINT, SHORT_ANSWER_BLUEPRINT):
        draft_packet = _packet(
            stage_name="draft_item",
            item_no=blueprint.item_no,
            seed=17,
            context={"item_blueprint": blueprint.model_dump(mode="json")},
        )
        draft_output = provider.invoke(draft_packet).output
        repeated_draft_output = provider.invoke(draft_packet).output
        alternate_seed_output = provider.invoke(
            _packet(
                stage_name="draft_item",
                item_no=blueprint.item_no,
                seed=18,
                context={"item_blueprint": blueprint.model_dump(mode="json")},
            )
        ).output

        assert _without_ids(draft_output) == _without_ids(repeated_draft_output)
        assert (
            draft_output["stem"] != alternate_seed_output["stem"]
            or draft_output["choices"] != alternate_seed_output["choices"]
        )

        solve_output = provider.invoke(
            _packet(
                stage_name="solve",
                item_no=blueprint.item_no,
                seed=17,
                context={"draft_item": draft_output},
            )
        ).output
        critique_output = provider.invoke(
            _packet(
                stage_name="critique",
                item_no=blueprint.item_no,
                seed=17,
                context={"solved_item": solve_output},
            )
        ).output
        revise_output = provider.invoke(
            _packet(
                stage_name="revise",
                item_no=blueprint.item_no,
                seed=17,
                context={"solved_item": solve_output, "critique_report": critique_output},
            )
        ).output

        for output in (draft_output, solve_output, critique_output, revise_output):
            serialized = json.dumps(output, ensure_ascii=False).lower()
            for token in BANNED_TOKENS:
                assert token not in serialized

        assert critique_output["requires_revision"] is True

        if blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            correct_index = solve_output["correct_choice_index"]
            assert correct_index is not None
            assert solve_output["correct_choice_value"] == draft_output["choices"][correct_index - 1]
            assert revise_output["correct_choice_value"] == revise_output["draft"]["choices"][correct_index - 1]
            assert revise_output["final_answer"] == str(correct_index)
            assert revise_output["draft"]["stem"].endswith("가장 알맞은 것을 고르시오.")
        else:
            assert draft_output["choices"] == []
            assert solve_output["correct_choice_index"] is None
            assert solve_output["correct_choice_value"] is None
            assert solve_output["final_answer"].isdigit()
            assert revise_output["draft"]["stem"].endswith("답을 자연수로 쓰시오.")
