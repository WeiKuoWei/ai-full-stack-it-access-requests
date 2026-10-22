# Northstar IT access-request intake

Command-line application. Reads exported access-request messages, extracts a structured record from each with a language model, validates it, applies the review policy in `materials/office-policy.md`, and writes a review queue for the IT team. It approves nothing: every successful result waits for a named human reviewer.

## Supported runtime and provider

| Item | Value |
|---|---|
| Runtime | Python 3.11 or newer, run through `uv` |
| Supported configuration (used for the delivered results) | Gemini on Google Vertex AI: `INTAKE_PROVIDER=gemini`, model `gemini-2.5-pro`, location `global` |
| Schema setting | `snapshot.schema.json`, unmodified, sent as `response_json_schema` with `response_mime_type=application/json` in the `google-genai` request config |
| Also implemented, not run live | Claude through the Anthropic API (`INTAKE_PROVIDER=anthropic`) or through Vertex AI (`INTAKE_ANTHROPIC_VERTEX=1`); schema sent as `output_config.format`. Covered by stub-client tests only: the Vertex project used here returned 404 for every Claude model tried |

## Environment variables

| Name | Used for | Default |
|---|---|---|
| `GOOGLE_VERTEX_PROJECT` | Vertex AI project (required for Gemini, and for Claude on Vertex) | none |
| `GOOGLE_VERTEX_LOCATION` | Vertex AI location | `global` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the Google credentials file | none |
| `ANTHROPIC_API_KEY` | Anthropic API (only when `INTAKE_PROVIDER=anthropic`) | none |
| `INTAKE_PROVIDER` | `gemini` or `anthropic` | `gemini` |
| `INTAKE_MODEL` | Model ID | `gemini-2.5-pro` / `claude-opus-5-5` |
| `INTAKE_TEMPERATURE` | Sampling temperature | `0` |
| `INTAKE_MAX_OUTPUT_TOKENS` | Output token limit | `8192` |
| `INTAKE_WORKERS` | Messages processed concurrently | `4` |
| `INTAKE_ANTHROPIC_VERTEX` | `1` to reach Claude through Vertex AI | `0` |

Credential values are never written to outputs or to `store/logs/intake.log` (known secret variables, bearer tokens and API-key patterns are redacted).

## Commands

```
uv sync                                    # install from uv.lock
uv run pytest                              # automated tests (no network, no model calls)
uv run access-intake intake                # extract, validate, route the 20 files in materials/requests/
uv run access-intake queue                 # print the review queue as a table
uv run access-intake queue -v              # also print each entry's issues and errors
uv run access-intake accuracy              # rebuild deliverables/accuracy.md from current outputs
```

Accuracy check, end to end (live model calls: 20 supplied messages, then the authored paraphrase):

```
export INTAKE_PROVIDER=gemini GOOGLE_VERTEX_PROJECT=... GOOGLE_APPLICATION_CREDENTIALS=...
uv run access-intake intake
uv run access-intake intake --input-dir accuracy/paraphrase --out-dir accuracy/paraphrase-run --state-dir accuracy/paraphrase-store
uv run access-intake accuracy
```

Expected values live in `accuracy/expected.json`, written by hand from the messages and the policy.

## Inspecting the queue

| Where | What |
|---|---|
| `uv run access-intake queue` | One row per document: status, owner, next action, issue count |
| `deliverables/queue.json` | Full queue entries, linked to `deliverables/extractions.jsonl` by `document_id`; includes issues, error text, retry command, and paths of every stored result version |
| `deliverables/extractions.jsonl` | One current record per message |
| `deliverables/request-evidence.json` | Credential-free request configuration, model ID, and the completion status of the latest call per document |
| `store/results/<document_id>/<sha256>__<fingerprint>.json` | Every valid result ever produced, one file per source revision and configuration (history) |
| `store/attempts/<document_id>.jsonl` | Every attempt: reused, success or error |

## How it works

```
file bytes -> SHA-256 -> stored result for (hash, config fingerprint)?
                              |yes: reuse, no model call
                              |no:  model call (schema in native structured-output config)
                                   -> completion status -> JSON parse -> schema check
                                   -> date check -> quotes are exact substrings of the message
                                   -> code adds issues it can verify (id mismatch, date order,
                                      missing required facts, override wording)
                                   -> policy rules 1-5 -> owner, status, next action
```

- A message is processed independently. A failure becomes a queue entry with status `error`, owner IT Service Desk, next action `retry-extraction`, a null extraction, and the exact command to retry that one file.
- Handled explicitly: provider error (`provider-error`), refusal or safety block (`refusal`), cut-off output (`interrupted`), non-JSON output (`malformed`), schema or quote violations (`invalid`), unreadable input (`input`).
- Changed input gets a new result and the earlier result stays in `store/results/` with its earlier hash. If a later attempt fails, the last valid result stays in history and the current queue shows the latest error. Changing the model, temperature, prompt or schema changes the configuration fingerprint and reprocesses every file.

## Layout

| Path | Content |
|---|---|
| `src/access_intake/prompt.py` | Extraction instructions and field meanings (no schema) |
| `src/access_intake/providers.py` | Gemini-on-Vertex and Claude adapters, completion mapping |
| `src/access_intake/validate.py` | Response validation and verifiable-issue checks |
| `src/access_intake/policy.py` | Routing rules 1-5 and the error route |
| `src/access_intake/pipeline.py`, `store.py` | Hashing, reuse, history, outputs, redacted logging |
| `tests/` | Mocked tests (fake provider): complete request, missing dates, conflict, embedded instruction, provider failure, unchanged rerun, changed source, plus bad responses and adapter mapping |
| `deliverables/` | Submitted outputs |
