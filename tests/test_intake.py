import json
import logging

import pytest

from access_intake import policy
from access_intake.store import RedactingFilter
from conftest import EXPECTED, FakeProvider, ProviderError, ProviderResponse, expected_extraction, message_of


def by_id(records):
    return {r["document_id"]: r for r in records}


def test_complete_request_routes_to_system_owner(make_intake):
    r = by_id(make_intake(FakeProvider()).run())["IT-001.json"]
    assert (r["status"], r["owner"], r["next_action"]) == ("review", "System Owner", "review-request")
    assert r["error"] is None and r["extraction"]["permission"] == "read"


def test_missing_dates_need_clarification(make_intake):
    r = by_id(make_intake(FakeProvider()).run())["IT-011.json"]
    assert r["extraction"]["start_date"] is None and r["extraction"]["end_date"] is None
    assert (r["status"], r["next_action"]) == ("needs-information", "clarify")


def test_conflicting_details_need_clarification(make_intake):
    records = by_id(make_intake(FakeProvider()).run())
    for doc in ("IT-004.json", "IT-020.json"):
        assert records[doc]["status"] == "needs-information"
        assert any(i.startswith("conflict") for i in records[doc]["extraction"]["issues"])


def test_conflict_tag_alone_routes_to_clarify_even_with_a_value(workspace, make_intake):
    """A model that picks one alternative but reports the conflict still goes to clarification."""
    msg = message_of(workspace / "requests" / "IT-020.json")
    ext = expected_extraction("IT-020.json", msg)
    ext["manager"] = "Priya Shah"
    r = by_id(make_intake(FakeProvider({"IT-020.json": ext})).run(only=["IT-020.json"]))["IT-020.json"]
    assert r["next_action"] == "clarify"


def test_embedded_instructions_go_to_inspection(make_intake):
    r = by_id(make_intake(FakeProvider()).run())["IT-006.json"]
    assert (r["status"], r["owner"], r["next_action"]) == ("review", "IT Service Desk", "inspect-message")
    assert r["extraction"]["permission"] == "read"


def test_validator_flags_override_the_model_missed(workspace, make_intake):
    msg = message_of(workspace / "requests" / "IT-006.json")
    ext = expected_extraction("IT-006.json", msg)
    ext["issues"] = []
    r = by_id(make_intake(FakeProvider({"IT-006.json": ext})).run(only=["IT-006.json"]))["IT-006.json"]
    assert r["next_action"] == "inspect-message"
    assert any(q in msg and "SYSTEM OVERRIDE" in q for q in r["extraction"]["supporting_quotes"])


def test_provider_failure_is_isolated_and_retryable(make_intake):
    provider = FakeProvider({"IT-003.json": ProviderError("Vertex AI API error 503: unavailable")})
    records = by_id(make_intake(provider).run())
    failed = records["IT-003.json"]
    assert (failed["status"], failed["owner"], failed["next_action"]) == ("error", "IT Service Desk", "retry-extraction")
    assert failed["extraction"] is None
    assert "uv run access-intake intake --only IT-003.json" in failed["error"]
    assert sum(r["status"] == "error" for r in records.values()) == 1
    assert len(records) == 20


@pytest.mark.parametrize("response, kind", [
    (ProviderResponse("complete", "{not json", "STOP"), "malformed"),
    (ProviderResponse("refusal", None, "SAFETY"), "refusal"),
    (ProviderResponse("interrupted", '{"request_id": "IT-0', "MAX_TOKENS"), "interrupted"),
    (ProviderResponse("complete", json.dumps({"request_id": "IT-002"}), "STOP"), "invalid"),
])
def test_bad_responses_become_visible_errors(make_intake, response, kind):
    r = by_id(make_intake(FakeProvider({"IT-002.json": response})).run(only=["IT-002.json"]))["IT-002.json"]
    assert r["status"] == "error" and r["error"].startswith(kind)


def test_non_verbatim_quote_is_rejected(workspace, make_intake):
    ext = expected_extraction("IT-001.json", message_of(workspace / "requests" / "IT-001.json"))
    ext["supporting_quotes"] = ["Maya Chen from analytics"]  # case changed
    r = by_id(make_intake(FakeProvider({"IT-001.json": ext})).run(only=["IT-001.json"]))["IT-001.json"]
    assert r["status"] == "error" and "exact substring" in r["error"]


def test_unchanged_rerun_reuses_results(workspace, make_intake):
    provider = FakeProvider()
    make_intake(provider).run()
    assert len(provider.calls) == 20
    rerun = FakeProvider()
    records = make_intake(rerun).run()
    assert rerun.calls == []
    lines = (workspace / "out" / "extractions.jsonl").read_text().splitlines()
    assert len(lines) == 20 == len({json.loads(l)["document_id"] for l in lines})
    queue = json.loads((workspace / "out" / "queue.json").read_text())
    assert len(queue["entries"]) == 20
    assert all(r["status"] != "error" for r in records)


def test_changed_source_creates_new_result_and_keeps_old(workspace, make_intake):
    make_intake(FakeProvider()).run()
    path = workspace / "requests" / "IT-001.json"
    old_sha = by_id(make_intake(FakeProvider()).run())["IT-001.json"]["source_sha256"]
    export = json.loads(path.read_text())
    export["message"] = export["message"].replace("2026-11-06", "2026-11-07")
    path.write_text(json.dumps(export, indent=2))

    provider = FakeProvider()
    records = by_id(make_intake(provider).run())
    assert provider.calls == ["IT-001.json"]
    new = records["IT-001.json"]
    assert new["source_sha256"] != old_sha
    history = sorted(p.name.split("__")[0] for p in (workspace / "state" / "results" / "IT-001.json").glob("*.json"))
    assert sorted([old_sha, new["source_sha256"]]) == history
    current = [json.loads(l) for l in (workspace / "out" / "extractions.jsonl").read_text().splitlines()]
    assert [r["source_sha256"] for r in current if r["document_id"] == "IT-001.json"] == [new["source_sha256"]]


def test_failure_after_change_keeps_last_valid_result_in_history(workspace, make_intake):
    make_intake(FakeProvider()).run()
    path = workspace / "requests" / "IT-002.json"
    path.write_bytes(path.read_bytes() + b"\n")
    records = by_id(make_intake(FakeProvider({"IT-002.json": ProviderError("timeout")})).run())
    assert records["IT-002.json"]["status"] == "error"
    kept = list((workspace / "state" / "results" / "IT-002.json").glob("*.json"))
    assert len(kept) == 1 and json.loads(kept[0].read_text())["status"] == "review"
    entry = next(e for e in json.loads((workspace / "out" / "queue.json").read_text())["entries"]
                 if e["document_id"] == "IT-002.json")
    assert entry["error"] and entry["result_versions"]


def test_retry_after_error_succeeds(make_intake):
    make_intake(FakeProvider({"IT-003.json": ProviderError("503")})).run()
    records = by_id(make_intake(FakeProvider()).run(only=["IT-003.json"]))
    assert records["IT-003.json"]["status"] == "needs-information"
    assert len(records) == 20


@pytest.mark.parametrize("document_id", sorted(EXPECTED))
def test_policy_routes_expected_extractions(document_id):
    """Routing applied to the hand-built expected extraction reproduces the expected queue entry."""
    exp = EXPECTED[document_id]
    ext = {k: exp[k] for k in ("request_id", "request_date", "kind", "requester", "team", "system",
                               "environment", "permission", "start_date", "end_date", "manager")}
    ext["business_purpose"] = "x"
    ext["issues"] = [f"{t}: x" for t in exp["required_issue_tags"]]
    assert policy.route(ext, document_id) == (exp["status"], exp["owner"], exp["next_action"])


def test_log_redaction(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret123")
    record = logging.LogRecord("x", logging.INFO, "", 0, "key=%s auth=Bearer abc.def", ("sk-ant-secret123",), None)
    RedactingFilter().filter(record)
    assert "secret123" not in record.msg and "abc.def" not in record.msg
