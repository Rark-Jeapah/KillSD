"""Deterministic mock provider for orchestrator tests and local smoke runs."""

from __future__ import annotations

import json
from random import Random
from time import perf_counter

from src.core.schemas import (
    CritiqueReport,
    DraftItem,
    ExamBlueprint,
    SolvedItem,
    ItemBlueprint,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.providers.base import BaseProvider, ProviderError, ProviderResponse, ProviderUsage


class MockProvider(BaseProvider):
    """Deterministic mock provider returning schema-valid JSON."""

    provider_name = "mock_provider"

    def invoke(self, packet) -> ProviderResponse:
        started = perf_counter()
        output = self._build_output(packet)
        raw_text = json.dumps(output, ensure_ascii=False)
        prompt_chars = len("".join(packet.instructions)) + len(
            json.dumps(packet.context, ensure_ascii=False, sort_keys=True)
        )
        completion_chars = len(raw_text)
        return ProviderResponse(
            provider_name=self.provider_name,
            prompt_packet_id=packet.packet_id,
            stage_name=packet.stage_name,
            output=output,
            raw_text=raw_text,
            prompt_hash=packet.prompt_hash,
            seed=packet.seed,
            usage=ProviderUsage(
                prompt_chars=prompt_chars,
                completion_chars=completion_chars,
                estimated_cost_usd=0.0,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    def _build_output(self, packet) -> dict:
        rng = Random((packet.seed or 0) + (packet.item_no or 0))

        if packet.stage_name == "exam_blueprint":
            blueprint = CSATMath2028Plugin().build_default_blueprint()
            return blueprint.model_dump(mode="json")

        if packet.stage_name == "item_blueprint":
            exam_blueprint = ExamBlueprint.model_validate(packet.context["exam_blueprint"])
            for item_blueprint in exam_blueprint.item_blueprints:
                if item_blueprint.item_no == packet.item_no:
                    return item_blueprint.model_dump(mode="json")
            raise ProviderError(f"item_no={packet.item_no} not found in exam blueprint")

        if packet.stage_name == "draft_item":
            item_blueprint = ItemBlueprint.model_validate(packet.context["item_blueprint"])
            if item_blueprint.format.value == "multiple_choice":
                base = (item_blueprint.item_no * 3) + rng.randint(1, 2)
                choices = [str(base + offset) for offset in range(5)]
            else:
                choices = []
            draft = DraftItem(
                blueprint=item_blueprint,
                stem=f"{item_blueprint.objective}을 평가하는 모의 문항 {item_blueprint.item_no}번이다.",
                choices=choices,
                rubric=f"{item_blueprint.objective}에 맞는 핵심 풀이를 구성한다.",
                answer_constraints=[item_blueprint.answer_type],
            )
            return draft.model_dump(mode="json")

        if packet.stage_name == "solve":
            draft = DraftItem.model_validate(packet.context["draft_item"])
            if draft.blueprint.format.value == "multiple_choice":
                correct_choice_index = ((draft.blueprint.item_no - 1) % len(draft.choices)) + 1
                correct_choice_value = draft.choices[correct_choice_index - 1]
                final_answer = str(correct_choice_index)
            else:
                correct_choice_index = None
                correct_choice_value = None
                final_answer = str(100 + draft.blueprint.item_no)
            solved = SolvedItem(
                draft=draft,
                final_answer=final_answer,
                correct_choice_index=correct_choice_index,
                correct_choice_value=correct_choice_value,
                solution_steps=[
                    f"{draft.blueprint.objective}에 필요한 조건을 먼저 정리한다.",
                    "핵심 계산 또는 추론을 수행한다.",
                    "정답 형식에 맞게 결과를 확정한다.",
                ],
                solution_summary=f"{draft.blueprint.objective}에 맞는 풀이가 완결되었다.",
            )
            return solved.model_dump(mode="json")

        if packet.stage_name == "critique":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            critique = CritiqueReport(
                item_no=solved.draft.blueprint.item_no,
                summary="구조적 결함이 없어 다음 단계로 진행 가능하다.",
                findings=[],
                requires_revision=False,
            )
            return critique.model_dump(mode="json")

        if packet.stage_name == "revise":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            revised = solved.model_copy(
                update={"solution_summary": f"{solved.solution_summary} [revised]"}
            )
            return revised.model_dump(mode="json")

        raise ProviderError(f"Unsupported mock stage: {packet.stage_name}")
