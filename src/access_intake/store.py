"""On-disk state.

state_dir/
  results/<document_id>/<sha256>__<fingerprint>.json   every valid result, one per source revision
                                                         and configuration (history; never overwritten)
  attempts/<document_id>.jsonl                           every attempt: reused, success or error
  logs/intake.log                                        credential-redacted operational log
out_dir/
  extractions.jsonl, queue.json, request-evidence.json   current outputs only
"""

import json
import logging
import os
import re
from pathlib import Path

CURRENT_FIELDS = ("document_id", "source_sha256", "extraction", "status", "owner", "next_action", "error")


class Store:
    def __init__(self, state_dir: Path, out_dir: Path):
        self.state_dir = state_dir
        self.out_dir = out_dir

    def result_path(self, document_id: str, sha: str, fingerprint: str) -> Path:
        return self.state_dir / "results" / document_id / f"{sha}__{fingerprint}.json"

    def load_result(self, document_id: str, sha: str, fingerprint: str) -> dict | None:
        p = self.result_path(document_id, sha, fingerprint)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def save_result(self, record: dict, fingerprint: str) -> Path:
        p = self.result_path(record["document_id"], record["source_sha256"], fingerprint)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return p

    def history(self, document_id: str) -> list[Path]:
        d = self.state_dir / "results" / document_id
        return sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []

    def append_attempt(self, document_id: str, attempt: dict) -> None:
        p = self.state_dir / "attempts" / f"{document_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(attempt, ensure_ascii=False) + "\n")

    def attempts(self, document_id: str) -> list[dict]:
        p = self.state_dir / "attempts" / f"{document_id}.jsonl"
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]

    def load_current(self) -> dict[str, dict]:
        p = self.out_dir / "extractions.jsonl"
        if not p.exists():
            return {}
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]
        return {r["document_id"]: r for r in rows}

    def write_current(self, records: list[dict]) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        with (self.out_dir / "extractions.jsonl").open("w", encoding="utf-8") as f:
            for r in sorted(records, key=lambda r: r["document_id"]):
                f.write(json.dumps({k: r[k] for k in CURRENT_FIELDS}, ensure_ascii=False) + "\n")

    def write_json(self, name: str, data) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class RedactingFilter(logging.Filter):
    """Removes credential values from log lines: known secret env vars, bearer tokens, API keys."""

    SECRET_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_KEY", "GEMINI_API_KEY")
    PATTERNS = [re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"), re.compile(r"\b(sk-ant-|AIza)[A-Za-z0-9_\-]+")]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for name in self.SECRET_ENV:
            value = os.environ.get(name)
            if value:
                msg = msg.replace(value, f"[{name} redacted]")
        for p in self.PATTERNS:
            msg = p.sub(lambda m: (m.group(1) if m.lastindex else "") + "[redacted]", msg)
        record.msg, record.args = msg, ()
        return True


def setup_logging(state_dir: Path) -> logging.Logger:
    log = logging.getLogger("access_intake")
    log.setLevel(logging.INFO)
    if not log.handlers:
        (state_dir / "logs").mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(state_dir / "logs" / "intake.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler.addFilter(RedactingFilter())
        log.addHandler(handler)
    return log
