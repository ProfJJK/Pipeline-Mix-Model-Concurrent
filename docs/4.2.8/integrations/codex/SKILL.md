---
name: codex-pipeline
description: Submit and track explicitly requested CoChem pipeline jobs, prepare registered coding projects, inspect quota waits, and verify deliverables. Direct pipeline maintenance stays local.
---

# CoChem submissions from Codex

Use the `cochem-pipeline` MCP connection. Check `pipeline_health` and
`pipeline_projects` before choosing intake. Do not start providers or restart the
service to repair a submission problem.

## Choose the workflow

When health confirms `task_planning` is enabled, `pipeline_submit` runs the 4.2.8
SRS, research, independent review, owner approval where required, decomposition
and execution workflow. Submit a concrete objective, deliverables and acceptance
criteria. Supply the actual registered `project_id` for repository work. The
controller assigns task types, complexity, models and efforts.

If the repository is missing, use `pipeline_project_prepare` with its absolute
local path, existing branch, scoped `allowed_paths`, disjoint `test_paths` and
needed `context_paths`. The controller must authorize its configured trusted
root and capture a private isolated snapshot. Retain its project ID and source
capture evidence. Never use `windows-acceptance` or Google Drive as a substitute.
If the source changed after preparation, a new snapshot ID is required; do not
overwrite or reset the previous capture.

`pipeline_code` remains the existing staged coding workflow with its own test,
review and Git evidence. When `task_planning` is disabled, `pipeline_submit`
generates legacy chapter documents only. Explain this limitation instead of
claiming that a document performed repository work or external actions.

Submit once and retain the returned task/workflow ID immediately. A timeout
after sending is an uncertain outcome: reconcile existing records before any
repeat. Do not duplicate queued jobs. Reuse the captured output contract and
handoff form; do not invent hashes, identities, approvals or test results.

## Follow execution and evidence

Use `pipeline_status` for task/document intake and `pipeline_code_status` for
coding intake. Inspect `pipeline_operator_view` with the returned ID; request
`view="full"` when reviewing acceptance evidence. Respect reported wait times.
Quota exhaustion uses the recorded eligible fallbacks and backoff. Never lower
the reasoning floor, reset budgets, repeat sign-in or run a native agent outside
the pipeline to force progress.

High-complexity owner approval is a human decision. Present the actual plan,
architecture, SRS and changes; an agent cannot approve it using its shared token.
Treat cancellation/resumption as state changes and require the user's request
or authorization for that specific recovery.

A completed job is not by itself the requested outcome. Inspect required child
jobs, committed native/cleanup receipts, exact deliverables and hashes. Report
content integrity, independent model review, executed tests, isolated repository
output and original-repository integration separately. A model's prose cannot
prove that a video was inspected, a service deployed or a test ran. Require the
actual action evidence and flag unsupported assertions.

## Scope and connection

This skill governs requested pipeline submissions, not all coding. Direct local
pipeline maintenance is exempt. Preserve four shared slots, sign-ins, quotas,
repair budgets and existing databases. Do not redirect or reconfigure the exam,
YouTube or Antigravity specialists' workflows.

An unavailable MCP tool has not been called. A separate configured protocol probe
does not load tools into the current chat. New MCP/settings/rules may require a
refreshed Codex session; do not change protected runtime state to work around it.
This submission workflow needs no additional headless agent or custom agent.
