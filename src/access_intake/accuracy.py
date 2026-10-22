"""Builds deliverables/accuracy.md from current outputs and accuracy/expected.json. Makes no model calls."""

import json
from pathlib import Path

FIELDS = (
    "request_id", "request_date", "kind", "requester", "team", "system",
    "environment", "permission", "start_date", "end_date", "manager",
)
ROUTING = ("status", "owner", "next_action")
RUNS = (("deliverables", "supplied messages"), ("accuracy/paraphrase-run", "authored paraphrase"))


def _load_records(root: Path) -> dict[str, dict]:
    records = {}
    for rel, _ in RUNS:
        p = root / rel / "extractions.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line:
                    r = json.loads(line)
                    records[r["document_id"]] = r
    return records


def _fmt(v) -> str:
    return "null" if v is None else f"`{v}`"


def compare(expected: dict, record: dict | None) -> dict:
    ext = (record or {}).get("extraction") or {}
    rows = []
    for f in FIELDS:
        rows.append((f, expected[f], ext.get(f) if ext else "(no extraction)", ext.get(f) == expected[f] if ext else False))
    for f in ROUTING:
        actual = (record or {}).get(f)
        rows.append((f, expected[f], actual, actual == expected[f]))
    purpose_expected = expected["business_purpose"]
    purpose_actual = ext.get("business_purpose") if ext else None
    if purpose_expected == "either":
        purpose_ok = None
    else:
        purpose_ok = (purpose_actual is not None) == (purpose_expected == "present")
    issues = ext.get("issues", []) if ext else []
    tags_ok = all(any(i.lower().startswith(t) for i in issues) for t in expected["required_issue_tags"])
    return {"rows": rows, "purpose": (purpose_expected, purpose_actual, purpose_ok), "tags_ok": tags_ok, "issues": issues}


def write_report(root: Path) -> Path:
    expected = json.loads((root / "accuracy" / "expected.json").read_text(encoding="utf-8"))["documents"]
    records = _load_records(root)
    evidence = json.loads((root / "deliverables" / "request-evidence.json").read_text(encoding="utf-8"))
    calls = evidence["latest_model_call_per_document"]
    para_ev_path = root / "accuracy" / "paraphrase-run" / "request-evidence.json"
    if para_ev_path.exists():
        calls = calls + json.loads(para_ev_path.read_text(encoding="utf-8"))["latest_model_call_per_document"]
    run_dates = sorted({c["at"][:10] for c in calls})
    cfg = evidence["request_config"]

    results = {doc: compare(exp, records.get(doc)) for doc, exp in expected.items()}
    n_docs = len(results)
    field_hits = sum(ok for r in results.values() for (f, _, _, ok) in r["rows"] if f in FIELDS)
    route_hits = sum(ok for r in results.values() for (f, _, _, ok) in r["rows"] if f in ROUTING)
    full_route = sum(all(ok for (f, _, _, ok) in r["rows"] if f in ROUTING) for r in results.values())
    purpose_scored = [r["purpose"][2] for r in results.values() if r["purpose"][2] is not None]
    tags_hits = sum(r["tags_ok"] for r in results.values())

    per_field = []
    for f in FIELDS + ROUTING:
        hits = sum(ok for r in results.values() for (g, _, _, ok) in r["rows"] if g == f)
        per_field.append(f"| {f} | {hits}/{n_docs} |")

    errors = []
    for doc, r in results.items():
        for f, exp, act, ok in r["rows"]:
            if not ok:
                errors.append(f"| {doc} | {f} | {_fmt(exp)} | {_fmt(act)} |")
        if r["purpose"][2] is False:
            errors.append(f"| {doc} | business_purpose presence | {r['purpose'][0]} | {_fmt(r['purpose'][1])} |")
        if not r["tags_ok"]:
            errors.append(f"| {doc} | required issue tag | {', '.join(expected[doc]['required_issue_tags'])} | not present |")

    lines = [
        "---",
        "style: descriptive",
        "generated_by: uv run access-intake accuracy",
        "---",
        "",
        "# Accuracy",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Provider | {cfg['provider']} ({cfg['sdk']} SDK) |",
        f"| Model | `{cfg['model']}` |",
        f"| Schema setting | `{evidence['schema_setting']}` (`response_json_schema` = `snapshot.schema.json`, unmodified) |",
        f"| Configuration fingerprint | `{evidence['config_fingerprint']}` (model, temperature, prompt, schema) |",
        f"| Live model calls behind these results | {len(calls)} (one per document; see `deliverables/request-evidence.json`) |",
        f"| Run date(s) of those calls (UTC) | {', '.join(run_dates) or 'none'} |",
        "| Expected values | `accuracy/expected.json`, written by hand from each message and `materials/office-policy.md` |",
        "| Mocked tests | `tests/` (pytest) use a fake provider and make no model calls; see `deliverables/verification.md` |",
        "",
        "## Exact-match counts",
        "",
        "| Measure | Matches |",
        "|---|---|",
        f"| Extracted scalar fields (11 per document) | {field_hits}/{n_docs * len(FIELDS)} |",
        f"| Routing values (status, owner, next_action) | {route_hits}/{n_docs * len(ROUTING)} |",
        f"| Documents routed fully correctly | {full_route}/{n_docs} |",
        f"| business_purpose presence (documents where the policy settles it) | {sum(purpose_scored)}/{len(purpose_scored)} |",
        f"| Required issue tags present | {tags_hits}/{n_docs} |",
        "",
        "business_purpose is free text, so only null versus non-null is compared.",
        "",
        "### By field",
        "",
        "| Field | Matches |",
        "|---|---|",
        *per_field,
        "",
        "## Factual errors",
        "",
    ]
    if errors:
        lines += ["| Document | Field | Expected | Actual |", "|---|---|---|---|", *errors]
    else:
        lines.append("None: every compared value matched.")
    lines += ["", "## Expected and actual, per document", ""]
    for doc, r in results.items():
        source = "authored paraphrase" if doc == "IT-021.json" else "supplied message"
        lines += [f"### {doc} ({source})", "", f"Basis: {expected[doc]['basis']}.", "",
                  "| Field | Expected | Actual | Match |", "|---|---|---|---|"]
        for f, exp, act, ok in r["rows"]:
            lines.append(f"| {f} | {_fmt(exp)} | {_fmt(act)} | {'yes' if ok else 'NO'} |")
        pe, pa, pok = r["purpose"]
        lines.append(f"| business_purpose | {pe} | {_fmt(pa)} | {'n/a' if pok is None else 'yes' if pok else 'NO'} |")
        lines += ["", "Issues reported:", ""]
        lines += [f"- {i}" for i in r["issues"]] or ["- none"]
        lines.append("")

    out = root / "deliverables" / "accuracy.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
