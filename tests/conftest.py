"""Shared fixtures. Every test uses FakeProvider: no network, no model calls."""

import json
import shutil
from pathlib import Path

import pytest

from access_intake.config import Settings, load_schema
from access_intake.pipeline import Intake
from access_intake.providers import ProviderError, ProviderResponse

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "accuracy" / "expected.json").read_text())["documents"]
FIELDS = ("request_id", "request_date", "kind", "requester", "team", "system", "environment",
          "permission", "start_date", "end_date", "manager")


def message_of(path: Path) -> str:
    return json.loads(path.read_text())["message"]


def expected_extraction(document_id: str, message: str) -> dict:
    """A schema-valid extraction carrying the hand-built expected values."""
    exp = EXPECTED[document_id]
    ext = {f: exp[f] for f in FIELDS}
    ext["business_purpose"] = None if exp["business_purpose"] is None else "stated purpose"
    ext["supporting_quotes"] = [message[:40]]
    ext["issues"] = [f"{tag}: from expected results" for tag in exp["required_issue_tags"]]
    return ext


class FakeProvider:
    """Returns a scripted response per document id; records every call."""

    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []

    def request_config(self):
        return {"provider": "fake", "sdk": "none", "model": "fake-model",
                "generation_config": {"response_json_schema": "<schema>"}}

    def extract(self, user_text):
        document_id = user_text.split("\n", 1)[0].removeprefix("Document id: ")
        self.calls.append(document_id)
        action = self.script.get(document_id, "expected")
        if isinstance(action, Exception):
            raise action
        if isinstance(action, ProviderResponse):
            return action
        message = user_text.split("<message>\n", 1)[1].rsplit("\n</message>", 1)[0]
        ext = action if isinstance(action, dict) else expected_extraction(document_id, message)
        return ProviderResponse("complete", json.dumps(ext), "STOP", {}, {"input_tokens": 1, "output_tokens": 1})


@pytest.fixture
def workspace(tmp_path):
    inputs = tmp_path / "requests"
    shutil.copytree(ROOT / "materials" / "requests", inputs)
    return tmp_path


@pytest.fixture
def make_intake(workspace):
    def make(provider):
        settings = Settings(provider="gemini", model="fake-model", max_output_tokens=100,
                            temperature=0, workers=2, schema=load_schema())
        return Intake(settings, provider, workspace / "requests", workspace / "out",
                      workspace / "state", "uv run access-intake intake")
    return make


__all__ = ["ProviderError", "ProviderResponse", "FakeProvider", "expected_extraction", "message_of", "EXPECTED"]
