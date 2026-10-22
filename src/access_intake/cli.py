"""Command line: intake, queue, accuracy."""

import argparse
import json
from pathlib import Path

from . import config, providers
from .config import REPO_ROOT
from .pipeline import Intake

DEFAULT_INPUT = REPO_ROOT / "materials" / "requests"
DEFAULT_OUT = REPO_ROOT / "deliverables"
DEFAULT_STATE = REPO_ROOT / "store"


def _retry_base(args) -> str:
    cmd = "uv run access-intake intake"
    for flag, value, default in (
        ("--input-dir", args.input_dir, DEFAULT_INPUT),
        ("--out-dir", args.out_dir, DEFAULT_OUT),
        ("--state-dir", args.state_dir, DEFAULT_STATE),
    ):
        if Path(value).resolve() != default.resolve():
            cmd += f" {flag} {value}"
    return cmd


def cmd_intake(args) -> int:
    settings = config.from_env()
    intake = Intake(
        settings,
        providers.build(settings),
        Path(args.input_dir),
        Path(args.out_dir),
        Path(args.state_dir),
        _retry_base(args),
    )
    records = intake.run(only=args.only)
    errors = [r for r in records if r["status"] == "error"]
    print(f"{len(records)} current records, {len(errors)} errors -> {args.out_dir}")
    for r in errors:
        print(f"  {r['document_id']}: {r['error']}")
    return 1 if errors else 0


def cmd_queue(args) -> int:
    queue = json.loads((Path(args.out_dir) / "queue.json").read_text(encoding="utf-8"))
    rows = [("document", "status", "owner", "next action", "issues")]
    for e in queue["entries"]:
        rows.append((e["document_id"], e["status"], e["owner"], e["next_action"], str(len(e["issues"]))))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))
    if args.verbose:
        for e in queue["entries"]:
            if e["issues"] or e["error"]:
                print(f"\n{e['document_id']}")
                for i in e["issues"]:
                    print(f"  - {i}")
                if e["error"]:
                    print(f"  ! {e['error']}")
    return 0


def cmd_accuracy(args) -> int:
    from .accuracy import write_report

    path = write_report(REPO_ROOT)
    print(f"wrote {path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="access-intake")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("intake", help="extract, validate and route every request export")
    p.add_argument("--only", action="append", metavar="DOCUMENT_ID", help="process only this file (repeatable)")
    p.add_argument("--input-dir", default=str(DEFAULT_INPUT))
    p.add_argument("--out-dir", default=str(DEFAULT_OUT))
    p.add_argument("--state-dir", default=str(DEFAULT_STATE))
    p.set_defaults(func=cmd_intake)

    p = sub.add_parser("queue", help="print the current review queue")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT))
    p.add_argument("-v", "--verbose", action="store_true", help="also print issues and errors")
    p.set_defaults(func=cmd_queue)

    p = sub.add_parser("accuracy", help="compare current outputs with accuracy/expected.json")
    p.set_defaults(func=cmd_accuracy)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
