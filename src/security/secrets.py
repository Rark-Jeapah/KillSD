"""Small secret-resolution layer for provider credentials."""

from __future__ import annotations

import os
from typing import Mapping

from src.core.schemas import StrictModel


class SecretResolutionError(Exception):
    """Raised when a required secret is missing."""


class ProviderCredential(StrictModel):
    """Resolved provider credential metadata."""

    provider_name: str
    env_var: str | None = None
    configured: bool = False
    redacted_value: str | None = None


class SecretsResolver:
    """Resolve provider credentials from environment variables."""

    DEFAULT_ENV_MAP = {
        "mock": None,
        "mock_provider": None,
        "openai": "OPENAI_API_KEY",
    }

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        provider_env_map: Mapping[str, str | None] | None = None,
    ) -> None:
        self.env = dict(env or os.environ)
        self.provider_env_map = {**self.DEFAULT_ENV_MAP, **(provider_env_map or {})}

    def resolve_provider_key(
        self,
        provider_name: str,
        *,
        required: bool = False,
        explicit_env_var: str | None = None,
    ) -> str | None:
        """Return the provider API key if configured."""
        env_var = explicit_env_var or self.provider_env_map.get(provider_name)
        if env_var is None:
            return None
        value = self.env.get(env_var)
        if required and not value:
            raise SecretResolutionError(f"Missing required secret: {env_var}")
        return value

    def describe_provider(
        self, provider_name: str, *, explicit_env_var: str | None = None
    ) -> ProviderCredential:
        """Return non-sensitive metadata about provider credential availability."""
        env_var = explicit_env_var or self.provider_env_map.get(provider_name)
        value = self.resolve_provider_key(
            provider_name,
            required=False,
            explicit_env_var=explicit_env_var,
        )
        return ProviderCredential(
            provider_name=provider_name,
            env_var=env_var,
            configured=bool(value),
            redacted_value=self._redact(value),
        )

    @staticmethod
    def _redact(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"
