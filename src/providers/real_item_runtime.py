"""Shared runtime config helpers for the real-item provider path."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from pydantic import model_validator

from src.core.schemas import ExamMode, StrictModel
from src.providers.base import BaseProvider
from src.providers.factory import build_provider
from src.security.secrets import SecretsResolver


REAL_ITEM_PROVIDER_CHOICES = ("deterministic", "manual", "openai")


class RealItemProviderConfig(StrictModel):
    """User-facing provider config for the real-item pipeline."""

    provider: str = "deterministic"
    model: str | None = None
    timeout_seconds: float | None = None
    max_retries: int | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    base_url: str | None = None
    organization: str | None = None
    project: str | None = None
    stage_max_attempts: int = 3

    @model_validator(mode="after")
    def validate_config(self) -> "RealItemProviderConfig":
        normalized = self.provider.lower()
        if normalized not in REAL_ITEM_PROVIDER_CHOICES:
            raise ValueError(
                f"provider must be one of {', '.join(REAL_ITEM_PROVIDER_CHOICES)}"
            )
        object.__setattr__(self, "provider", normalized)
        if self.stage_max_attempts < 1:
            raise ValueError("stage_max_attempts must be >= 1")
        if normalized != "openai":
            openai_values = (
                self.model,
                self.timeout_seconds,
                self.max_retries,
                self.temperature,
                self.max_output_tokens,
                self.base_url,
                self.organization,
                self.project,
            )
            if any(value is not None for value in openai_values):
                raise ValueError("OpenAI settings require --provider openai")
        return self

    @property
    def mode(self) -> ExamMode:
        return ExamMode.MANUAL if self.provider == "manual" else ExamMode.API

    def build_provider(
        self,
        *,
        env: Mapping[str, str] | None = None,
        secrets_resolver: SecretsResolver | None = None,
    ) -> BaseProvider | None:
        if self.provider == "manual":
            return None
        provider_kwargs: dict[str, Any] = {}
        if self.provider == "openai":
            provider_kwargs = {
                "model": self.model,
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "temperature": self.temperature,
                "max_output_tokens": self.max_output_tokens,
                "base_url": self.base_url,
                "organization": self.organization,
                "project": self.project,
            }
        return build_provider(
            self.provider,
            env=env,
            secrets_resolver=secrets_resolver,
            **{key: value for key, value in provider_kwargs.items() if value is not None},
        )

    def public_settings(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "mode": self.mode.value,
            "stage_max_attempts": self.stage_max_attempts,
        }
        if self.provider == "openai":
            for key in (
                "model",
                "timeout_seconds",
                "max_retries",
                "temperature",
                "max_output_tokens",
                "base_url",
                "organization",
                "project",
            ):
                value = getattr(self, key)
                if value is not None:
                    payload[key] = value
        return payload


def add_real_item_provider_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_legacy_mode: bool = False,
    provider_required: bool = False,
) -> None:
    """Attach shared provider arguments to a script parser."""

    parser.add_argument(
        "--provider",
        choices=REAL_ITEM_PROVIDER_CHOICES,
        default=None if not provider_required else "deterministic",
        help="Provider flow for remote real-item stages: deterministic, manual, or openai.",
    )
    if include_legacy_mode:
        parser.add_argument(
            "--mode",
            choices=[mode.value for mode in ExamMode],
            default=None,
            help="Deprecated compatibility flag. Prefer --provider.",
        )
    parser.add_argument("--openai-model", default=None, help="Override the OpenAI model id.")
    parser.add_argument(
        "--openai-timeout-seconds",
        type=float,
        default=None,
        help="Override the per-request timeout for the OpenAI provider.",
    )
    parser.add_argument(
        "--openai-max-retries",
        type=int,
        default=None,
        help="Retry transient OpenAI transport failures this many times.",
    )
    parser.add_argument(
        "--openai-temperature",
        type=float,
        default=None,
        help="Optional temperature for the OpenAI provider.",
    )
    parser.add_argument(
        "--openai-max-output-tokens",
        type=int,
        default=None,
        help="Optional max_output_tokens for the OpenAI provider.",
    )
    parser.add_argument(
        "--openai-base-url",
        default=None,
        help="Optional custom base URL for the OpenAI provider.",
    )
    parser.add_argument(
        "--openai-organization",
        default=None,
        help="Optional OpenAI organization id.",
    )
    parser.add_argument(
        "--openai-project",
        default=None,
        help="Optional OpenAI project id.",
    )
    parser.add_argument(
        "--stage-max-attempts",
        type=int,
        default=3,
        help="Reject malformed provider output and retry a stage up to this many attempts.",
    )


def provider_config_from_args(
    args: argparse.Namespace,
    *,
    default_provider: str = "deterministic",
) -> RealItemProviderConfig:
    """Normalize argparse values into one real-item provider config."""

    provider = getattr(args, "provider", None)
    legacy_mode = getattr(args, "mode", None)
    if provider is None:
        if legacy_mode == ExamMode.MANUAL.value:
            provider = "manual"
        elif legacy_mode in {ExamMode.API.value, None}:
            provider = default_provider
        else:  # pragma: no cover - argparse constrains the values
            raise ValueError(f"Unsupported mode: {legacy_mode}")
    elif legacy_mode is not None:
        expected_mode = ExamMode.MANUAL.value if provider == "manual" else ExamMode.API.value
        if legacy_mode != expected_mode:
            raise ValueError(
                f"--mode {legacy_mode} conflicts with --provider {provider}; "
                f"use mode={expected_mode} or omit --mode"
            )

    return RealItemProviderConfig(
        provider=provider,
        model=getattr(args, "openai_model", None),
        timeout_seconds=getattr(args, "openai_timeout_seconds", None),
        max_retries=getattr(args, "openai_max_retries", None),
        temperature=getattr(args, "openai_temperature", None),
        max_output_tokens=getattr(args, "openai_max_output_tokens", None),
        base_url=getattr(args, "openai_base_url", None),
        organization=getattr(args, "openai_organization", None),
        project=getattr(args, "openai_project", None),
        stage_max_attempts=getattr(args, "stage_max_attempts", 3),
    )
