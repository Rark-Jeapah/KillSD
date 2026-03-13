"""Base provider interfaces for prompt execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.schemas import PromptPacket, StrictModel


class ProviderError(Exception):
    """Raised when a provider invocation fails."""


class MalformedProviderResponseError(ProviderError):
    """Raised when a provider returns output that fails strict normalization."""


class ProviderUsage(StrictModel):
    """Normalized provider usage metadata for benchmarking."""

    prompt_chars: int = 0
    completion_chars: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int | None = None


class ProviderResponse(StrictModel):
    """Normalized provider response payload."""

    provider_name: str
    prompt_packet_id: str
    stage_name: str
    output: dict[str, Any]
    raw_text: str
    prompt_hash: str | None = None
    seed: int | None = None
    usage: ProviderUsage | None = None


class BaseProvider(ABC):
    """Abstract provider interface used by API mode."""

    provider_name: str

    @abstractmethod
    def invoke(self, packet: PromptPacket) -> ProviderResponse:
        """Execute a prompt packet and return structured JSON output."""
