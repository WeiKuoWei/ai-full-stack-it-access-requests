"""Provider adapters against stub clients: the completion mapping and error wrapping."""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from access_intake.config import Settings, load_schema
from access_intake.providers import AnthropicProvider, ProviderError


def settings():
    return Settings(provider="anthropic", model="claude-opus-5-5", max_output_tokens=100,
                    temperature=0, workers=1, schema=load_schema())


def provider_with(create):
    p = AnthropicProvider.__new__(AnthropicProvider)
    p.settings = settings()
    p.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return p


def reply(stop_reason, text="{}"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


@pytest.mark.parametrize("stop_reason, completion", [
    ("end_turn", "complete"), ("refusal", "refusal"), ("max_tokens", "interrupted"), ("pause_turn", "interrupted"),
])
def test_stop_reason_mapping(stop_reason, completion):
    assert provider_with(lambda **kw: reply(stop_reason)).extract("x").completion == completion


def test_schema_goes_only_in_output_config():
    seen = {}
    provider_with(lambda **kw: seen.update(kw) or reply("end_turn")).extract("x")
    assert seen["output_config"]["format"] == {"type": "json_schema", "schema": load_schema()}
    for keyword in ("additionalProperties", '"type"', '"properties"', "json_schema"):
        assert keyword not in seen["system"]


def test_api_error_becomes_provider_error():
    def boom(**kw):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    with pytest.raises(ProviderError):
        provider_with(boom).extract("x")
