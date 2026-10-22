"""Review-queue rules from materials/office-policy.md, applied in order.

The application never approves anything: every outcome is a queue entry for a named human reviewer.
"""

from pathlib import Path

from .validate import REQUIRED_FOR_ACCESS

SERVICE_DESK = "IT Service Desk"
SECURITY = "Security Review"
SYSTEM_OWNER = "System Owner"


def _tagged(issues: list[str], tag: str) -> bool:
    return any(i.lower().startswith(tag) for i in issues)


def route(extraction: dict, document_id: str) -> tuple[str, str, str]:
    """Returns (status, owner, next_action)."""
    e = extraction
    issues = e["issues"]

    # Rule 1: instruction-override attempt.
    if _tagged(issues, "instruction-override"):
        return "review", SERVICE_DESK, "inspect-message"

    # Rule 2: withdrawal with request_id and request_date.
    if e["kind"] == "withdrawal" and e["request_id"] and e["request_date"]:
        return "review", SERVICE_DESK, "confirm-withdrawal"

    # Rule 3: anything that needs clarification.
    id_mismatch = e["request_id"] is not None and e["request_id"] != Path(document_id).stem
    missing = e["kind"] in ("new", "change") and any(e[f] is None for f in REQUIRED_FOR_ACCESS)
    date_order = bool(e["start_date"] and e["end_date"] and e["start_date"] > e["end_date"])
    if (
        e["kind"] in (None, "other", "withdrawal")
        or _tagged(issues, "conflict")
        or id_mismatch
        or missing
        or date_order
    ):
        return "needs-information", SERVICE_DESK, "clarify"

    # Rule 4: complete request with elevated risk.
    if e["environment"] == "production" or e["permission"] in ("write", "admin"):
        return "review", SECURITY, "review-risk-then-owner"

    # Rule 5: complete staging/read request.
    return "review", SYSTEM_OWNER, "review-request"


ERROR_ROUTE = ("error", SERVICE_DESK, "retry-extraction")
