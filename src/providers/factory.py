"""Shared provider construction helpers."""

from __future__ import annotations

from collections.abc import Mapping

from src.providers.base import BaseProvider, ProviderError
from src.providers.mock_provider import MockProvider
from src.providers.openai_provider import OpenAIProvider
from src.security.secrets import SecretsResolver


def build_provider(
    provider_name: str,
    *,
    env: Mapping[str, str] | None = None,
    secrets_resolver: SecretsResolver | None = None,
) -> BaseProvider:
    """Return a configured provider adapter by name."""
    normalized = provider_name.lower()
    if normalized in {"mock", "mock_provider"}:
        return MockProvider()
    if normalized in {"openai", "openai_provider"}:
        return OpenAIProvider(env=env, secrets_resolver=secrets_resolver)
    raise ProviderError(f"Unsupported provider: {provider_name}")
