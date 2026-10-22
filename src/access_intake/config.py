"""Runtime settings, read from environment variables only."""

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "snapshot.schema.json"

DEFAULT_MODELS = {"gemini": "gemini-2.5-pro", "anthropic": "claude-opus-5-5"}


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    max_output_tokens: int
    temperature: float
    workers: int
    vertex_project: str | None = None
    vertex_location: str = "global"
    anthropic_use_vertex: bool = False
    schema: dict = field(default_factory=dict, compare=False)


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def from_env() -> Settings:
    provider = os.environ.get("INTAKE_PROVIDER", "gemini")
    if provider not in DEFAULT_MODELS:
        raise SystemExit(f"INTAKE_PROVIDER must be one of {sorted(DEFAULT_MODELS)}, got {provider!r}")
    return Settings(
        provider=provider,
        model=os.environ.get("INTAKE_MODEL", DEFAULT_MODELS[provider]),
        max_output_tokens=int(os.environ.get("INTAKE_MAX_OUTPUT_TOKENS", "8192")),
        temperature=float(os.environ.get("INTAKE_TEMPERATURE", "0")),
        workers=int(os.environ.get("INTAKE_WORKERS", "4")),
        vertex_project=os.environ.get("GOOGLE_VERTEX_PROJECT"),
        vertex_location=os.environ.get("GOOGLE_VERTEX_LOCATION", "global"),
        anthropic_use_vertex=os.environ.get("INTAKE_ANTHROPIC_VERTEX", "0") == "1",
        schema=load_schema(),
    )


def config_fingerprint(settings: Settings, prompt: str) -> str:
    """Identifies everything besides the source bytes that shapes a result.

    A stored result is reused only when both the source hash and this fingerprint match.
    """
    material = json.dumps(
        {
            "provider": settings.provider,
            "model": settings.model,
            "temperature": settings.temperature,
            "prompt": prompt,
            "schema": settings.schema,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
