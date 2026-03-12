"""Generation cost and latency logging for benchmark runs."""

from __future__ import annotations

from pydantic import Field

from src.core.schemas import StrictModel
from src.core.storage import ArtifactStore
from src.providers.base import ProviderResponse


class StageCostBreakdown(StrictModel):
    """Aggregated cost counters for one stage."""

    stage_name: str
    prompt_count: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0


class CostSummary(StrictModel):
    """Aggregated provider usage for one run or benchmark attempt."""

    prompt_count: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    by_stage: list[StageCostBreakdown] = Field(default_factory=list)


class CostLogger:
    """Collect provider usage from stored artifacts or in-memory responses."""

    def summarize_responses(self, responses: list[ProviderResponse]) -> CostSummary:
        """Aggregate usage metrics from normalized provider responses."""
        stage_totals: dict[str, StageCostBreakdown] = {}
        for response in responses:
            usage = response.usage
            if usage is None:
                continue
            stage_total = stage_totals.setdefault(
                response.stage_name,
                StageCostBreakdown(stage_name=response.stage_name),
            )
            stage_total.prompt_count += 1
            stage_total.prompt_chars += usage.prompt_chars
            stage_total.completion_chars += usage.completion_chars
            stage_total.estimated_cost_usd += usage.estimated_cost_usd
            stage_total.latency_ms += usage.latency_ms or 0

        breakdown = sorted(stage_totals.values(), key=lambda entry: entry.stage_name)
        return CostSummary(
            prompt_count=sum(entry.prompt_count for entry in breakdown),
            prompt_chars=sum(entry.prompt_chars for entry in breakdown),
            completion_chars=sum(entry.completion_chars for entry in breakdown),
            estimated_cost_usd=round(sum(entry.estimated_cost_usd for entry in breakdown), 6),
            latency_ms=sum(entry.latency_ms for entry in breakdown),
            by_stage=breakdown,
        )

    def load_and_summarize(self, *, run_id: str, artifact_store: ArtifactStore) -> CostSummary:
        """Load provider response artifacts for a run and aggregate them."""
        responses: list[ProviderResponse] = []
        for record in artifact_store.list_artifacts(run_id=run_id, limit=1000):
            if record.artifact_type != "ProviderResponse":
                continue
            responses.append(artifact_store.load_model(record.artifact_id, ProviderResponse))
        return self.summarize_responses(responses)
