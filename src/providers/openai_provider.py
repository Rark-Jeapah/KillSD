"""OpenAI-backed provider adapter for prompt packet execution."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from src.core import schemas as core_schemas
from src.core.schemas import PromptPacket
from src.orchestrator.stages import get_stage_definition
from src.providers.base import BaseProvider, ProviderError, ProviderResponse, ProviderUsage
from src.security.secrets import SecretResolutionError, SecretsResolver

try:
    import httpx
    from openai import APIConnectionError, APITimeoutError, OpenAI
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only in uninstalled envs
    httpx = None  # type: ignore[assignment]
    APIConnectionError = None  # type: ignore[assignment]
    APITimeoutError = None  # type: ignore[assignment]
    OpenAI = None  # type: ignore[assignment]
    _OPENAI_IMPORT_ERROR: Exception | None = exc
else:
    _OPENAI_IMPORT_ERROR = None


class OpenAIProvider(BaseProvider):
    """Provider adapter that executes prompt packets through the OpenAI Responses API."""

    provider_name = "openai"

    DEFAULT_MODEL = "gpt-4.1-mini"

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        input_cost_per_1m_tokens: float | None = None,
        output_cost_per_1m_tokens: float | None = None,
        env: Mapping[str, str] | None = None,
        secrets_resolver: SecretsResolver | None = None,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.env = dict(env or os.environ)
        self.secrets = secrets_resolver or SecretsResolver(env=self.env)
        self.model = model or self._env_string("CSAT_OPENAI_MODEL", "OPENAI_MODEL") or self.DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        if self.timeout_seconds is None:
            self.timeout_seconds = self._env_float("CSAT_OPENAI_TIMEOUT_SECONDS")

        self.max_retries = max_retries
        if self.max_retries is None:
            self.max_retries = self._env_int("CSAT_OPENAI_MAX_RETRIES", default=0)
        if self.max_retries < 0:
            raise ProviderError("CSAT_OPENAI_MAX_RETRIES must be >= 0")

        self.temperature = temperature
        if self.temperature is None:
            self.temperature = self._env_float("CSAT_OPENAI_TEMPERATURE")

        self.max_output_tokens = max_output_tokens
        if self.max_output_tokens is None:
            self.max_output_tokens = self._env_int("CSAT_OPENAI_MAX_OUTPUT_TOKENS")

        self.base_url = (
            base_url
            or self._env_string("CSAT_OPENAI_BASE_URL", "OPENAI_BASE_URL")
        )
        self.organization = (
            organization
            or self._env_string("CSAT_OPENAI_ORGANIZATION", "OPENAI_ORGANIZATION")
        )
        self.project = project or self._env_string("CSAT_OPENAI_PROJECT", "OPENAI_PROJECT")
        self.input_cost_per_1m_tokens = input_cost_per_1m_tokens
        if self.input_cost_per_1m_tokens is None:
            self.input_cost_per_1m_tokens = self._env_float(
                "CSAT_OPENAI_INPUT_COST_PER_1M_TOKENS",
                default=0.0,
            )
        self.output_cost_per_1m_tokens = output_cost_per_1m_tokens
        if self.output_cost_per_1m_tokens is None:
            self.output_cost_per_1m_tokens = self._env_float(
                "CSAT_OPENAI_OUTPUT_COST_PER_1M_TOKENS",
                default=0.0,
            )

        try:
            self.api_key = self.secrets.resolve_provider_key("openai", required=True)
        except SecretResolutionError as exc:
            raise ProviderError(str(exc)) from exc

        self._client = client
        self._client_factory = client_factory or OpenAI
        if self._client is None and self._client_factory is None:
            raise ProviderError("The openai package is not installed")
        if self._client is None and _OPENAI_IMPORT_ERROR is not None:
            raise ProviderError("The openai package is not installed") from _OPENAI_IMPORT_ERROR

    def invoke(self, packet: PromptPacket) -> ProviderResponse:
        started = perf_counter()
        instructions = self._compose_instructions(packet)
        input_payload = self._build_input_payload(packet)

        try:
            response = self._send_request(
                packet=packet,
                instructions=instructions,
                input_payload=input_payload,
            )
            raw_text = self._extract_output_text(response)
            output = self._normalize_output(packet, raw_text)
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise ProviderError(f"OpenAI provider failed: {exc}") from exc

        return ProviderResponse(
            provider_name=self.provider_name,
            prompt_packet_id=packet.packet_id,
            stage_name=packet.stage_name,
            output=output,
            raw_text=raw_text,
            prompt_hash=packet.prompt_hash,
            seed=packet.seed,
            usage=self._build_usage(
                response=response,
                raw_text=raw_text,
                instructions=instructions,
                input_payload=input_payload,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
        )

    @property
    def client(self) -> Any:
        """Return a lazily constructed OpenAI client."""
        if self._client is None:
            self._client = self._client_factory(
                api_key=self.api_key,
                base_url=self.base_url,
                organization=self.organization,
                project=self.project,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        return self._client

    def _send_request(
        self,
        *,
        packet: PromptPacket,
        instructions: str,
        input_payload: list[dict[str, Any]],
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                return self.client.responses.create(
                    **self._build_request_kwargs(
                        packet=packet,
                        instructions=instructions,
                        input_payload=input_payload,
                    )
                )
            except Exception as exc:
                if self._is_retryable(exc) and attempt <= self.max_retries:
                    last_error = exc
                    continue
                if self._is_timeout(exc):
                    raise ProviderError(
                        f"OpenAI request timed out after {attempt} attempt(s)"
                    ) from exc
                raise ProviderError(f"OpenAI request failed: {exc}") from exc

        raise ProviderError(f"OpenAI request failed: {last_error}")

    def _build_request_kwargs(
        self,
        *,
        packet: PromptPacket,
        instructions: str,
        input_payload: list[dict[str, Any]],
    ) -> dict[str, Any]:
        schema = self._response_schema(packet)
        metadata = {
            "packet_id": packet.packet_id,
            "stage_name": packet.stage_name,
            "run_id": packet.run_id,
            "expected_output_model": packet.expected_output_model,
        }
        if packet.item_no is not None:
            metadata["item_no"] = str(packet.item_no)
        if packet.prompt_hash is not None:
            metadata["prompt_hash"] = packet.prompt_hash

        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_payload,
            "metadata": metadata,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": packet.expected_output_model,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if self.timeout_seconds is not None:
            kwargs["timeout"] = self.timeout_seconds
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            kwargs["max_output_tokens"] = self.max_output_tokens
        return kwargs

    def _compose_instructions(self, packet: PromptPacket) -> str:
        instruction_parts = list(packet.instructions)
        instruction_parts.append(
            "Return exactly one JSON object that matches the required schema. "
            "Do not add markdown fences or explanatory prose."
        )
        if packet.seed is not None:
            instruction_parts.append(f"Recorded deterministic seed: {packet.seed}.")
        return "\n\n".join(part for part in instruction_parts if part)

    def _build_input_payload(self, packet: PromptPacket) -> list[dict[str, Any]]:
        prompt_context = {
            "packet_id": packet.packet_id,
            "spec_id": packet.spec_id,
            "run_id": packet.run_id,
            "stage_name": packet.stage_name,
            "pipeline_stage": packet.stage.value,
            "blueprint_id": packet.blueprint_id,
            "item_no": packet.item_no,
            "attempt": packet.attempt,
            "seed": packet.seed,
            "input_artifact_ids": packet.input_artifact_ids,
            "lineage_parent_ids": packet.lineage_parent_ids,
            "expected_output_model": packet.expected_output_model,
            "response_schema_version": packet.response_schema_version,
            "context": packet.context,
        }
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(prompt_context, ensure_ascii=False, sort_keys=True),
                    }
                ],
            }
        ]

    def _extract_output_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        fragments: list[str] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue
            for content_item in getattr(item, "content", []) or []:
                if getattr(content_item, "type", None) != "output_text":
                    continue
                text = getattr(content_item, "text", None)
                if isinstance(text, str) and text:
                    fragments.append(text)
        if fragments:
            return "".join(fragments)
        raise ProviderError("OpenAI response did not contain output_text")

    def _normalize_output(self, packet: PromptPacket, raw_text: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ProviderError("OpenAI response did not contain valid JSON") from exc

        if not isinstance(payload, dict):
            raise ProviderError("OpenAI response JSON must be an object")

        model_type = self._resolve_output_model(packet)
        if model_type is None:
            return payload

        try:
            normalized = model_type.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(
                f"OpenAI response failed schema validation for {packet.expected_output_model}"
            ) from exc
        return normalized.model_dump(mode="json")

    def _resolve_output_model(self, packet: PromptPacket) -> type[BaseModel] | None:
        try:
            stage_model = get_stage_definition(packet.stage_name).output_model
        except ValueError:
            stage_model = None

        if stage_model is not None and stage_model.__name__ == packet.expected_output_model:
            return stage_model

        candidate = getattr(core_schemas, packet.expected_output_model, None)
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
        return None

    def _response_schema(self, packet: PromptPacket) -> dict[str, Any]:
        if packet.response_json_schema:
            return packet.response_json_schema
        model_type = self._resolve_output_model(packet)
        if model_type is None:
            raise ProviderError(
                f"No response schema available for expected_output_model={packet.expected_output_model}"
            )
        return model_type.model_json_schema()

    def _build_usage(
        self,
        *,
        response: Any,
        raw_text: str,
        instructions: str,
        input_payload: list[dict[str, Any]],
        latency_ms: int,
    ) -> ProviderUsage:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        prompt_chars = len(instructions) + len(
            json.dumps(input_payload, ensure_ascii=False, sort_keys=True)
        )
        completion_chars = len(raw_text)
        estimated_cost_usd = round(
            (
                (input_tokens * self.input_cost_per_1m_tokens)
                + (output_tokens * self.output_cost_per_1m_tokens)
            )
            / 1_000_000,
            6,
        )
        return ProviderUsage(
            prompt_chars=prompt_chars,
            completion_chars=completion_chars,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
        )

    def _is_timeout(self, exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if APITimeoutError is not None and isinstance(exc, APITimeoutError):
            return True
        if httpx is not None and isinstance(exc, httpx.TimeoutException):
            return True
        return False

    def _is_retryable(self, exc: Exception) -> bool:
        if self._is_timeout(exc):
            return True
        if APIConnectionError is not None and isinstance(exc, APIConnectionError):
            return True
        return False

    def _env_string(self, *names: str) -> str | None:
        for name in names:
            value = self.env.get(name)
            if value:
                return value
        return None

    def _env_float(self, name: str, *, default: float | None = None) -> float | None:
        value = self.env.get(name)
        if value in {None, ""}:
            return default
        try:
            return float(value)
        except ValueError as exc:
            raise ProviderError(f"{name} must be a float") from exc

    def _env_int(self, name: str, *, default: int | None = None) -> int | None:
        value = self.env.get(name)
        if value in {None, ""}:
            return default
        try:
            return int(value)
        except ValueError as exc:
            raise ProviderError(f"{name} must be an integer") from exc
