# Initial output contracts and prepared handoff forms

The worker's first prompt includes the output JSON schema and a prepared response
form from `src/cochem_pipeline/output_contracts.py`. The format validator uses
that same schema. Existing semantic checks remain authoritative for ownership,
requirements, source evidence, content, independent reviews and release results.

The form copies controller-known IDs, allowed paths, requirements, task types,
complexity, upstream hashes, required deliverable names and criteria. It never
fills in substantive work, approvals, successful checks or missing source facts.
Unfilled work fields are JSON `null`. A form by itself is not a valid completion.

For offline preparation from a captured execution node (a JSON object with
`kind` and `payload`), use the repository's Python 3.12 interpreter:

```powershell
& 'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe' -I scripts/prepare_job_handoff.py --node captured-node.json --output prepared-handoff.json
```

This helper does not submit a job, execute a provider, elevate, or change a live
configuration. It creates a new output file exclusively and refuses to overwrite
an existing form or result. No attempt IDs, fencing tokens or controller token
are included. Use a sanitized captured node without credentials in its payload.

The native worker distinguishes model-content JSON/structural errors from native
CLI protocol failures. `OutputFormatError.as_feedback()` returns only a contract
hash and bounded fixed issue codes/field paths. The controller attaches correction
feedback at the node root, separate from immutable task input. The prompt refuses
feedback for a changed contract or a correction number outside one through two.
Persisted correction scheduling and accounting are owned by the job store and
runtime; a model cannot request a budget reset by returning formatting prose.

New 4.2.8 deliverable hashes can be omitted or null. Before validation the worker
computes those hashes from the exact UTF-8 content and records raw and normalized
output digests plus changed digest fields in `receipt.output_normalization`.
This is a deterministic representation step, not verification that an external
action occurred. Supplied non-null hashes must match and are never repaired.
Upstream hashes, requirement links, content and verification claims are unchanged.

The source fixtures cover initial prompt/form agreement, input immutability,
semantic rejection after format acceptance, stale feedback, bounded corrections,
real microtask IDs, exclusive file creation, exact Unicode/newline hashing and
preservation of invalid supplied/upstream hashes. They do not attest that the
updated worker is deployed or that a native provider completed a new job.
