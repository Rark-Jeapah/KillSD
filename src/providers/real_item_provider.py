"""Deterministic real-item provider wired to the family registry."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from src.core.schemas import CritiqueReport, DraftItem, ItemBlueprint, PromptPacket, SolvedItem
from src.distill.atom_extractor import InsightAtom
from src.orchestrator.real_item_families import (
    RealItemFamilyRegistry,
    build_real_item_family_registry,
)
from src.providers.base import BaseProvider, ProviderError, ProviderResponse, ProviderUsage


def _atom_from_context(context: dict[str, Any]) -> InsightAtom:
    if "atom" in context:
        return InsightAtom.model_validate(context["atom"])
    if "draft_item" in context:
        draft = DraftItem.model_validate(context["draft_item"])
        return InsightAtom(
            atom_id=f"inferred-{draft.blueprint.item_no}",
            label=draft.blueprint.objective,
            topic=draft.blueprint.objective,
            prerequisites=draft.blueprint.skill_tags,
            allowed_answer_forms=draft.answer_constraints,
        )
    if "solved_item" in context:
        solved = SolvedItem.model_validate(context["solved_item"])
        return InsightAtom(
            atom_id=f"inferred-{solved.draft.blueprint.item_no}",
            label=solved.draft.blueprint.objective,
            topic=solved.draft.blueprint.objective,
            prerequisites=solved.draft.blueprint.skill_tags,
            allowed_answer_forms=solved.draft.answer_constraints,
        )
    if "item_blueprint" in context:
        blueprint = ItemBlueprint.model_validate(context["item_blueprint"])
        return InsightAtom(
            atom_id=f"inferred-{blueprint.item_no}",
            label=blueprint.objective,
            topic=blueprint.objective,
            prerequisites=blueprint.skill_tags,
            allowed_answer_forms=[blueprint.answer_type],
        )
    raise ProviderError("Unable to infer atom context for real-item family execution")


class RealItemProvider(BaseProvider):
    """Deterministic provider that emits one registered real-item family with measured usage."""

    provider_name = "deterministic"

    def __init__(
        self,
        *,
        family_registry: RealItemFamilyRegistry | None = None,
        prompt_usd_per_1k_chars: float = 0.00035,
        completion_usd_per_1k_chars: float = 0.00085,
    ) -> None:
        self.family_registry = family_registry or build_real_item_family_registry()
        self.prompt_usd_per_1k_chars = prompt_usd_per_1k_chars
        self.completion_usd_per_1k_chars = completion_usd_per_1k_chars

    def invoke(self, packet: PromptPacket) -> ProviderResponse:
        """Return a schema-valid remote stage output and normalized usage."""
        started = perf_counter()
        output = self._render_stage_output(packet)
        raw_text = json.dumps(output, ensure_ascii=False, indent=2)
        prompt_chars = len("".join(packet.instructions)) + len(
            json.dumps(packet.context, ensure_ascii=False, sort_keys=True)
        )
        completion_chars = len(raw_text)
        latency_ms = max(1, int((perf_counter() - started) * 1000))
        estimated_cost_usd = round(
            (prompt_chars / 1000.0) * self.prompt_usd_per_1k_chars
            + (completion_chars / 1000.0) * self.completion_usd_per_1k_chars,
            6,
        )
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
                estimated_cost_usd=estimated_cost_usd,
                latency_ms=latency_ms,
            ),
        )

    def _render_stage_output(self, packet: PromptPacket) -> dict[str, Any]:
        family = self.family_registry.resolve_for_context(packet.context)
        atom = _atom_from_context(packet.context)
        if packet.stage_name == "draft_item":
            blueprint = ItemBlueprint.model_validate(packet.context["item_blueprint"])
            return family.draft_strategy(blueprint, atom).model_dump(mode="json")

        if packet.stage_name == "solve":
            draft = DraftItem.model_validate(packet.context["draft_item"])
            return family.solve_strategy(draft, atom).model_dump(mode="json")

        if packet.stage_name == "critique":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            return family.critique_strategy(solved, atom).model_dump(mode="json")

        if packet.stage_name == "revise":
            solved = SolvedItem.model_validate(packet.context["solved_item"])
            critique = CritiqueReport.model_validate(packet.context["critique_report"])
            return family.revise_strategy(solved, critique, atom).model_dump(mode="json")

        raise ProviderError(f"Unsupported real-item stage: {packet.stage_name}")
