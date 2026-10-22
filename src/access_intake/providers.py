"""Model-provider adapters.

Each adapter sends the schema through the provider's native structured-output setting and
returns a ProviderResponse whose `completion` is one of:
  complete     the model finished normally
  refusal      the provider or model declined (safety block, refusal stop reason)
  interrupted  the output was cut off (token limit, missing finish reason)
Transport and API failures raise ProviderError.
"""

from dataclasses import dataclass, field

from .config import Settings
from .prompt import SYSTEM_PROMPT


class ProviderError(Exception):
    pass


@dataclass
class ProviderResponse:
    completion: str
    text: str | None
    finish_reason: str
    request_config: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


GEMINI_REFUSAL = {
    "SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION",
    "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "LANGUAGE",
}


class GeminiVertexProvider:
    def __init__(self, settings: Settings):
        from google import genai

        if not settings.vertex_project:
            raise SystemExit("GOOGLE_VERTEX_PROJECT is required for INTAKE_PROVIDER=gemini")
        self.settings = settings
        self.client = genai.Client(
            vertexai=True, project=settings.vertex_project, location=settings.vertex_location
        )

    def request_config(self) -> dict:
        s = self.settings
        return {
            "provider": "google-vertex-ai",
            "sdk": "google-genai",
            "model": s.model,
            "project": s.vertex_project,
            "location": s.vertex_location,
            "generation_config": {
                "system_instruction": "<prompt.SYSTEM_PROMPT>",
                "response_mime_type": "application/json",
                "response_json_schema": "<snapshot.schema.json, unmodified>",
                "temperature": s.temperature,
                "max_output_tokens": s.max_output_tokens,
            },
        }

    def extract(self, user_text: str) -> ProviderResponse:
        from google.genai import errors, types

        s = self.settings
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=s.schema,
            temperature=s.temperature,
            max_output_tokens=s.max_output_tokens,
        )
        try:
            r = self.client.models.generate_content(model=s.model, contents=user_text, config=config)
        except errors.APIError as e:
            raise ProviderError(f"Vertex AI API error {e.code}: {e.message}") from e
        except Exception as e:  # network failures, timeouts
            raise ProviderError(f"{type(e).__name__}: {e}") from e

        usage = {}
        if r.usage_metadata:
            usage = {
                "input_tokens": r.usage_metadata.prompt_token_count,
                "output_tokens": r.usage_metadata.candidates_token_count,
            }
        block = r.prompt_feedback.block_reason if r.prompt_feedback else None
        if block:
            return ProviderResponse("refusal", None, f"PROMPT_BLOCKED:{block.name}", self.request_config(), usage)
        if not r.candidates:
            return ProviderResponse("interrupted", None, "NO_CANDIDATES", self.request_config(), usage)
        reason = r.candidates[0].finish_reason
        name = reason.name if reason else "FINISH_REASON_UNSPECIFIED"
        if name == "STOP":
            completion = "complete"
        elif name in GEMINI_REFUSAL:
            completion = "refusal"
        else:
            completion = "interrupted"
        return ProviderResponse(completion, r.text, name, self.request_config(), usage)


class AnthropicProvider:
    """Claude via the Anthropic API (ANTHROPIC_API_KEY) or via Vertex AI (INTAKE_ANTHROPIC_VERTEX=1)."""

    def __init__(self, settings: Settings):
        import anthropic

        self.settings = settings
        if settings.anthropic_use_vertex:
            self.client = anthropic.AnthropicVertex(
                project_id=settings.vertex_project, region=settings.vertex_location
            )
        else:
            self.client = anthropic.Anthropic()

    def request_config(self) -> dict:
        s = self.settings
        return {
            "provider": "anthropic-vertex" if s.anthropic_use_vertex else "anthropic",
            "sdk": "anthropic",
            "model": s.model,
            "max_tokens": s.max_output_tokens,
            "system": "<prompt.SYSTEM_PROMPT>",
            "output_config": {"format": {"type": "json_schema", "schema": "<snapshot.schema.json, unmodified>"}},
        }

    def extract(self, user_text: str) -> ProviderResponse:
        import anthropic

        s = self.settings
        try:
            r = self.client.messages.create(
                model=s.model,
                max_tokens=s.max_output_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_text}],
                output_config={"format": {"type": "json_schema", "schema": s.schema}},
            )
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Anthropic connection error: {e}") from e

        usage = {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
        text = next((b.text for b in r.content if b.type == "text"), None)
        completion = {"end_turn": "complete", "refusal": "refusal"}.get(r.stop_reason, "interrupted")
        return ProviderResponse(completion, text, r.stop_reason or "none", self.request_config(), usage)


def build(settings: Settings):
    return {"gemini": GeminiVertexProvider, "anthropic": AnthropicProvider}[settings.provider](settings)
