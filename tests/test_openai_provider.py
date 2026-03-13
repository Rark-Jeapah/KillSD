"""Unit tests for the OpenAI provider adapter."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.core.schemas import ExamMode, ItemBlueprint, PipelineStage, PromptPacket
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.providers.base import ProviderError
from src.providers.factory import build_provider
from src.providers.openai_provider import OpenAIProvider


SPEC = CSATMath2028Plugin().load_exam_spec()
ITEM_BLUEPRINT = SPEC.default_item_blueprints[0]


class FakeResponsesClient:
    """Minimal fake for the OpenAI Responses API surface."""

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    """Minimal fake OpenAI client."""

    def __init__(self, outcomes: list[object]) -> None:
        self.responses = FakeResponsesClient(outcomes)


def _response(payload_text: str, *, input_tokens: int = 0, output_tokens: int = 0) -> object:
    return SimpleNamespace(
        output_text=payload_text,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _packet() -> PromptPacket:
    return PromptPacket(
        mode=ExamMode.API,
        stage=PipelineStage.DESIGN,
        stage_name="item_blueprint",
        spec_id=SPEC.spec_id,
        run_id="openai-provider-test",
        blueprint_id="bp-test",
        item_no=ITEM_BLUEPRINT.item_no,
        instructions=["Generate one item blueprint that matches the contract exactly."],
        context={"spec_id": SPEC.spec_id, "exam_year": 2028},
        expected_output_model="ItemBlueprint",
        response_json_schema=ItemBlueprint.model_json_schema(),
        seed=17,
    )


def test_openai_provider_returns_structured_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = ITEM_BLUEPRINT.model_dump(mode="json")
    raw_text = json.dumps(payload, ensure_ascii=False)
    client = FakeClient([_response(raw_text, input_tokens=120, output_tokens=48)])

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CSAT_OPENAI_MODEL", "gpt-test-model")

    provider = OpenAIProvider(
        client=client,
        input_cost_per_1m_tokens=2.0,
        output_cost_per_1m_tokens=8.0,
    )

    response = provider.invoke(_packet())

    assert response.provider_name == "openai"
    assert response.output == payload
    assert response.raw_text == raw_text
    assert response.seed == 17
    assert response.usage is not None
    assert response.usage.prompt_chars > 0
    assert response.usage.completion_chars == len(raw_text)
    assert response.usage.estimated_cost_usd == 0.000624

    request = client.responses.calls[0]
    assert request["model"] == "gpt-test-model"
    assert request["text"] == {
        "format": {
            "type": "json_schema",
            "name": "ItemBlueprint",
            "schema": ItemBlueprint.model_json_schema(),
            "strict": True,
        }
    }

    input_text = request["input"][0]["content"][0]["text"]  # type: ignore[index]
    input_payload = json.loads(input_text)  # type: ignore[arg-type]
    assert input_payload["context"] == {"exam_year": 2028, "spec_id": SPEC.spec_id}


def test_openai_provider_raises_on_malformed_json() -> None:
    provider = OpenAIProvider(
        env={"OPENAI_API_KEY": "sk-test"},
        client=FakeClient([_response("{not-json")]),
    )

    with pytest.raises(ProviderError, match="valid JSON"):
        provider.invoke(_packet())


def test_openai_provider_raises_on_schema_mismatch() -> None:
    provider = OpenAIProvider(
        env={"OPENAI_API_KEY": "sk-test"},
        client=FakeClient(
            [
                _response(
                    json.dumps(
                        {
                            "item_no": ITEM_BLUEPRINT.item_no,
                            "domain": ITEM_BLUEPRINT.domain,
                        }
                    )
                )
            ]
        ),
    )

    with pytest.raises(ProviderError, match="schema validation"):
        provider.invoke(_packet())


def test_openai_provider_missing_secret_is_reported() -> None:
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        build_provider("openai", env={})


def test_openai_provider_retries_timeout_when_configured() -> None:
    payload = ITEM_BLUEPRINT.model_dump(mode="json")
    client = FakeClient(
        [
            TimeoutError("first attempt timed out"),
            _response(json.dumps(payload, ensure_ascii=False)),
        ]
    )
    provider = OpenAIProvider(
        env={"OPENAI_API_KEY": "sk-test"},
        client=client,
        max_retries=1,
    )

    response = provider.invoke(_packet())

    assert response.output == payload
    assert len(client.responses.calls) == 2
