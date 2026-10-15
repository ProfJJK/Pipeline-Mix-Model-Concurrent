# Codex integration source audit

The current installed Codex skill, UI metadata and scoped global rule were read
on 2026-10-15. The configured unprivileged MCP client was separately probed;
the installed r4 server exposed fifteen tools, responded to health/projects,
and reported task planning disabled. This chat did not dynamically acquire MCP
tools. Existing client configuration, credentials and provider profiles were
not rewritten. No additional Codex agent definition is required for submission.

Versioned candidate files are in `integrations/codex/`: `SKILL.md`,
`agents/openai.yaml`, the narrowly scoped `AGENTS.md` rule and
`mcp.template.toml`. They are release inputs, not proof of installed behavior.
The template uses only the existing client-config path and reviewed runtime
path; it contains no token, provider credentials, environment values or personal
configuration. Never replace a user's whole configuration with this fragment.

The repaired server adds `pipeline_project_prepare` to expose the already scoped
controller preparation endpoint. An in-memory MCP test checks the exact endpoint
and fields and confirms it does not submit a model job. The refreshed instruction
describes enabled 4.2.8 task planning separately from disabled legacy document
generation and the existing coding workflow. The worker's output contract and
`scripts/prepare_job_handoff.py` use the same schema; the offline form has no
submission or execution authority.

`scripts/prepare_codex_integration_manifest.py` exports only these four explicitly
listed files from a supplied exact Git commit into a fresh directory, with hashes
and a source-commit manifest. It reads no personal configuration and changes no
live integration. The final release must include that manifest and verify its
pins before applying the Codex-only settings. Other specialists' integrations
remain under their owners.
