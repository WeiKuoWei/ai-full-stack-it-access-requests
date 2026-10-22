"""Intake run: hash each input, reuse or extract, validate, route, write current outputs."""

import datetime as dt
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import policy
from .config import Settings, config_fingerprint
from .prompt import SYSTEM_PROMPT, user_message
from .providers import ProviderError
from .store import Store, setup_logging
from .validate import ExtractionError, apply_checks, parse_and_validate


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Intake:
    def __init__(self, settings: Settings, provider, input_dir: Path, out_dir: Path, state_dir: Path, retry_base: str):
        self.settings = settings
        self.provider = provider
        self.input_dir = input_dir
        self.store = Store(state_dir, out_dir)
        self.fingerprint = config_fingerprint(settings, SYSTEM_PROMPT)
        self.retry_base = retry_base
        self.log = setup_logging(state_dir)

    def retry_command(self, document_id: str) -> str:
        return f"{self.retry_base} --only {document_id}"

    def process(self, path: Path) -> dict:
        document_id = path.name
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        attempt = {"at": _now(), "source_sha256": sha, "fingerprint": self.fingerprint, "model": self.settings.model}

        cached = self.store.load_result(document_id, sha, self.fingerprint)
        if cached:
            self.store.append_attempt(document_id, {**attempt, "outcome": "reused"})
            self.log.info("%s reused %s", document_id, sha[:12])
            return cached

        try:
            export = json.loads(raw.decode("utf-8"))
            message = export["message"]
            if not isinstance(message, str):
                raise ValueError("message is not a string")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as e:
            return self._fail(document_id, sha, attempt, ExtractionError("input", f"cannot read export: {e}"))

        try:
            response = self.provider.extract(user_message(document_id, export))
        except ProviderError as e:
            return self._fail(document_id, sha, attempt, ExtractionError("provider-error", str(e)))
        attempt.update(completion=response.completion, finish_reason=response.finish_reason, usage=response.usage)

        try:
            extraction = parse_and_validate(response, self.settings.schema, message)
        except ExtractionError as e:
            return self._fail(document_id, sha, attempt, e)

        extraction = apply_checks(extraction, document_id, message)
        status, owner, next_action = policy.route(extraction, document_id)
        record = {
            "document_id": document_id,
            "source_sha256": sha,
            "extraction": extraction,
            "status": status,
            "owner": owner,
            "next_action": next_action,
            "error": None,
            "processed_at": attempt["at"],
            "model": self.settings.model,
            "subject": export.get("subject"),
        }
        self.store.save_result(record, self.fingerprint)
        self.store.append_attempt(document_id, {**attempt, "outcome": "success", "status": status})
        self.log.info("%s extracted %s -> %s / %s", document_id, sha[:12], owner, next_action)
        return record

    def _fail(self, document_id: str, sha: str, attempt: dict, err: ExtractionError) -> dict:
        status, owner, next_action = policy.ERROR_ROUTE
        error = f"{err}. Retry: {self.retry_command(document_id)}"
        self.store.append_attempt(document_id, {**attempt, "outcome": "error", "error_kind": err.kind, "error": str(err)})
        self.log.warning("%s failed: %s", document_id, err)
        return {
            "document_id": document_id,
            "source_sha256": sha,
            "extraction": None,
            "status": status,
            "owner": owner,
            "next_action": next_action,
            "error": error,
            "processed_at": attempt["at"],
            "model": self.settings.model,
            "subject": None,
        }

    def run(self, only: list[str] | None = None) -> list[dict]:
        files = sorted(self.input_dir.glob("*.json"))
        if only:
            missing = set(only) - {p.name for p in files}
            if missing:
                raise SystemExit(f"not found in {self.input_dir}: {', '.join(sorted(missing))}")
            targets = [p for p in files if p.name in only]
        else:
            targets = files

        # Each message is independent: one failure never stops the others.
        with ThreadPoolExecutor(max_workers=max(1, self.settings.workers)) as pool:
            fresh = {r["document_id"]: r for r in pool.map(self.process, targets)}

        previous = self.store.load_current()
        names = {p.name for p in files}
        current = [fresh.get(n) or previous.get(n) for n in sorted(names)]
        current = [r for r in current if r is not None]
        self.store.write_current(current)
        self.store.write_json("queue.json", self.queue(current))
        self.store.write_json("request-evidence.json", self.evidence(current))
        return current

    def queue(self, records: list[dict]) -> dict:
        entries = []
        for r in records:
            e = r["extraction"] or {}
            versions = [str(p.relative_to(self.store.state_dir.parent)) for p in self.store.history(r["document_id"])]
            entries.append({
                "document_id": r["document_id"],
                "source_sha256": r["source_sha256"],
                "status": r["status"],
                "owner": r["owner"],
                "next_action": r["next_action"],
                "request_id": e.get("request_id"),
                "kind": e.get("kind"),
                "requester": e.get("requester"),
                "system": e.get("system"),
                "environment": e.get("environment"),
                "permission": e.get("permission"),
                "issues": e.get("issues", []),
                "error": r["error"],
                "retry_command": self.retry_command(r["document_id"]) if r["status"] == "error" else None,
                "result_versions": versions,
            })
        return {
            "generated_at": _now(),
            "note": "Review queue only. Approval decisions belong to the named human reviewers.",
            "entries": entries,
        }

    def evidence(self, records: list[dict]) -> dict:
        calls = []
        for r in records:
            live = [a for a in self.store.attempts(r["document_id"]) if a.get("outcome") in ("success", "error")]
            if live:
                a = live[-1]
                calls.append({
                    "document_id": r["document_id"],
                    "at": a["at"],
                    "model": a["model"],
                    "completion": a.get("completion"),
                    "finish_reason": a.get("finish_reason"),
                    "outcome": a["outcome"],
                    "usage": a.get("usage"),
                })
        config = self.provider.request_config()
        return {
            "request_config": config,
            "schema_setting": next(k for k in ("generation_config", "output_config") if k in config),
            "response_schema": self.settings.schema,
            "credentials": "supplied by environment (GOOGLE_APPLICATION_CREDENTIALS or ANTHROPIC_API_KEY); values never written",
            "config_fingerprint": self.fingerprint,
            "latest_model_call_per_document": calls,
        }
