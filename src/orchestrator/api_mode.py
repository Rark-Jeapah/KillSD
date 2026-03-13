"""API-mode executor for remote prompt stages."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError

from src.core.schemas import PromptPacket
from src.providers.base import BaseProvider, MalformedProviderResponseError, ProviderResponse

T = TypeVar("T", bound=BaseModel)


class ApiModeExecutor:
    """Execute prompt packets through a provider adapter."""

    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    def invoke(self, packet: PromptPacket) -> ProviderResponse:
        """Invoke the provider and return the normalized provider envelope."""
        return self.provider.invoke(packet)

    def normalize(self, response: ProviderResponse, model_type: type[T]) -> T:
        """Validate a provider response payload against the stage model."""
        try:
            return model_type.model_validate(response.output)
        except ValidationError as exc:
            raise MalformedProviderResponseError(
                f"Provider response failed schema validation for {model_type.__name__}"
            ) from exc

    def execute(self, packet: PromptPacket, model_type: type[T]) -> tuple[T, ProviderResponse]:
        """Invoke the provider and validate the returned JSON against the model."""
        response = self.invoke(packet)
        model = self.normalize(response, model_type)
        return model, response
