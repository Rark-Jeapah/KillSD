"""API-mode executor for remote prompt stages."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from src.core.schemas import PromptPacket
from src.providers.base import BaseProvider, ProviderResponse

T = TypeVar("T", bound=BaseModel)


class ApiModeExecutor:
    """Execute prompt packets through a provider adapter."""

    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def execute(self, packet: PromptPacket, model_type: type[T]) -> tuple[T, ProviderResponse]:
        """Invoke the provider and validate the returned JSON against the model."""
        response = self.provider.invoke(packet)
        model = model_type.model_validate(response.output)
        return model, response
