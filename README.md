# AI Full Stack Challenge — IT Access Requests

## The task
Northstar Labs receives access requests as free-text messages. Build a small runnable application that uses a language model to turn those messages into structured records and a review queue for the IT team. The supplied company, people and requests are fictional.

Start with materials/office-policy.md, the eight messages in materials/requests/, and snapshot.schema.json. Choose a CLI, service or web application as the interface.

## Required behavior
- Extract the request details using a language model. Supply snapshot.schema.json through the provider's native schema-constrained structured-output configuration, directly or through an SDK that forwards it. Keep the application-authored prompt focused on extraction instructions and field meanings; place the complete JSON schema exclusively in that configuration.
- Validate response structure and completion status before using extracted data. Preserve exact supporting quotes and represent uncertain fields as null with an explanatory issue.
- Apply the supplied review policy and display each request's status, owner and next action. Approval decisions belong to the named human reviewers.
- Record input filenames and SHA-256 hashes. Reuse unchanged results, process changed inputs and retain earlier versions. Process each message independently and make failures visible with a reproducible retry command.
- Handle malformed output, provider errors, refusal and interrupted responses explicitly. Keep model/provider settings configurable and document a supported configuration. The facilitator supplies model-provider access through environment variables.

## What to submit
| Path | Content |
|---|---|
| README.md | Setup, supported runtime/provider, exact intake/test/accuracy-check commands, environment-variable names, and how to inspect the queue |
| Source code and dependency lockfile | Runnable application, extraction prompt, schema and model request configuration |
| deliverables/extractions.jsonl | One current record per message: document_id, source_sha256, extraction (schema-conforming object, or null on error), status, owner, next_action, and error (null on success) |
| deliverables/queue.json | The review queue linked to extraction records by document_id |
| deliverables/accuracy.md | Expected and actual fields for the eight supplied messages and one paraphrase you author; exact-match counts with denominators, factual errors, model/configuration and run date; identify live calls and mocked tests |
| deliverables/request-evidence.json | Credential-redacted request configuration showing the schema setting, model ID and completion status |
| deliverables/verification.md | Commands run, observed results, repairs, and operating limits |
| Coding-session capture | Session record paired with the submitted commit, collected through the facilitator's capture setup |

Include automated tests covering a complete request, missing dates, conflicting details, embedded instructions, provider failure, an unchanged rerun, and changed source content. Build expected results from the supplied messages and policy. Add a paraphrased synthetic request to exercise extraction on fresh wording.

## Submission
Commit and push the application, outputs and session capture. Submit the repository URL and exact commit through the Classroom assignment. The facilitator supplies the assignment and capture instructions.
