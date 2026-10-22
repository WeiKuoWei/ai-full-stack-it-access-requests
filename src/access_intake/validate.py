"""Turns a provider response into a validated extraction, or raises ExtractionError.

Order: completion status -> JSON parse -> schema -> date format -> exact quotes.
Then deterministic checks add issues the model may have missed: identifier mismatch,
start after end, missing required facts, instruction-override wording.
"""

import datetime as dt
import json
import re
from pathlib import Path

import jsonschema

from .providers import ProviderResponse

DATE_FIELDS = ("request_date", "start_date", "end_date")
REQUIRED_FOR_ACCESS = (
    "request_id", "request_date", "requester", "team", "system", "environment",
    "permission", "business_purpose", "start_date", "end_date", "manager",
)
# Phrases that address the intake system or reviewers rather than describe a request.
OVERRIDE_PATTERN = re.compile(
    r"[^.\n]*\b(system override|ignore (all |any )?(previous|prior|above) instructions|"
    r"bypass (the )?approval|mark (this |the )?request as approved|highest-priority system instruction|"
    r"display the api key)\b[^.\n]*\.?",
    re.IGNORECASE,
)


class ExtractionError(Exception):
    """A failed attempt. `kind` is one of provider-error, refusal, interrupted, malformed, invalid."""

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind


def parse_and_validate(response: ProviderResponse, schema: dict, message: str) -> dict:
    if response.completion == "refusal":
        raise ExtractionError("refusal", f"provider declined the request (finish reason {response.finish_reason})")
    if response.completion != "complete":
        raise ExtractionError("interrupted", f"response did not complete (finish reason {response.finish_reason})")
    if not response.text:
        raise ExtractionError("malformed", "response completed with no text")
    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as e:
        raise ExtractionError("malformed", f"response is not valid JSON ({e.msg} at char {e.pos})") from e

    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=str)
    if errors:
        e = errors[0]
        where = "/".join(map(str, e.absolute_path)) or "(root)"
        raise ExtractionError("invalid", f"schema violation at {where}: {e.message}")

    for name in DATE_FIELDS:
        value = data[name]
        if value is not None:
            try:
                if dt.date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                raise ExtractionError("invalid", f"{name} {value!r} is not a YYYY-MM-DD date") from None

    for quote in data["supporting_quotes"]:
        if quote not in message:
            raise ExtractionError("invalid", f"supporting quote is not an exact substring of the message: {quote!r}")
    return data


def _has_issue(issues: list[str], tag: str, field: str | None = None) -> bool:
    return any(
        i.lower().startswith(tag) and (field is None or field in i.lower()) for i in issues
    )


def apply_checks(data: dict, document_id: str, message: str) -> dict:
    """Adds issues for facts code can verify on its own. Never changes an extracted value."""
    issues = data["issues"]
    stem = Path(document_id).stem

    if data["request_id"] is not None and data["request_id"] != stem and not _has_issue(issues, "id-mismatch"):
        issues.append(f"id-mismatch: message states {data['request_id']} but the document is {document_id} (added by validator)")

    if data["start_date"] and data["end_date"] and data["start_date"] > data["end_date"]:
        if not _has_issue(issues, "date-order"):
            issues.append(f"date-order: start_date {data['start_date']} is after end_date {data['end_date']} (added by validator)")

    if data["kind"] in ("new", "change"):
        for name in REQUIRED_FOR_ACCESS:
            if data[name] is None and not any(name in i.lower() for i in issues):
                issues.append(f"missing: {name} - not stated in the message (added by validator)")

    match = OVERRIDE_PATTERN.search(message)
    if match and not _has_issue(issues, "instruction-override"):
        issues.append("instruction-override: message contains text addressed to the intake system (added by validator)")
        quote = match.group(0).strip()
        if quote not in data["supporting_quotes"]:
            data["supporting_quotes"].append(quote)
    return data
