---
style: descriptive
---

# Verification

Run date: 2026-10-22 (UTC). Provider: Gemini `gemini-2.5-pro` on Google Vertex AI, project `gitroll`, location `global`.

## Commands and observed results

| # | Command | Observed |
|---|---|---|
| 1 | `uv run pytest -q` | 44 passed, 0 model calls (fake provider and stub clients) |
| 2 | Mutation check: removed `or e["permission"] in ("write", "admin")` from rule 4 in `policy.py`, ran `uv run pytest -q` | 2 failed (`test_policy_routes_expected_extractions` for IT-007 and IT-012); file restored, 38 passed |
| 3 | Mutation check: replaced `if cached:` with `if False:` in `pipeline.py`, ran `uv run pytest -q` | 2 failed (`test_unchanged_rerun_reuses_results`, `test_changed_source_creates_new_result_and_keeps_old`); file restored, 38 passed |
| 4 | Live probe of Claude on Vertex (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-opus-4-8`, `-4-7`, `-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5@20251001`, `claude-sonnet-5`, `claude-opus-5`, `claude-haiku-5-5`) | 404 for all ten: not available to project `gitroll` |
| 5 | Live probe of Gemini with `snapshot.schema.json` as `response_json_schema` | `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash-preview` returned schema-shaped JSON with finish reason STOP; `gemini-3-pro-preview` returned 404 |
| 6 | `uv run access-intake intake` (first live run, 20 files) | 20 current records, 0 errors; accuracy 230/231 fields, 62/63 routing values |
| 7 | Same command after the prompt repair below | 20 records, 1 error: IT-008 rejected, supporting quote `'(Correction: environment is actually staging. Previous entry used production.)'` added a closing parenthesis not in the message |
| 8 | `uv run access-intake intake --only IT-008.json` (the retry command printed in the error) | 20 current records, 0 errors |
| 9 | `uv run access-intake intake --input-dir accuracy/paraphrase --out-dir accuracy/paraphrase-run --state-dir accuracy/paraphrase-store` | 1 record, 0 errors |
| 10 | `uv run access-intake accuracy` | 231/231 fields, 63/63 routing values, 21/21 documents routed correctly (`deliverables/accuracy.md`) |
| 11 | `uv run access-intake intake` (unchanged rerun) | 20 current records, 0 errors; `store/attempts/` shows 20 `reused` outcomes and no model call; `deliverables/extractions.jsonl` has 20 lines |
| 12 | `grep -rIl -E 'AIza\|sk-ant\|private_key\|Bearer ' deliverables store accuracy` | no matches |

## Repairs

| Finding | Repair | Result |
|---|---|---|
| Run 1: IT-003 returned kind `other`; the requester asks for new Beacon access without details | Prompt: `new` covers access the requester does not have yet even when details are missing | IT-003 kind `new` |
| Run 1: IT-005 flagged "Please record the request as withdrawn" as an instruction-override, routing to `inspect-message` instead of `confirm-withdrawal` | Prompt: defined an override as text that changes system or reviewer behaviour; an ordinary ask of the IT team is the request | IT-005 routes `confirm-withdrawal` |
| Run 2: one invalid supporting quote on IT-008 (row 7) | None to the code: the exact-substring check did its job and the single retry succeeded | IT-008 `review-request` |
| `/tmp/pol.bak` backup left by the mutation checks | Not deleted: the workspace's recent-file guard refused the `rm` | harmless file outside the repository |

Run 1 results are kept in `accuracy/runs/` (`run-1_accuracy.md`, `run-1_request-evidence.json`). Every result produced under the earlier prompt remains in `store/results/<document_id>/` next to the later one, keyed by configuration fingerprint.

## Operating limits

| Limit | Detail |
|---|---|
| Not verified live | Claude through the Anthropic API or Vertex AI: no Claude model reachable from the available project (row 4); only stub-client tests cover that adapter |
| Model variation | Temperature 0 does not make Gemini deterministic; row 7 shows one run producing a quote that failed validation and passed on retry. A rerun of the whole set can differ from `deliverables/accuracy.md` |
| Accuracy scope | 21 documents; expected values written by the same author as the code. `business_purpose` is compared for null versus non-null only |
| Override detection | Model-reported, plus a regular expression for six known phrasings in `validate.py`; a differently worded embedded instruction depends on the model flagging it |
| Required-fact checks | Done in code only for kind `new` or `change`; a withdrawal with a missing request id or date goes to `needs-information` through rule 3 |
| Retry | Manual, one command per failed file; there is no automatic retry or backoff |
| Rate limits | Concurrency is `INTAKE_WORKERS` (default 4); no rate-limit backoff |
| Coding-session capture | Not part of this repository: it comes from the facilitator's capture setup |
