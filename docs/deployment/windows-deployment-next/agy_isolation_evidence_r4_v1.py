"""Agy isolation and model-identity evidence under the worker tokens (build-manifest step 6, r5 sitting S8).

Standalone artifact copied by agy-isolation-evidence-r4-v1.ps1, together with the hash-pinned
cochem-inference-only.agent.md, into a fresh SYSTEM/BA-only root and run once by a one-shot SYSTEM
task (PT10M) under the pinned r4 interpreter (-I -B). Never import it from the checkout for a real
run. Derived from agy_status_capture_r4_v1.py (sha256 ce103aad..., the r5 onboarding-audit re-pin: r4 custody,
require_stopped, observe_child, inventory, receipt skeleton) and the stdin pipe of worker_claude_login_bridge_r3.py
(sha256 b5bbede8...: one line, flush, EOF).

Mode 'evidence' (slot1, root C:\\Program Files\\CoChem\\AgyIsolation4.2.7-windows-20261011-r4-v1-<attempt>,
receipt isolation-receipt.json, schema cochem-agy-isolation-evidence/1): (a) stage the protected custom
agent into the slot1 profile at BOTH discovery locations (SYSTEM/BA full, worker read-only, sha256
re-verified before every launch) and check the other discovery locations for a same-name shadow;
(b) inventory the six worker profiles (names, sizes, sha256; token files size only, never opened; the
declared ~/.gemini/config/{config,skills,plugins}.json are inspected as strict JSON for non-empty
plugin/mcp/hook/skill/agent/sidecar keys and recorded by key NAME only; ~/.gemini/config/sidecars is
a hooks-class location), the
two workspaces (slot root and RAM workspace) with EVERY ancestor up to the drive root, and (read-only,
before and after the runs) C:\\ProgramData\\Antigravity, which must be absent or the protected empty
folder of the stage mode; (c) attest the worker environment block as SYSTEM through win._worker_token +
win._worker_environment (variable NAMES only); then four non-inference pre-check probes (version,
models json, agents json, agents text) under the worker token. Only when the slot is signed in and
the agent listing is exactly ['cochem-inference-only'] does the bounded model-form matrix run in the
order R1 slug, R5 owner's effort-null slug, R2 slug + --effort high, R3 family id + --effort high, R4
unknown id: stdin one NDJSON line then EOF, 120 s wall bound then Job termination, 1 MiB output
bound, raw NDJSON/stderr kept in the private root (raw/), a redacted replay copy for config-builder
gate G5 (replay/), profile deltas and the owned Job's process accounting after each run (any process
beyond agy's own tree fails G3), and a bounded phrase count over the cli-*.log files the run created (a
true model-fallback phrase in an accepted run clears reroute_scan_clean and fails G3). The argv equals the production argv (no -p, no
--print-timeout/--project/--log-file). Runs the deadline guard skips after a passing R1 leave the
evidence complete, with the gate resting on R1 and the skipped runs executed false.

Mode 'stage' (all six slots, root ...-<attempt>-stage, receipt stage-receipt.json, schema
cochem-agy-agent-staging/1): first create C:\\ProgramData\\Antigravity as the protected empty folder
(SYSTEM owner, SYSTEM/BA full, Users read and execute) or accept it only when it already is exactly
that folder (anything else is refused and preserved); stage the same pinned agent into every worker
profile at both locations with the same ACL, protect both parent folders (.gemini/agents and
.gemini/config/agents: worker list and traverse only), check shadows, and prove under each worker
token that ['--output-format','json','agents'] and ['agents'] list exactly ['cochem-inference-only'].
No model job.

Receipts carry only allowlisted classifications, digests and sanitized error strings; they are
written CreateNew. Every gate failure is recorded (held), never retried.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from types import SimpleNamespace

COCHEM = Path(r'C:\Program Files\CoChem')
EVIDENCE_BASE = COCHEM
INSTALL = COCHEM / 'Pipeline4.2.7-windows-20261009-r4'
PREVIOUS_INSTALL = COCHEM / 'Pipeline4.2.7-windows-20261007-r3'
NATIVE = COCHEM / 'Native4.2.7-windows-20261006'
EXECUTABLE = NATIVE / 'agy.exe'
PYTHON = INSTALL / '.venv' / 'Scripts' / 'python.exe'
BASE_PYTHON = COCHEM / 'Toolchain4.2.7-windows-20261006' / 'Python312' / 'python.exe'
PROFILE_PARENT = Path(r'C:\Users')
HELPER_NAME = 'agy_isolation_evidence_r4_v1.py'
AGENT_FILE_NAME = 'cochem-inference-only.agent.md'
# Fixed namespace date (this component's build date); the helper refuses any other root name.
NAMESPACE_DATE = '20261011'
ROOT_PREFIX = 'AgyIsolation4.2.7-windows-' + NAMESPACE_DATE + '-r4-v1-'

INSTALL_RECEIPT_SHA256 = '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
MANIFEST_SHA256 = '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
REVISION_SHA256 = '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
WINDOWS_SHA256 = 'ca07b3bba2b22d0eb095c1f05b9a6c0969207bf7d8b25741adbaee184f4618ba'
RESOURCE_SHA256 = 'de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f'
CONFIG_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
LAYOUT_SHA256 = '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
PYTHON_SHA256 = '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
VENV_CONFIG_SHA256 = '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
BASE_PYTHON_SHA256 = 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
REPAIR_RELATIVE = 'src/cochem_pipeline/resource_telemetry.py'
REPAIR_SHA256 = 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
PREVIOUS_INSTALL_RECEIPT_SHA256 = '3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
PREVIOUS_MANIFEST_SHA256 = '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'
PRESERVED_DENIAL_SHA256 = '691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d'
AGY_SHA256 = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
AGY_VERSION = '1.3.1'

SLOTS = ('slot1',)  # the only slot that runs the model-form matrix
STAGE_SLOTS = ('slot1', 'slot2', 'slot3', 'slot4', 'slot5', 'slot6')
MODES = ('evidence', 'stage')
STAGE_ROOT_SUFFIX = '-stage'
RECEIPT_NAMES = {'evidence': 'isolation-receipt.json', 'stage': 'stage-receipt.json'}
DAEMON_TASK_NAMES = ('CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor',
                     'CoChem-4.2.2-Warden', 'CoChem-4.2.3-Supervisor')

# ----- the protected custom agent (manifest step 6 (a); conflicts_resolved 5) -----
AGENT_NAME = 'cochem-inference-only'
# Commander amendment 2026-10-11: 'hidden: true' removed (no isolation weight; it risked hiding the agent from
# every slot's `agy agents` listing, which the strict listing gate requires to show exactly this agent).
AGENT_SHA256 = '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'
AGENT_BYTES = 478
AGENT_MAX_BYTES = 4096
AGENT_FRONTMATTER = (
    ('name', AGENT_NAME), ('description', 'CoChem inference-only primary agent'), ('tools', '[]'),
    ('mainAgent', 'true'), ('subagent', 'false'), ('model', 'inherit'),
    ('commandExecutionPolicy', '"off"'), ('inheritCustomizations', 'false'), ('inheritMcp', 'false'),
    ('excludeDefaultComponents', 'true'), ('mcpServers', '[]'), ('skills', '[]'), ('plugins', '[]'),
    ('rules', '[]'), ('agents', '[]'))
# This host's live discovery location first, then the documented one (resolved fact 17).
AGENT_DESTINATION_PARTS = (('.gemini', 'agents', AGENT_NAME, 'agent.md'),
                           ('.gemini', 'config', 'agents', AGENT_NAME, 'agent.md'))
FULL_CONTROL = 0x1F01FF
WORKER_READ_FILE = 0x120089   # FILE_GENERIC_READ
WORKER_READ_DIRECTORY = 0x1200A9  # FILE_GENERIC_READ | FILE_TRAVERSE (list + traverse, no write)
AGENT_DIRECTORY_SDDL = 'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sid})'
AGENT_FILE_SDDL = 'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x120089;;;{sid})'
# O-F3 (stage mode): the PARENT folders .gemini/agents and .gemini/config/agents get the same grant (worker list and
# traverse only: no add-file, no add-subdirectory, no delete-child), so the leaf can be neither renamed away nor replaced.
AGENT_PARENT_DIRECTORY_SDDL = 'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sid})'
AGENT_PARENT_RELATIVES = ('.gemini/agents', '.gemini/config/agents')
# O-F2: agy reads %PROGRAMDATA%\Antigravity\admin_settings.json (enterprise gateway mode). G3 and G4 accept the folder
# only ABSENT or as exactly the protected empty folder the stage mode creates: SYSTEM-owned, SYSTEM/BA full control,
# BUILTIN\Users read and execute only (no write, no create), DACL protected from the ProgramData inheritance.
PROGRAMDATA_ANTIGRAVITY = Path(r'C:\ProgramData\Antigravity')
PROGRAMDATA_ANTIGRAVITY_SDDL = 'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
USERS_SID = 'S-1-5-32-545'
USERS_READ_EXECUTE = 0x1200A9
PROGRAMDATA_STATES = ('ABSENT', 'PROTECTED_EMPTY', 'NOT_EMPTY', 'WEAK_ACL', 'ACL_UNVERIFIABLE', 'NOT_DIRECTORY',
                      'REPARSE_POINT', 'UNREADABLE')
PROGRAMDATA_CLEAR_STATES = ('ABSENT', 'PROTECTED_EMPTY')
ENTRY_NAME_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._ -]{0,127}')
# O-F1: per-run Job accounting (JOBOBJECT_BASIC_ACCOUNTING_INFORMATION.TotalProcesses, read after the owned Job is
# terminated so the count is final). agy's own tree is agy.exe plus the console host Windows starts inside the same Job
# for a CREATE_NO_WINDOW console child; any further process (a hook, MCP server, plugin or tool) fails G3.
JOB_EXPECTED_PROCESSES_MAXIMUM = 2
MAX_SHADOW_ENTRIES = 256
MAX_PLUGINS = 64

# ----- inference transport (production argv; conflicts_resolved 6) -----
PROMPT = 'Reply with exactly: ready true'
PROMPT_LINE = b'{"event":"user","message":{"content":"Reply with exactly: ready true"}}\n'
PROMPT_LINE_SHA256 = hashlib.sha256(PROMPT_LINE).hexdigest()
EXPECTED_RESPONSE = 'ready true'
PRODUCTION_ARGUMENTS = ('--agent', AGENT_NAME, '--input-format', 'stream-json', '--output-format', 'stream-json',
                        '--model', '{model}', '--disable-slash-commands')
PRIMARY_MODEL = 'gemini-3.8-flash-high'
# The owner's pre-declared slug for the effort-null tier 1-3 binding of 'gemini-3.8-flash' (config
# builder rule): only the catalog's gemini-3.8-flash effort slugs are reviewed values.
EFFORT_NULL_SLUGS = ('gemini-3.8-flash-low', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-high')
DEFAULT_EFFORT_NULL_SLUG = 'gemini-3.8-flash-low'
RUN_IDS = ('R1', 'R5', 'R2', 'R3', 'R4')
MAX_MODEL_JOBS = len(RUN_IDS)


def run_matrix(effort_null_slug=DEFAULT_EFFORT_NULL_SLUG):
    """R5 runs right after R1 so the owner's binding evidence is kept if the deadline guard bites."""
    if effort_null_slug not in EFFORT_NULL_SLUGS:
        raise ValueError('The effort-null slug must be a reviewed gemini-3.8-flash catalog slug')
    return (
        ('R1', PRIMARY_MODEL, (), 'primary acceptance: catalog slug, identity init.model == slug'),
        ('R5', effort_null_slug, (), "owner's effort-null slug: binds tier 1-3 'gemini-3.8-flash' (effort null) only if it passes"),
        ('R2', PRIMARY_MODEL, ('--effort', 'high'), 'slug with --effort: is the effort_contracts selector form accepted with a slug'),
        ('R3', 'gemini-3.8-flash', ('--effort', 'high'), 'family id with --effort: accepted, and which init.model is echoed'),
        ('R4', 'gemini-3.1-pro-preview', (), 'expected rejection: unknown-model exit code, ERROR envelope and AGY_ERROR shape'),
    )


RUNS = run_matrix()
FORBIDDEN_FLAGS = frozenset(('-p', '--print', '--prompt', '-i', '--prompt-interactive', '-c', '--continue',
                             '--conversation', '--dangerously-skip-permissions', '--print-timeout', '--project',
                             '--new-project', '--log-file', '--json-schema', '--mode', '--sandbox', '--add-dir',
                             '--remote-control'))
RUN_SECONDS = 120
RUN_OUTPUT = 1024 * 1024
# Manifest markers plus the two the cli design's identity contract adds; any one fails R1.
STDERR_MARKERS = ('AGY_ERROR:', 'is no longer available. Using', 'Model resolved via', 'Restored session model',
                  'resolves to a different model', 'defaulting to')
REROUTE_KEY_FRAGMENTS = ('reroute', 'fallback', 'deprecat', 'resolved', 'substitut', 'downgrad')
# RG-2: agy 1.3.x writes model resolution as INFO lines to ~/.gemini/antigravity-cli/log/cli-*.log, not stderr. Only the
# log files a run created are read (bounded, never published); only the true fallback phrases clear reroute_scan_clean.
# agy's normal resolution path is counted, never flagged.
LOG_FALLBACK_PHRASES = ('is no longer available. Using', 'Restored session model', 'resolves to a different model',
                        'Restoring model')
LOG_BENIGN_PHRASES = ('Model resolved via default', 'not in local config, defaulting to CCPA')
LOG_PATH_PATTERN = re.compile(r'\.gemini/antigravity-cli/log/cli-[^/]{1,200}\.log')
LOG_SCAN_MAXIMUM = 1024 * 1024
LOG_SCAN_FILES = 8
ERROR_TEMPLATES = (
    ('model_conflicts_with_effort', re.compile(r'--model \S+ conflicts with --effort=\S+')),
    ('model_requires_effort', re.compile(r'--model \S+ requires --effort \(available: [^)]*\)')),
    ('invalid_model_selection', re.compile(r'invalid model selection \(--model "[^"]*" --effort "[^"]*"\)')),
    ('effort_not_supported_for_model', re.compile(r'--effort is not supported for model "[^"]*"')),
    ('effort_not_supported_current_model', re.compile(r'--effort is not supported for the current model')),
    ('invalid_effort', re.compile(r'[Ii]nvalid (?:--)?effort "[^"]*" \(valid: [^)]*\)')),
    ('invalid_model', re.compile(r'Invalid model "[^"]*" \(available: [^)]*\)')),
    ('unknown_model', re.compile(r'unknown model "[^"]*"')),
    ('model_not_found', re.compile(r'Model \S+ not found in available models')),
    ('resolve_model_failed', re.compile(r'Failed to resolve model flag "[^"]*"')),
    ('no_model_configuration', re.compile(r'no model configuration is available for this account')),
    ('agent_model_invalid', re.compile(r'agent: model must be inherit, flash_lite, flash, or pro')),
    ('authentication_required', re.compile(r'authentication required')),
)

# ----- non-inference pre-check under the worker token -----
PRECHECK = (('PC1', ('--version',), 'version'), ('PC2', ('--output-format', 'json', 'models'), 'models_json'),
            ('PC3', ('--output-format', 'json', 'agents'), 'agents_json'), ('PC4', ('agents',), 'agents_text'))
# The listing gate of the stage mode: the same two agent probes under every worker token.
STAGE_PROBES = PRECHECK[2:]
PROBE_SECONDS = 30
PROBE_OUTPUT = 65536
SIGN_IN_PREDICATE_TEXT = 'Please sign in to view available models'
AUTH_REQUIRED_TEXT = 'authentication required'
NOT_LOGGED_IN_LINE = 'You are not logged into Antigravity.'
FETCHING_LINE = 'Fetching available models...'

# ----- bounds -----
POLL_SECONDS = 0.05
RAW_FILE_MAXIMUM = 16 * 1024 * 1024
# Task ExecutionTimeLimit PT10M (600 s). A launch starts only while its worst case still fits before
# this helper deadline: the launch-boundary require_stopped (PowerShell, 45 s timeout) plus the launch
# delay and profile load (LAUNCH_OVERHEAD_SECONDS), the bound, and the Job close/unload allowance.
# After the deadline the post-loop work (inventory, agy re-hash, require_stopped <= 45 s, receipt)
# still fits: 480 + 45 + 30 < 600, so the receipt is always written.
DEADLINE_SECONDS = 480
LAUNCH_OVERHEAD_SECONDS = 60
CLEANUP_MARGIN_SECONDS = 25
TASK_LIMIT_SECONDS = 600
POST_LOOP_SECONDS = 75
INVENTORY_HASH_LIMIT = 1024 * 1024
MAX_TREE_ENTRIES = 400
PROFILE_PATH_MAX_ENTRIES = 64
MAX_TREE_DEPTH = 16
MAX_STREAM_LINES = 32768
MAX_KEY_SCAN = 4096
RECEIPT_MAX_BYTES = 1024 * 1024
SLOT1_TREES = (('.gemini', ('.gemini',)), ('AppData/Local/agy', ('AppData', 'Local', 'agy')))

# ----- six-profile inventory (manifest (b)); antigravity-cli plugins/skills are the documented CLI locations -----
# O-F1: every customization location agy 1.3.1 documents. Per user: ~/.gemini/config/{config.json (it can enable
# plugins), skills.json, plugins.json}. Per workspace: the folders .agents/ (or .agent/, _agents/, _agent/) with
# hooks.json, mcp_config.json, skills/ and agents/, plus the declared skills.json and plugins.json, in the cwd AND every
# ancestor directory up to the drive root (agy walks upward from its working directory).
PROFILE_PATHS = (
    '.gemini/config/hooks.json', '.gemini/config/mcp_config.json', '.gemini/config/settings.json',
    '.gemini/config/plugins', '.gemini/config/skills', '.gemini/config/agents', '.gemini/config/rules',
    '.gemini/config/workflows', '.gemini/agents', '.gemini/.agents',
    '.gemini/antigravity-cli/hooks.json', '.gemini/antigravity-cli/settings.json', '.gemini/antigravity-cli/mcp',
    '.gemini/antigravity-cli/plugin_data', '.gemini/antigravity-cli/cache', '.gemini/antigravity-cli/updater',
    '.gemini/antigravity-cli/antigravity-oauth-token', '.gemini/antigravity-cli/plugins',
    '.gemini/antigravity-cli/skills', 'AppData/Local/agy/bin', '.gemini/config/sidecars',
    '.gemini/config/config.json', '.gemini/config/skills.json', '.gemini/config/plugins.json')
WORKSPACE_DIRS = ('.agents', '.agent', '_agents', '_agent')
WORKSPACE_ITEMS = ('hooks.json', 'mcp_config.json', 'skills', 'agents')
WORKSPACE_PATHS = (*(folder + '/' + item for folder in WORKSPACE_DIRS for item in WORKSPACE_ITEMS), 'skills.json', 'plugins.json')
WORKSPACE_HOOK_PATHS = tuple(folder + '/hooks.json' for folder in WORKSPACE_DIRS)
WORKSPACE_MCP_PATHS = tuple(folder + '/mcp_config.json' for folder in WORKSPACE_DIRS)
WORKSPACE_SKILL_PATHS = (*(folder + '/skills' for folder in WORKSPACE_DIRS), 'skills.json')
WORKSPACE_PLUGIN_PATHS = ('plugins.json',)
# RG-3: agy starts background sidecars from <config>/sidecars/ (hooks class: an empty folder is absent, any entry present).
HOOK_PATHS = ('.gemini/config/hooks.json', '.gemini/antigravity-cli/hooks.json', '.gemini/antigravity-cli/settings.json',
              '.gemini/config/sidecars')
MCP_PATHS = ('.gemini/config/mcp_config.json', '.gemini/antigravity-cli/mcp')
PLUGIN_PATHS = ('.gemini/config/plugins', '.gemini/antigravity-cli/plugins', '.gemini/antigravity-cli/plugin_data',
                '.gemini/config/plugins.json', '.gemini/config/config.json')
SKILL_PATHS = ('.gemini/config/skills', '.gemini/antigravity-cli/skills', '.gemini/config/skills.json')
# Commander rule (agy's sign-in may write ~/.gemini/config/config.json): the three declared user configurations are
# inspected, not flagged for existing. Strict JSON (UTF-8, a leading UTF-8 BOM is stripped and the rest inspected, no
# duplicate key, no NaN/Infinity), at most 256 KiB and 64 levels deep, a top-level object; FLAGGED otherwise, or when
# any key at any depth whose casefolded name contains plugin, mcp, hook, skill, agent or sidecar has a non-empty value (a
# non-empty object, array or string, or true). Only key NAMES are recorded, never values. Workspace files stay
# 'present = flagged'.
DECLARED_CONFIG_PATHS = ('.gemini/config/config.json', '.gemini/config/skills.json', '.gemini/config/plugins.json')
DECLARED_CONFIG_MAXIMUM = 256 * 1024
DECLARED_CONFIG_DEPTH = 64
DECLARED_CONFIG_FRAGMENTS = ('plugin', 'mcp', 'hook', 'skill', 'agent', 'sidecar')
DECLARED_CONFIG_REASONS = ('CUSTOMIZATION_KEYS', 'NOT_A_REGULAR_FILE', 'HARDLINKED', 'UNREADABLE', 'OVER_SIZE_BOUND',
                           'CHANGED_DURING_INSPECTION', 'NOT_UTF8', 'TOO_DEEP', 'DUPLICATE_KEY', 'UNPARSEABLE', 'NOT_AN_OBJECT')
CONFIG_KEY_PATTERN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}')
PROFILE_CONFIG_REASON_PREFIX = 'PROFILE_CONFIG_FLAGGED:'
ENV_NAME_PATTERN = re.compile(r'^(AGY_|ANTIGRAVITY_|XDG_|GEMINI_|GOOGLE_|CLOUDSDK_|GCLOUD_|CODEX_HOME$|CLAUDE_CONFIG_DIR$)')
PROFILE_BINDING_KEYS = ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')

# ----- allowlists -----
ANSI_PATTERN = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]')
MODEL_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}')
AGENT_NAME_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
TOOL_NAME_PATTERN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}')
KEY_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
SAFE_TEXT_PATTERN = re.compile(r'[\x20-\x7e]{1,600}')
UNSAFE_TEXT_PATTERN = re.compile(r'(?i)@|https?://|bearer|secret|password|passwd|api[_-]?key|oauth|refresh_token|access_token')
STATUS_VALUES = ('SUCCESS', 'ERROR', 'CANCELED', 'INTERRUPTED', 'INVALID', 'WAITING', 'RUNNING')
STEP_TYPES = ('user_input', 'agent_response', 'tool', 'checkpoint')
ALLOWED_STEP_TYPES = ('user_input', 'agent_response', 'checkpoint')
PERMISSION_MODES = ('request-review', 'proceed-in-sandbox', 'always-proceed', 'strict')
USAGE_KEYS = ('input_tokens', 'output_tokens', 'thinking_tokens', 'cache_read_tokens', 'total_tokens')
MAX_LISTED = 64
FAILURE_PHASES = ('trusted_preflight', 'reservation', 'runtime_custody', 'layout', 'boundaries', 'native_custody',
                  'daemon_precheck', 'inventory_before', 'agent_staging', 'profile_inventory',
                  'environment_attestation', 'agent_verification', 'precheck_launch', 'native_attestation',
                  'precheck_wait', 'precheck_result', 'inference_launch', 'inference_wait', 'native_cleanup',
                  'inference_result', 'replay', 'stage_listing', 'inventory_after', 'daemon_postcheck', 'verdict',
                  'programdata_guard')
LAUNCH_PHASES = ('precheck_launch', 'inference_launch', 'stage_listing')
STATUSES = ('EVIDENCE_COMPLETE', 'EVIDENCE_PRECHECK_REFUSED', 'EVIDENCE_INCOMPLETE', 'EVIDENCE_FAILED')
STAGE_STATUSES = ('STAGING_COMPLETE', 'STAGING_INCOMPLETE', 'STAGING_FAILED')
PASSING_STATUSES = ('EVIDENCE_COMPLETE', 'EVIDENCE_PRECHECK_REFUSED', 'STAGING_COMPLETE')
RUN_CHECK_REASONS = (('exited_zero', 'R1_EXIT_NOT_ZERO'), ('init_present', 'R1_INIT_MISSING'),
                     ('stream_well_formed', 'R1_STREAM_MALFORMED'), ('tools_empty', 'R1_TOOLS_NOT_EMPTY'),
                     ('agent_matches', 'R1_AGENT_MISMATCH'), ('model_matches', 'R1_MODEL_MISMATCH'),
                     ('no_tool_steps', 'R1_TOOL_STEPS'), ('no_subagent_steps', 'R1_SUBAGENT_STEPS'),
                     ('only_allowed_step_types', 'R1_UNEXPECTED_STEP_TYPES'), ('step_models_match', 'R1_STEP_MODEL_MISMATCH'),
                     ('result_success', 'R1_RESULT_NOT_SUCCESS'), ('num_turns_one', 'R1_NUM_TURNS_NOT_ONE'),
                     ('result_model_absent_or_equal', 'R1_RESULT_MODEL_MISMATCH'), ('no_stderr_markers', 'R1_STDERR_MARKERS'))
# Checks a run may fail and still prove its echoed identity (R3: the family id form reports a slug).
ECHO_EXEMPT_CHECKS = ('model_matches', 'step_models_match', 'result_model_absent_or_equal')
REASONS = ('EVIDENCE_NOT_COMPLETE', 'PRECHECK_VERSION_MISMATCH', 'PRECHECK_NOT_SIGNED_IN', 'AGENTS_PRECHECK_FAILED',
           'AGENT_SHADOW_FOUND', 'R1_NOT_RUN', *[reason for _, reason in RUN_CHECK_REASONS], 'ISOLATION_BREACH_IN_MATRIX',
           'JOB_PROCESSES_BEYOND_AGY_TREE', 'MODEL_FALLBACK_LOGGED', 'MODEL_LOG_SCAN_INCOMPLETE', 'PROFILE_INVENTORY_NOT_CLEAR', 'PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR')
STAGE_REASONS = ('STAGING_NOT_COMPLETE', 'SLOT_NOT_PROCESSED', 'AGENT_NOT_STAGED_AT_BOTH_LOCATIONS', 'AGENT_SHADOW_FOUND',
                 'AGENTS_JSON_LISTING_FAILED', 'AGENTS_TEXT_LISTING_FAILED')

# ----- raw-stream secret scan and the redacted replay copy (config-builder gate G5) -----
# Raw streams stay SYSTEM/BA-only and never-publish. The replay copy the builder reads has every
# account- or credential-looking span replaced; the receipt records only the pattern NAMES and counts.
# URLs first (they can carry userinfo, codes or tokens), then e-mail addresses, then token shapes.
SENSITIVE_PATTERNS = (
    ('url', re.compile(rb'(?i)https?://[^\s"\'<>\\]{1,4096}'), b'REDACTED_URL'),
    ('email', re.compile(rb'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+'), b'REDACTED_EMAIL'),
    ('google_access_token', re.compile(rb'ya29\.[A-Za-z0-9._-]{8,}'), b'REDACTED_TOKEN'),
    ('google_refresh_token', re.compile(rb'1//0[A-Za-z0-9._-]{8,}'), b'REDACTED_TOKEN'),
    ('authorization_code', re.compile(rb'4/0[A-Za-z0-9._-]{8,}'), b'REDACTED_TOKEN'),
    ('jwt', re.compile(rb'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'), b'REDACTED_TOKEN'),
    ('bearer', re.compile(rb'(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}'), b'REDACTED_TOKEN'),
    ('secret_field', re.compile(rb'(?i)(access_token|refresh_token|id_token|client_secret|api[_-]?key|password)'
                                rb'(["\']?\s*[:=]\s*["\']?)(?!REDACTED_)[^"\'\s,}]{1,4096}'), rb'\1\2REDACTED_VALUE'),
)
SENSITIVE_NAMES = tuple(name for name, _, _ in SENSITIVE_PATTERNS)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError('Nonfinite JSON value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def digest_file(path, maximum=1024 * 1024 * 1024):
    before = path.stat()
    if before.st_size > maximum:
        raise ValueError('Reviewed file exceeds its size bound')
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > maximum:
                raise ValueError('Reviewed file grew beyond its size bound')
            digest.update(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Reviewed file changed during hash capture')
    return digest.hexdigest()


def protected_json(win, path):
    win.validate_code_path(path)
    from cochem_pipeline.ramdisk import ordinary_tree
    ordinary_tree(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Protected configuration exceeds its byte bound')
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError('Protected configuration exceeds its byte bound')
    value = strict_json(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Protected configuration requires an object')
    return value, hashlib.sha256(raw).hexdigest()


def current_executable():
    return Path(sys.executable).resolve()


def validate_interpreter():
    if (current_executable() != PYTHON or Path(sys.base_prefix).resolve() != BASE_PYTHON.parent
            or Path(sys._base_executable).resolve() != BASE_PYTHON
            or sys.version_info[:3] != (3, 12, 13) or not sys.flags.isolated or not sys.dont_write_bytecode
            or digest_file(INSTALL / '.venv' / 'pyvenv.cfg') != VENV_CONFIG_SHA256):
        raise ValueError('Protected isolated interpreter binding changed')


def verify_r4_source(value, read):
    if (value.get('schema') != 'cochem-stopped-runtime-source/1' or value.get('target_root') != str(INSTALL)
            or value.get('complete_source_freeze') is not True or not isinstance(value.get('files'), list)
            or len(value['files']) != 166
            or value.get('changes_from_previous_source') != {'added': [], 'removed': [], 'changed': [REPAIR_RELATIVE]}):
        raise ValueError('Frozen r4 source inventory differs')
    seen = set()
    for row in value['files']:
        key = row.get('relative')
        if (not isinstance(key, str) or '\\' in key or ':' in key or key.startswith('/')
                or any(part in ('', '.', '..') for part in key.split('/')) or key.casefold() in seen
                or not (key.startswith('src/') or key in ('README.md', 'pyproject.toml', 'uv.lock'))
                or not re.fullmatch('[a-f0-9]{64}', str(row.get('sha256')))
                or type(row.get('length')) is not int or not 0 <= row['length'] <= 16777216):
            raise ValueError('Unsafe frozen r4 source record')
        if key == REPAIR_RELATIVE and row['sha256'] != REPAIR_SHA256:
            raise ValueError('Frozen r4 repair differs from its pin')
        seen.add(key.casefold())
        read(INSTALL / 'source' / key, row['sha256'], row['length'])
    if not {'pyproject.toml', 'uv.lock', 'readme.md', REPAIR_RELATIVE} <= seen:
        raise ValueError('Project controls missing from r4 manifest')


def verified_source(win, path, pin, length):
    win.validate_code_path(path)
    if path.stat().st_size != length or digest_file(path) != pin:
        raise ValueError('Frozen source bytes differ')


def check_install_after(installed):
    """The r4 install-after.json bindings, with the real key names printed on disk."""
    expected = {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY',
                'target_root': str(INSTALL), 'previous_runtime_root': str(PREVIOUS_INSTALL),
                'previous_install_receipt_sha256': PREVIOUS_INSTALL_RECEIPT_SHA256,
                'previous_source_manifest_sha256': PREVIOUS_MANIFEST_SHA256,
                'source_manifest_sha256': MANIFEST_SHA256, 'source_files': 166,
                'reviewed_repair': REPAIR_RELATIVE, 'reviewed_repair_sha256': REPAIR_SHA256,
                'configuration_sha256': CONFIG_SHA256, 'configuration_unchanged': True, 'only_config_change': None,
                'preserved_denial_receipt_sha256': PRESERVED_DENIAL_SHA256,
                'preserved_denial_task_terminal_check_deferred': False, 'preserved_worker_cleanup_verified': False,
                'accounts_provisioned': 0, 'tasks_changed': 0, 'credentials_modified': False,
                'databases_modified': False, 'ram_modified': False, 'pipeline_started': False,
                'activation_ready': False}
    if any(type(installed.get(k)) is not type(v) or installed.get(k) != v for k, v in expected.items()) or installed.get('holds') != []:
        raise ValueError('Complete stopped r4 installation binding missing')
    verification = installed.get('verification')
    bindings = installed.get('runtime_bindings')
    if (not isinstance(verification, dict) or verification.get('configuration_parsed') is not True
            or verification.get('telemetry_repair_installed') is not True
            or verification.get('no_system_or_model_execution') is not True
            or not isinstance(bindings, dict) or bindings.get('pyvenv_sha256') != VENV_CONFIG_SHA256
            or bindings.get('venv_python_sha256') != PYTHON_SHA256 or bindings.get('base_python_sha256') != BASE_PYTHON_SHA256
            or bindings.get('base_root') != str(BASE_PYTHON.parent)
            or not isinstance(verification.get('revision'), dict)
            or verification['revision'].get('source_sha256') != REVISION_SHA256):
        raise ValueError('r4 verification/runtime binding differs')
    return verification


def verify_r4_runtime(win, install_receipt_sha256=INSTALL_RECEIPT_SHA256):
    """Bind the reviewed r4 stopped runtime before comparing the installed package revision."""
    from cochem_pipeline.deployment_revision import verify_installed_revision
    from cochem_pipeline import resource_limits
    for pin in (RESOURCE_SHA256, MANIFEST_SHA256, install_receipt_sha256, VENV_CONFIG_SHA256, REVISION_SHA256, REPAIR_SHA256):
        if not re.fullmatch('[a-f0-9]{64}', pin):
            raise ValueError('Actual reviewed r4 bindings are not frozen')
    if (Path(sys.base_prefix).resolve() != BASE_PYTHON.parent or Path(sys._base_executable).resolve() != BASE_PYTHON
            or sys.version_info[:3] != (3, 12, 13) or not sys.flags.isolated or not sys.dont_write_bytecode):
        raise ValueError('Exact isolated protected Python binding differs')
    site = INSTALL / '.venv' / 'Lib' / 'site-packages'
    for path, pin in ((PYTHON, PYTHON_SHA256), (INSTALL / '.venv' / 'pyvenv.cfg', VENV_CONFIG_SHA256),
                      (Path(resource_limits.__file__), RESOURCE_SHA256), (BASE_PYTHON, BASE_PYTHON_SHA256),
                      (site / 'cochem_pipeline' / 'resource_telemetry.py', REPAIR_SHA256)):
        win.validate_code_path(path)
        if digest_file(path) != pin:
            raise ValueError('Pinned r4 runtime control differs')
    installed, digest = protected_json(win, INSTALL / 'install-after.json')
    if digest != install_receipt_sha256:
        raise ValueError('Actual r4 receipt pin differs')
    verification = check_install_after(installed)
    manifest, digest = protected_json(win, INSTALL / 'source-manifest.json')
    if digest != MANIFEST_SHA256:
        raise ValueError('Frozen r4 manifest pin differs')
    verify_r4_source(manifest, lambda path, pin, length: verified_source(win, path, pin, length))
    revision = verify_installed_revision(INSTALL / 'source', site, INSTALL / 'source')
    if (revision.get('verified') is not True or revision.get('files') != 109
            or revision.get('source_sha256') != REVISION_SHA256
            or revision != verification.get('revision')):
        raise ValueError('Actual installed r4 revision differs from pinned receipt/source')
    return revision


def require_stopped(win):
    # Do not alter tasks, accept unknown scheduler errors, or inspect legacy tasks.
    win._powershell(r"""
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\');
        foreach ($name in $data) {
            $task=$null;
            try {$task=$folder.GetTask($name)} catch {
                $missing=$false;$exception=$_.Exception;
                while ($null -ne $exception) {if ($exception.HResult -eq -2147024894) {$missing=$true;break};$exception=$exception.InnerException}
                if (-not $missing) {throw 'Cannot establish task state.'}
            }
            if ($null -ne $task -and ($task.Enabled -or $task.State -notin @(1,3) -or $task.GetInstances(0).Count -ne 0)) {throw 'Protected daemons must remain stopped and disabled.'}
        }
    """, list(DAEMON_TASK_NAMES))


def launch_native_process(win, identity, argv, cwd, stdin, output, errors, limits):
    # Recheck the four daemon task names at every launch boundary. No task is changed here.
    require_stopped(win)
    return win.launch_worker(identity, argv, cwd, stdin, output, errors, limits=limits)


def native_device_path(win, path):
    """NT device form of a local drive path (QueryDosDeviceW), used only after the child exited."""
    text = str(path)
    if not re.fullmatch(r'[A-Za-z]:\\.+', text):
        raise ValueError('Native executable path must be a local drive path')
    query = win._api()['kernel32'].QueryDosDeviceW
    query.argtypes = [win.LPWSTR, win.LPWSTR, win.DWORD]
    query.restype = win.DWORD
    buffer = C.create_unicode_buffer(1024)
    win._check(query(text[:2], buffer, 1024), 'Resolve executable drive device')
    return buffer.value + text[2:]


EXIT_SETTLE_MILLISECONDS = 5000


def attest_image(query_image, wait_exited, executable, device_path):
    """Image attestation with the exit fallback for any query failure.

    query_image(flags) -> str | None (None: the query failed); wait_exited(ms) -> bool (the owned
    handle is signaled). A fast child can fail the Win32-form query with ERROR_ACCESS_DENIED (5)
    during its ~0.4 ms teardown before the handle is signaled, and with ERROR_GEN_FAILURE (31) after
    exit; either way a bounded wait on the owned handle decides: signaled -> the native (device) form
    is compared, not signaled -> the attestation fails closed.
    """
    image = query_image(0)
    if image is not None:
        if Path(image).resolve() != executable.resolve():
            raise ValueError('Observed native process image differs from the reviewed executable')
        return 'win32'
    if not wait_exited(EXIT_SETTLE_MILLISECONDS):
        raise ValueError('Observe native process image failed')
    image = query_image(1)
    if image is None:
        raise ValueError('Observe exited native process image failed')
    if image.casefold() != device_path().casefold():
        raise ValueError('Observed native process image differs from the reviewed executable')
    return 'native_after_exit'


def observe_child(win, process, expected_sid, executable):
    """Observe the actual child token/image/job through the owned process handle (status-capture body)."""
    api = win._api()
    token = win.HANDLE()
    win._check(api['advapi32'].OpenProcessToken(process._process, 0x8, C.byref(token)), 'Open owned native process token')
    try:
        user = win._SID_AND_ATTRIBUTES.from_buffer(win._token_info(token, 1))
        sid = win._sid_text(user.Sid)
        if sid != expected_sid or sid in {win.SYSTEM_SID, win.ADMIN_SID}:
            raise ValueError('Observed native process has the wrong identity')
        count = win.DWORD()
        api['userenv'].GetUserProfileDirectoryW(token, None, C.byref(count))
        if not 1 <= count.value <= 32768:
            raise ValueError('Observed profile path has an invalid bound')
        profile = C.create_unicode_buffer(count.value)
        win._check(api['userenv'].GetUserProfileDirectoryW(token, profile, C.byref(count)), 'Observe worker token profile')
        query = api['kernel32'].QueryFullProcessImageNameW
        query.argtypes = [win.HANDLE, win.DWORD, win.LPWSTR, C.POINTER(win.DWORD)]
        query.restype = win.BOOL

        def query_image(flags):
            size = win.DWORD(32768)
            image = C.create_unicode_buffer(size.value)
            return image.value if query(process._process, flags, image, C.byref(size)) else None

        def wait_exited(milliseconds):
            # WAIT_OBJECT_0 on the owned handle; WAIT_TIMEOUT or WAIT_FAILED fail the attestation.
            return api['kernel32'].WaitForSingleObject(process._process, milliseconds) == 0

        image_format = attest_image(query_image, wait_exited, executable,
                                    lambda: native_device_path(win, executable.resolve()))
        in_job = win.BOOL()
        check_job = api['kernel32'].IsProcessInJob
        check_job.argtypes = [win.HANDLE, win.HANDLE, C.POINTER(win.BOOL)]
        check_job.restype = win.BOOL
        win._check(check_job(process._process, process._job, C.byref(in_job)), 'Observe owned Job membership')
        if not in_job.value:
            raise ValueError('Native process is not in its owned Job Object')
        return {'pid': process.pid, 'creation_time_filetime': process.creation_time_filetime,
                'token_sid': sid, 'token_matches_selected_worker': True,
                'image_matches_reviewed_executable': True, 'owned_job_membership_verified': True,
                'image_query_format': image_format,
                'profile_directory_sha256': hashlib.sha256(profile.value.casefold().encode()).hexdigest(),
                'source': 'owned_windows_process_handle_and_child_token'}
    finally:
        win._close(token)


def wait_bounded(process, output, errors, seconds, limit):
    """Record instead of raising: a bound reached ends the child through its owned Job on block exit."""
    deadline = time.monotonic() + seconds
    while True:
        if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > limit:
            return 'output_bound_terminated', None
        code = process.poll()
        if code is not None:
            return 'exited', code
        if time.monotonic() >= deadline:
            return 'timed_out_terminated', None
        time.sleep(POLL_SECONDS)


def safe_failure(error, phase):
    kind = re.sub('[^A-Za-z0-9_]', '', type(error).__name__)[:80] or 'Exception'
    code, current = None, error
    for _ in range(5):
        value = getattr(current, 'winerror', None)
        if type(value) is int and 0 <= value <= 0xFFFFFFFF:
            code = value
            break
        current = current.__cause__ or current.__context__
        if current is None:
            break
    return {'phase': phase if phase in FAILURE_PHASES else 'trusted_preflight', 'error_type': kind, 'winerror': code}


# ----- text helpers (raw text never leaves these functions except as sanitized error strings) -----

def strip_ansi(text):
    return ANSI_PATTERN.sub('', text)


def allow(value, allowed):
    if not isinstance(value, str):
        return None
    return value if value in allowed else 'OTHER'


def allowed_name(value, pattern):
    if not isinstance(value, str):
        return None
    return value if pattern.fullmatch(value) else 'OTHER'


def sanitized_text(value):
    """A printable error string without account, URL or credential-looking content, else withheld."""
    if not isinstance(value, str):
        return None, ('not_string' if value is not None else None)
    text = strip_ansi(value).strip()
    if not text:
        return None, 'empty'
    if not SAFE_TEXT_PATTERN.fullmatch(text):
        return None, 'unsafe_characters_or_length'
    if UNSAFE_TEXT_PATTERN.search(text):
        return None, 'unsafe_content'
    return text, None


def error_templates(*texts):
    found = set()
    for text in texts:
        if isinstance(text, str):
            for name, pattern in ERROR_TEMPLATES:
                if pattern.search(text):
                    found.add(name)
    return sorted(found)


def key_names(mapping):
    names = [key for key in mapping if isinstance(key, str) and KEY_PATTERN.fullmatch(key)]
    return sorted(names)[:MAX_LISTED]


def reroute_keys(events):
    """Names of keys anywhere in the stream that look like reroute/fallback signals (names only)."""
    found, stack, seen = set(), [(event, 0) for event in events], 0
    while stack and seen < MAX_KEY_SCAN:
        value, depth = stack.pop()
        if depth > 32:
            continue
        if isinstance(value, dict):
            for key, child in value.items():
                seen += 1
                if isinstance(key, str) and any(fragment in key.casefold() for fragment in REROUTE_KEY_FRAGMENTS):
                    found.add(key if KEY_PATTERN.fullmatch(key) else 'OTHER')
                stack.append((child, depth + 1))
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value[:MAX_KEY_SCAN])
    return sorted(found)[:MAX_LISTED]


# ----- stream-json classification -----

def parse_stream_events(text, requested):
    """Bounded NDJSON parse: malformed lines are counted, never echoed. Returns (summary, private)."""
    lines = [line for line in text.split('\n') if line.strip()]
    truncated = len(lines) > MAX_STREAM_LINES
    lines = lines[:MAX_STREAM_LINES]
    events, malformed, non_object = [], 0, 0
    for line in lines:
        try:
            value = strict_json(line)
        except (ValueError, TypeError, RecursionError):
            malformed += 1
            continue
        if not isinstance(value, dict):
            non_object += 1
            continue
        events.append(value)
    counts = {'init': 0, 'step_update': 0, 'result': 0, 'other': 0}
    for event in events:
        kind = event.get('event')
        counts[kind if kind in ('init', 'step_update', 'result') else 'other'] += 1
    init_event = next((event for event in events if event.get('event') == 'init'), None)
    result_event = next((event for event in reversed(events) if event.get('event') == 'result'), None)
    init = init_event.get('init') if init_event is not None else None
    session = init_event.get('conversation_id') if init_event is not None else None
    session_ok = isinstance(session, str) and 0 < len(session.strip()) <= 512
    summary = {'lines': len(lines), 'lines_truncated': truncated, 'malformed_lines': malformed,
               'non_object_lines': non_object, 'events': counts,
               'first_event_init': bool(events) and events[0].get('event') == 'init',
               'last_event_result': bool(events) and events[-1].get('event') == 'result',
               'conversation_id_present': session_ok, 'conversation_ids_consistent': False,
               'event_keys': key_names({key: None for event in events for key in event}),
               'reroute_keys': reroute_keys(events), 'init_present': isinstance(init, dict), 'init': None,
               'steps': None, 'result_present': False, 'result': None}
    private = {'error': None}
    if isinstance(init, dict):
        tools = init.get('tools')
        listed = [name for name in tools if isinstance(name, str) and TOOL_NAME_PATTERN.fullmatch(name)] if isinstance(tools, list) else []
        cwd = init.get('cwd')
        summary['init'] = {
            'keys': key_names(init), 'tools_is_list': isinstance(tools, list),
            'tools_count': len(tools) if isinstance(tools, list) else None,
            'tools': listed[:MAX_LISTED],
            'tools_unlisted': (len(tools) - len(listed[:MAX_LISTED])) if isinstance(tools, list) else 0,
            'model_present': 'model' in init, 'model': allowed_name(init.get('model'), MODEL_PATTERN),
            'agent_present': 'agent' in init, 'agent': allowed_name(init.get('agent'), AGENT_NAME_PATTERN),
            'permission_mode': allow(init.get('permission_mode'), PERMISSION_MODES),
            'cwd_present': isinstance(cwd, str),
            'cwd_sha256': hashlib.sha256(cwd.casefold().encode('utf-8', 'replace')).hexdigest() if isinstance(cwd, str) else None}
    sessions_ok = session_ok
    init_model_raw = init.get('model') if isinstance(init, dict) else None
    step_types = {name: 0 for name in (*STEP_TYPES, 'OTHER')}
    steps = {'count': 0, 'step_types': step_types, 'tool_name_count': 0, 'tool_info_count': 0, 'subagent_info_count': 0,
             'step_type_tool_count': 0, 'disallowed_step_type_count': 0, 'model_field_count': 0, 'model_mismatch_count': 0,
             'model_init_mismatch_count': 0, 'tool_names': [], 'keys': []}
    step_keys, tool_names = set(), []
    for event in events:
        if event.get('event') != 'step_update':
            continue
        step = event.get('step_update')
        steps['count'] += 1
        if not isinstance(step, dict):
            step_types['OTHER'] += 1
            steps['disallowed_step_type_count'] += 1
            sessions_ok = False
            continue
        step_keys.update(key for key in step if isinstance(key, str))
        kind = step.get('step_type')
        step_types[kind if kind in STEP_TYPES else 'OTHER'] += 1
        if kind not in ALLOWED_STEP_TYPES:
            steps['disallowed_step_type_count'] += 1
        if kind == 'tool':
            steps['step_type_tool_count'] += 1
        if 'tool_name' in step:
            steps['tool_name_count'] += 1
            name = step.get('tool_name')
            if isinstance(name, str) and TOOL_NAME_PATTERN.fullmatch(name) and name not in tool_names:
                tool_names.append(name)
        if 'tool_info' in step:
            steps['tool_info_count'] += 1
        if 'subagent_info' in step:
            steps['subagent_info_count'] += 1
        if 'model' in step:
            steps['model_field_count'] += 1
            if step.get('model') != requested:
                steps['model_mismatch_count'] += 1
            if step.get('model') != init_model_raw:
                steps['model_init_mismatch_count'] += 1
        if step.get('conversation_id') != session:
            sessions_ok = False
    steps['tool_names'] = tool_names[:MAX_LISTED]
    steps['keys'] = key_names({key: None for key in step_keys})
    summary['steps'] = steps
    result = result_event.get('result') if result_event is not None else None
    if isinstance(result, dict):
        summary['result_present'] = True
        response = result.get('response')
        error = result.get('error')
        if isinstance(error, str) or error in (None, '', {}, []):
            error_source = error if isinstance(error, str) else None
        else:
            error_source = json.dumps(error, sort_keys=True, separators=(',', ':'))
        error_text, withheld = sanitized_text(error_source)
        usage = result.get('usage') if isinstance(result.get('usage'), dict) else {}
        num_turns = result.get('num_turns')
        summary['result'] = {
            'keys': key_names(result), 'status': allow(result.get('status'), STATUS_VALUES),
            'num_turns': num_turns if type(num_turns) is int and 0 <= num_turns <= 1000000 else None,
            'usage': {key: (usage.get(key) if type(usage.get(key)) is int and 0 <= usage.get(key) < 2 ** 53 else None) for key in USAGE_KEYS},
            'error_present': error not in (None, '', {}, []), 'error_text': error_text, 'error_withheld_reason': withheld,
            'response_present': isinstance(response, str) and bool(response.strip()),
            'response_bytes': len(response.encode('utf-8')) if isinstance(response, str) else None,
            'response_sha256': hashlib.sha256(response.encode('utf-8')).hexdigest() if isinstance(response, str) else None,
            'response_matches_expected': isinstance(response, str) and response.strip() == EXPECTED_RESPONSE,
            'model_field_present': 'model' in result, 'model': allowed_name(result.get('model'), MODEL_PATTERN),
            'duration_seconds_present': 'duration_seconds' in result,
            'permission_denials_present': bool(result.get('permission_denials'))}
        private['error'] = error_source
        if result.get('conversation_id') != session:
            sessions_ok = False
    else:
        sessions_ok = False
    summary['conversation_ids_consistent'] = sessions_ok
    return summary, private


def agy_error_lines(stderr_text):
    """Structured 'AGY_ERROR: {...}' lines: key names and sanitized scalar fields only."""
    records = []
    for line in stderr_text.splitlines():
        text = line.strip()
        if not text.startswith('AGY_ERROR:'):
            continue
        if len(records) >= 4:
            break
        payload = text[len('AGY_ERROR:'):].strip()
        try:
            value = strict_json(payload)
        except (ValueError, TypeError, RecursionError):
            records.append({'parsed': False, 'keys': [], 'fields': {}})
            continue
        if not isinstance(value, dict):
            records.append({'parsed': False, 'keys': [], 'fields': {}})
            continue
        fields = {}
        for key in key_names(value)[:16]:
            item = value[key]
            if isinstance(item, bool) or item is None or (type(item) is int and abs(item) < 2 ** 53):
                fields[key] = item
            elif isinstance(item, str):
                fields[key] = sanitized_text(item)[0]
            else:
                fields[key] = 'NON_SCALAR'
        records.append({'parsed': True, 'keys': key_names(value), 'fields': fields})
    return records


def classify_run(stdout, stderr, outcome, exit_code, requested, protocol=None):
    """Allowlisted classification of one stream-json run; the answer text is reduced to a digest."""
    oversize = len(stdout) + len(stderr) > RUN_OUTPUT
    try:
        out = stdout.decode('utf-8', 'strict')
        utf8 = True
    except UnicodeError:
        out, utf8 = '', False
    err = strip_ansi(stderr.decode('utf-8', 'replace'))
    usable = utf8 and not oversize
    stream, private = parse_stream_events(out if usable else '', requested)
    markers = {marker: marker in err for marker in STDERR_MARKERS}
    protocol_check = {'evaluated': False, 'accepted': None, 'error': None}
    if protocol is not None and usable:
        protocol_check['evaluated'] = True
        try:
            protocol.parse_stream(out, requested)
            protocol_check['accepted'] = True
        except ValueError as exc:
            protocol_check['accepted'] = False
            protocol_check['error'] = sanitized_text(str(exc))[0]
    result = {'utf8_valid': utf8, 'output_bound_exceeded': oversize or outcome == 'output_bound_terminated',
              'timed_out': outcome == 'timed_out_terminated', 'stdout_empty': not stdout, 'stderr_empty': not stderr,
              'stderr_lines': len([line for line in err.splitlines() if line.strip()]),
              'stream': stream, 'stderr_markers': markers, 'agy_error_lines': agy_error_lines(err),
              'error_templates': error_templates(err, private['error']),
              'agy_protocol_parse_stream': protocol_check}
    del out, err, private
    return result


def run_checks(record, requested):
    """The identity/isolation contract evaluated on one run record (mirrored by the wrapper)."""
    c = record['classification']
    s = c['stream']
    init, steps, res = s['init'], s['steps'], s['result']
    init_present = s['init_present'] is True and isinstance(init, dict)
    result_present = s['result_present'] is True and isinstance(res, dict)
    checks = {
        'exited_zero': record['outcome'] == 'exited' and type(record['exit_code']) is int and record['exit_code'] == 0,
        'init_present': init_present,
        'stream_well_formed': (c['utf8_valid'] is True and c['output_bound_exceeded'] is False and s['malformed_lines'] == 0
                               and s['non_object_lines'] == 0 and s['lines_truncated'] is False
                               and s['first_event_init'] is True and s['last_event_result'] is True
                               and s['conversation_ids_consistent'] is True),
        'tools_empty': init_present and init['tools_is_list'] is True and init['tools_count'] == 0,
        'agent_matches': init_present and init['agent'] == AGENT_NAME,
        'model_matches': init_present and init['model'] == requested,
        'no_tool_steps': steps['tool_name_count'] == 0 and steps['tool_info_count'] == 0 and steps['step_type_tool_count'] == 0,
        'no_subagent_steps': steps['subagent_info_count'] == 0,
        'only_allowed_step_types': steps['disallowed_step_type_count'] == 0,
        'step_models_match': steps['model_mismatch_count'] == 0,
        'result_success': (result_present and res['status'] == 'SUCCESS' and res['error_present'] is False
                           and res['response_present'] is True and res['permission_denials_present'] is False),
        'num_turns_one': result_present and res['num_turns'] == 1,
        'result_model_absent_or_equal': not (result_present and res['model_field_present'] is True and res['model'] != requested),
        'no_stderr_markers': not any(c['stderr_markers'].values()),
    }
    checks['accepted'] = checks['exited_zero'] and checks['result_success']
    # O-F1: the run's owned Job may hold agy's own tree only; a missing or larger count is a breach.
    accounting = record.get('job_accounting')
    total = accounting.get('total_processes') if isinstance(accounting, dict) else None
    checks['job_processes_within_tree'] = type(total) is int and 1 <= total <= JOB_EXPECTED_PROCESSES_MAXIMUM
    checks['isolation_breach'] = ((init_present and not checks['tools_empty']) or not checks['no_tool_steps']
                                  or not checks['no_subagent_steps'] or not checks['job_processes_within_tree'])
    checks['passes_contract'] = all(checks[name] for name, _ in RUN_CHECK_REASONS)
    # The echoed form (R3): identity is init.model as echoed, consistent across steps and result.
    echoed = init['model'] if init_present else None
    checks['echo_consistent'] = (init_present and init['model_present'] is True and isinstance(echoed, str)
                                 and echoed != 'OTHER' and steps['model_init_mismatch_count'] == 0
                                 and not (result_present and res['model_field_present'] is True and res['model'] != echoed))
    checks['passes_with_echo'] = checks['echo_consistent'] and all(
        checks[name] for name, _ in RUN_CHECK_REASONS if name not in ECHO_EXEMPT_CHECKS)
    return checks


# ----- non-inference probe classification -----

def parse_envelope(text):
    try:
        value = strict_json(text)
    except (ValueError, TypeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def envelope_list(envelope, key):
    command = envelope.get('command') if isinstance(envelope, dict) else None
    data = command.get('data') if isinstance(command, dict) else None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, list) else None


def only_fetching_stderr(err):
    return all(line.strip() == FETCHING_LINE for line in err.splitlines() if line.strip())


def status_helper_predicate(stdout, stderr, exit_code, completed):
    """The r4 status helper's gemini predicate (build manifest step 3): LOGGED_IN | LOGGED_OUT | HOLD."""
    if not completed or type(exit_code) is not int or len(stdout) + len(stderr) > PROBE_OUTPUT:
        return 'HOLD'
    try:
        out, err = stdout.decode('utf-8', 'strict'), stderr.decode('utf-8', 'strict')
    except UnicodeError:
        return 'HOLD'
    envelope = parse_envelope(out)
    models = envelope_list(envelope, 'models')
    command = envelope.get('command') if isinstance(envelope, dict) else None
    if (exit_code == 0 and envelope is not None and envelope.get('status') == 'SUCCESS' and isinstance(command, dict)
            and command.get('name') == 'models' and models
            and all(isinstance(row, dict) and isinstance(row.get('id'), str) and isinstance(row.get('label'), str) for row in models)
            and any(row['id'].startswith('gemini-') for row in models) and only_fetching_stderr(err)):
        return 'LOGGED_IN'
    text = out + '\n' + err
    if (exit_code != 0 or any(marker in text for marker in (SIGN_IN_PREDICATE_TEXT, AUTH_REQUIRED_TEXT, NOT_LOGGED_IN_LINE))
            or (envelope is not None and envelope.get('status') != 'SUCCESS')):
        return 'LOGGED_OUT'
    return 'HOLD'


def listed_names(values, pattern):
    names = [value for value in values if isinstance(value, str) and pattern.fullmatch(value)]
    return names[:MAX_LISTED], len(values) - len(names[:MAX_LISTED])


def classify_probe(kind, stdout, stderr, outcome, exit_code):
    oversize = len(stdout) + len(stderr) > PROBE_OUTPUT
    try:
        out = stdout.decode('utf-8', 'strict')
        utf8 = True
    except UnicodeError:
        out, utf8 = '', False
    usable = utf8 and not oversize
    result = {'timed_out': outcome == 'timed_out_terminated', 'output_bound_exceeded': oversize or outcome == 'output_bound_terminated',
              'utf8_valid': utf8, 'stdout_empty': not stdout, 'stderr_empty': not stderr}
    lines = [line.strip() for line in strip_ansi(out).splitlines() if line.strip()] if usable else []
    if kind == 'version':
        result['version_matches'] = outcome == 'exited' and exit_code == 0 and usable and out.strip() == AGY_VERSION
    elif kind == 'models_json':
        envelope = parse_envelope(out) if usable else None
        models = envelope_list(envelope, 'models')
        ids = [row.get('id') for row in models if isinstance(row, dict)] if models is not None else []
        result['json_envelope_parsed'] = envelope is not None
        result['status_value'] = allow(envelope.get('status'), STATUS_VALUES) if envelope else None
        result['gemini_row_present'] = any(isinstance(i, str) and i.startswith('gemini-') for i in ids)
        result['model_ids'], result['model_ids_unlisted'] = listed_names(ids, MODEL_PATTERN)
        result['status_helper_classification'] = status_helper_predicate(stdout, stderr, exit_code, outcome == 'exited')
    elif kind == 'agents_json':
        envelope = parse_envelope(out) if usable else None
        agents = envelope_list(envelope, 'agents')
        command = envelope.get('command') if isinstance(envelope, dict) else None
        result['json_envelope_parsed'] = envelope is not None
        result['status_value'] = allow(envelope.get('status'), STATUS_VALUES) if envelope else None
        result['command_name'] = allow(command.get('name'), ('agents', 'models')) if isinstance(command, dict) else None
        result['agents_count'] = len(agents) if agents is not None else None
        result['agents'], result['agents_unlisted'] = listed_names(agents or [], AGENT_NAME_PATTERN)
    elif kind == 'agents_text':
        result['agents_count'] = len(lines)
        result['agents'], result['agents_unlisted'] = listed_names(lines, AGENT_NAME_PATTERN)
    return result


def agents_probe_ok(probe, json_form):
    """One listing probe proves the slot resolves exactly the protected agent (exit 0, exact list)."""
    if not isinstance(probe, dict):
        return False
    value = probe.get('classification')
    code = probe.get('exit_code')
    if (not isinstance(value, dict) or probe.get('outcome') != 'exited' or type(code) is not int or code != 0
            or value.get('agents') != [AGENT_NAME] or value.get('agents_unlisted') != 0 or value.get('agents_count') != 1):
        return False
    return not json_form or (value.get('status_value') == 'SUCCESS' and value.get('command_name') == 'agents')


def listing_reasons(probes):
    by = {probe.get('id'): probe for probe in probes}
    reasons = []
    if not agents_probe_ok(by.get('PC3'), True):
        reasons.append('AGENTS_JSON_LISTING_FAILED')
    if not agents_probe_ok(by.get('PC4'), False):
        reasons.append('AGENTS_TEXT_LISTING_FAILED')
    return reasons


def precheck_decision(probes, shadows_found):
    """Model jobs run only when the slot is signed in and resolves exactly the protected agent."""
    by = {probe.get('id'): probe for probe in probes}
    reasons = []
    pc1, pc2 = (by.get(name, {}).get('classification') for name in ('PC1', 'PC2'))
    if not isinstance(pc1, dict) or pc1.get('version_matches') is not True:
        reasons.append('PRECHECK_VERSION_MISMATCH')
    if not isinstance(pc2, dict) or pc2.get('status_helper_classification') != 'LOGGED_IN':
        reasons.append('PRECHECK_NOT_SIGNED_IN')
    if listing_reasons(probes):
        reasons.append('AGENTS_PRECHECK_FAILED')
    if shadows_found:
        reasons.append('AGENT_SHADOW_FOUND')
    return {'passed': not reasons, 'reasons': reasons}


# ----- gate and verdicts -----

INVENTORY_KEYS = ('hooks_absent', 'mcp_absent', 'plugins_absent', 'skills_absent')


def isolation_gate(status, precheck, runs, verdict=None):
    """Gate G3 (sitting S8): the protected agent is resolved, R1 meets the identity/isolation contract, no
    run in the matrix breaches isolation or runs a process beyond agy's own tree and (when the verdict is given)
    the six-profile and workspace-chain inventory shows no hooks, MCP, plugins or skills and
    C:\\ProgramData\\Antigravity is absent or the protected empty folder."""
    if status not in ('EVIDENCE_COMPLETE', 'EVIDENCE_PRECHECK_REFUSED'):
        return {'passed': False, 'reasons': ['EVIDENCE_NOT_COMPLETE']}
    reasons = list(precheck['reasons'])
    if status == 'EVIDENCE_PRECHECK_REFUSED' or reasons:
        return {'passed': False, 'reasons': reasons or ['EVIDENCE_NOT_COMPLETE']}
    by = {run['id']: run for run in runs}
    r1 = by.get('R1')
    if r1 is None or 'checks' not in r1:
        reasons.append('R1_NOT_RUN')
    else:
        reasons.extend(reason for name, reason in RUN_CHECK_REASONS if r1['checks'][name] is not True)
    if any(run['checks']['isolation_breach'] for run in runs if run['id'] != 'R1' and 'checks' in run):
        reasons.append('ISOLATION_BREACH_IN_MATRIX')
    if any(run['checks'].get('job_processes_within_tree') is not True for run in runs if 'checks' in run):
        reasons.append('JOB_PROCESSES_BEYOND_AGY_TREE')
    if any(log_fallback_found(run) for run in runs if 'checks' in run and run['checks'].get('accepted') is True):
        reasons.append('MODEL_FALLBACK_LOGGED')
    if any(log_scan_incomplete(run) for run in runs if 'checks' in run and run['checks'].get('accepted') is True):
        reasons.append('MODEL_LOG_SCAN_INCOMPLETE')
    if verdict is not None and not all(verdict.get(key) is True for key in INVENTORY_KEYS):
        reasons.append('PROFILE_INVENTORY_NOT_CLEAR')
    if verdict is not None:
        # The file and the customization key names (or the inspection reason) of each flagged user configuration.
        reasons.extend(PROFILE_CONFIG_REASON_PREFIX + item for item in verdict.get('profile_configs_flagged') or [])
    if verdict is not None and verdict.get('programdata_antigravity_clear') is not True:
        reasons.append('PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR')
    return {'passed': not reasons, 'reasons': reasons}


def present(row):
    """A path proves absence only when it does not exist or is an empty, fully listed directory; an inspected
    declared user configuration counts only when its inspection is not CLEAR (present-but-clear)."""
    if row.get('exists') is not True:
        return False
    declared = row.get('declared_config')
    if row.get('kind') == 'file' and isinstance(declared, dict):
        return declared.get('status') != 'CLEAR'
    return not (row.get('kind') == 'dir' and row.get('entry_count') == 0 and row.get('truncated') is False)


def declared_config_detail(row):
    """The reason suffix of a flagged declared configuration: its customization key names, else why it is flagged."""
    declared = row.get('declared_config')
    if row.get('kind') == 'file' and isinstance(declared, dict):
        return ','.join(declared.get('flagged_keys') or []) or str(declared.get('reason'))
    return str(row.get('kind'))


def flagged_profile_configs(profiles):
    return [f"{profile.get('slot')}:{row['path']}:{declared_config_detail(row)}"
            for profile in profiles for row in profile.get('paths') or []
            if row.get('path') in DECLARED_CONFIG_PATHS and present(row)]


def inventory_flags(paths, workspace=False):
    rows = {row['path']: row for row in paths}

    def hit(names):
        return any(present(rows.get(name, {})) for name in names)
    if workspace:
        plugins = hit(WORKSPACE_PLUGIN_PATHS)
        return {'hooks_present': hit(WORKSPACE_HOOK_PATHS) or plugins, 'mcp_present': hit(WORKSPACE_MCP_PATHS) or plugins,
                'plugins_present': plugins, 'skills_present': hit(WORKSPACE_SKILL_PATHS) or plugins}
    plugins = hit(PLUGIN_PATHS)
    return {'hooks_present': hit(HOOK_PATHS) or plugins, 'mcp_present': hit(MCP_PATHS) or plugins,
            'plugins_present': plugins, 'skills_present': hit(SKILL_PATHS) or plugins,
            'rules_present': hit(('.gemini/config/rules',)), 'workflows_present': hit(('.gemini/config/workflows',))}


def isolation_verdict(runs, profiles, workspaces, programdata=None):
    executed = [run for run in runs if 'checks' in run]
    with_init = [run for run in executed if run['checks']['init_present']]
    flags = [profile['flags'] for profile in profiles] + [workspace['flags'] for workspace in workspaces]
    complete = len(profiles) == 6
    verdict = {'tools_empty': any(run['id'] == 'R1' for run in with_init) and all(run['checks']['tools_empty'] for run in with_init),
               'no_tool_steps': bool(executed) and all(run['checks']['no_tool_steps'] for run in executed),
               'no_subagent_steps': bool(executed) and all(run['checks']['no_subagent_steps'] for run in executed),
               'hooks_absent': complete and not any(flag['hooks_present'] for flag in flags),
               'mcp_absent': complete and not any(flag['mcp_present'] for flag in flags),
               'plugins_absent': complete and not any(flag['plugins_present'] for flag in flags),
               'skills_absent': complete and not any(flag['skills_present'] for flag in flags),
               'model_fallback_basis': 'UNKNOWN',
               'runs_considered': [run['id'] for run in executed], 'profiles_considered': len(profiles),
               'workspaces_considered': [workspace['label'] for workspace in workspaces]}
    # The inference_only.disables_* attestations the config builder copies (manifest step 13): each is
    # true only where this evidence supports it. disables_model_fallback is deliberately absent: the
    # basis stays UNKNOWN here and the builder applies its explicit 3B rule (identity policy + reroute
    # scan + passing replay G5).
    # O-F1/O-F2: hooks and MCP count as disabled only while the extended inventory is clear (six profiles, both
    # workspace chains, C:\ProgramData\Antigravity) AND every executed run's Job held agy's own tree only.
    verdict['process_accounting_clean'] = bool(executed) and all(
        run['checks'].get('job_processes_within_tree') is True for run in executed)
    verdict['programdata_antigravity_clear'] = isinstance(programdata, dict) and programdata.get('clear') is True
    verdict['profile_configs_flagged'] = flagged_profile_configs(profiles)
    clean = verdict['process_accounting_clean'] and verdict['programdata_antigravity_clear']
    verdict['disables_tools'] = verdict['tools_empty'] and verdict['no_tool_steps']
    verdict['disables_mcp'] = verdict['mcp_absent'] and verdict['plugins_absent'] and clean
    verdict['disables_hooks'] = verdict['hooks_absent'] and verdict['plugins_absent'] and clean
    verdict['disables_subagents'] = verdict['no_subagent_steps'] and verdict['tools_empty']
    return verdict


def identity_verdict(runs, matrix=RUNS, effort_null_slug=DEFAULT_EFFORT_NULL_SLUG, skipped=None):
    by = {run['id']: run for run in runs if 'checks' in run}
    skip_reasons = {item.get('id'): item.get('reason') for item in skipped or () if isinstance(item, dict)}
    rows = {}
    for run_id, model, extra, _ in matrix:
        run = by.get(run_id)
        if run is None:
            # O-F4: a run that did not execute (pre-check refusal, isolation stop, deadline guard) passes nothing, so the
            # builder leaves its binding unbound.
            rows[run_id] = {'executed': False, 'requested_model': model, 'extra_arguments': list(extra),
                            'accepted': False, 'passes_contract': False, 'passes_with_echo': False,
                            'skipped_reason': skip_reasons.get(run_id)}
            continue
        c, s = run['classification'], run['classification']['stream']
        init, res = s['init'] or {}, s['result'] or {}
        rows[run_id] = {
            'executed': True, 'requested_model': model, 'extra_arguments': list(extra),
            'exit_code': run['exit_code'], 'outcome': run['outcome'], 'accepted': run['checks']['accepted'],
            'passes_contract': run['checks']['passes_contract'], 'passes_with_echo': run['checks']['passes_with_echo'],
            'init_model': init.get('model'), 'init_model_equals_requested': run['checks']['model_matches'],
            'init_agent_equals': run['checks']['agent_matches'], 'result_status': res.get('status'),
            'result_model_field_present': res.get('model_field_present') is True,
            'error_templates': c['error_templates'], 'error_text': res.get('error_text'),
            'agy_error_line_present': bool(c['agy_error_lines']), 'agy_error_lines': c['agy_error_lines'],
            'stderr_markers': sorted(marker for marker, hit in c['stderr_markers'].items() if hit),
            'reroute_keys': list(s['reroute_keys']),
            'log_scanned': isinstance(run.get('log_scan'), dict) and run['log_scan'].get('log_scanned') is True,
            'log_fallback_found': log_fallback_found(run), 'log_scan_incomplete': log_scan_incomplete(run)}
    empty = {'executed': False}
    r1, r2, r3, r4, r5 = (rows.get(name, empty) for name in ('R1', 'R2', 'R3', 'R4', 'R5'))
    accepted = [row for row in rows.values() if row.get('accepted') is True]
    return {'primary_model': PRIMARY_MODEL, 'identity_source': 'init.model (the result envelope documents no model field)',
            'runs': rows,
            'slug_form_accepted': r1.get('accepted') is True and r1.get('init_model_equals_requested') is True,
            'slug_form_passes_contract': r1.get('passes_contract') is True,
            'slug_with_effort_accepted': r2.get('accepted') is True,
            'slug_with_effort_passes_contract': r2.get('passes_contract') is True,
            'slug_with_effort_init_model': r2.get('init_model') if r2.get('accepted') is True else None,
            'family_with_effort_accepted': r3.get('accepted') is True,
            'family_with_effort_passes_with_echo': r3.get('passes_with_echo') is True,
            'family_with_effort_init_model': r3.get('init_model') if r3.get('accepted') is True else None,
            'unknown_model_rejected': r4.get('executed') is True and r4.get('accepted') is False,
            'unknown_model_exit_code': r4.get('exit_code'), 'unknown_model_error_templates': r4.get('error_templates', []),
            'effort_null': {'slug': effort_null_slug, 'run_id': 'R5', 'executed': r5.get('executed') is True,
                            'passed': r5.get('passes_contract') is True, 'init_model': r5.get('init_model')},
            # Reroute scan over every accepted run (R4's expected AGY_ERROR line is not an accepted run): stderr markers,
            # stream reroute keys and (RG-2) a true fallback phrase in the run's own cli-*.log.
            'reroute_scan_clean': (r1.get('executed') is True and bool(accepted)
                                   and all(row['stderr_markers'] == [] and row['reroute_keys'] == [] and row['log_fallback_found'] is False and row['log_scan_incomplete'] is False
                                           for row in accepted)),
            'result_model_field_present_any': any(row.get('result_model_field_present') is True for row in rows.values())}


def staged_records_ok(records):
    if not isinstance(records, list) or len(records) != len(AGENT_DESTINATION_PARTS):
        return False
    for record, parts in zip(records, AGENT_DESTINATION_PARTS):
        if (not isinstance(record, dict) or record.get('relative') != '/'.join(parts) or record.get('sha256') != AGENT_SHA256
                or record.get('bytes') != AGENT_BYTES or record.get('acl_verified') is not True):
            return False
    return True


def slot_staging_reasons(entry):
    reasons = []
    if not staged_records_ok(entry.get('staged')) or entry.get('agent_sha256_after_listing') != [AGENT_SHA256] * len(AGENT_DESTINATION_PARTS):
        reasons.append('AGENT_NOT_STAGED_AT_BOTH_LOCATIONS')
    if entry.get('shadows_found'):
        reasons.append('AGENT_SHADOW_FOUND')
    reasons.extend(listing_reasons(entry.get('probes') or []))
    return reasons


def staging_gate(status, slots):
    """Config-builder gate G4: every slot holds the pinned agent at both locations and lists exactly it."""
    if status != 'STAGING_COMPLETE':
        return {'passed': False, 'reasons': ['STAGING_NOT_COMPLETE'], 'slots': {}}
    by = {entry.get('slot'): entry for entry in slots}
    per_slot = {slot: (slot_staging_reasons(by[slot]) if slot in by else ['SLOT_NOT_PROCESSED']) for slot in STAGE_SLOTS}
    reasons = [f'{slot}:{reason}' for slot in STAGE_SLOTS for reason in per_slot[slot]]
    return {'passed': not reasons, 'reasons': reasons,
            'slots': {slot: {'passed': not per_slot[slot], 'reasons': per_slot[slot]} for slot in STAGE_SLOTS}}


# ----- inventories (token files: existence and size only, never opened) -----

def is_reparse(info):
    return bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def token_like(relative):
    return any('token' in part.casefold() for part in relative.split('/'))


def open_for_hash(path):
    # The only place an inventory opens a file. Token-like paths never reach it.
    return open(path, 'rb')


def hash_inventory_file(path):
    with open_for_hash(path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > INVENTORY_HASH_LIMIT:
            return None, 'over_1_mib'
        digest, count = hashlib.sha256(), 0
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > INVENTORY_HASH_LIMIT:
                return None, 'over_1_mib'
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != after.st_size:
        return None, 'changed_during_hash'
    return digest.hexdigest(), None


def file_row(relative, path, info):
    row = {'path': relative, 'kind': 'file', 'size': info.st_size, 'sha256': None}
    if LOG_PATH_PATTERN.fullmatch(relative) and not token_like(relative):
        row['mtime_ns'] = info.st_mtime_ns
    if token_like(relative):
        row['token_file'] = True
    elif info.st_nlink != 1:
        row['hash_skipped'] = 'hardlink'
    elif info.st_size > INVENTORY_HASH_LIMIT:
        row['hash_skipped'] = 'over_1_mib'
    else:
        try:
            row['sha256'], reason = hash_inventory_file(path)
        except OSError as error:
            row['sha256'], reason = None, 'unreadable_' + type(error).__name__
        if reason:
            row['hash_skipped'] = reason
    return row


def inventory_tree(root, max_entries=MAX_TREE_ENTRIES, label=''):
    """Bounded listing; the token rule is applied to the label-qualified path so a tree root cannot hide it."""
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return {'exists': False, 'reparse_point': False, 'entries': [], 'entry_count': 0, 'truncated': False}
    if is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        return {'exists': True, 'reparse_point': is_reparse(info), 'directory': stat.S_ISDIR(info.st_mode),
                'entries': [], 'entry_count': 0, 'truncated': False}
    entries, truncated, stack = [], False, [(str(root), '', 0)]
    while stack and not truncated:
        directory, prefix, depth = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            entries.append({'path': prefix.rstrip('/') or '.', 'kind': 'unreadable_directory', 'error': type(error).__name__})
            continue
        for entry in children:
            if len(entries) >= max_entries:
                truncated = True
                break
            relative = prefix + entry.name
            try:
                item = os.lstat(entry.path)
            except OSError as error:
                entries.append({'path': relative, 'kind': 'unreadable', 'error': type(error).__name__})
                continue
            if is_reparse(item):
                entries.append({'path': relative, 'kind': 'reparse_point'})
            elif stat.S_ISDIR(item.st_mode):
                row = {'path': relative, 'kind': 'dir'}
                if depth + 1 < MAX_TREE_DEPTH:
                    stack.append((entry.path, relative + '/', depth + 1))
                else:
                    row['not_descended'] = 'depth_bound'
                entries.append(row)
            else:
                row = file_row((label + '/' if label else '') + relative, entry.path, item)
                row['path'] = relative
                entries.append(row)
    entries.sort(key=lambda row: row['path'])
    return {'exists': True, 'reparse_point': False, 'entries': entries, 'entry_count': len(entries), 'truncated': truncated}


def inventory_path(base, relative, max_entries=PROFILE_PATH_MAX_ENTRIES):
    """One listed path below base; an intermediate reparse point is reported, never followed."""
    parts = relative.split('/')
    current, info = base, None
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return {'path': relative, 'exists': False}
        except OSError as error:
            return {'path': relative, 'exists': True, 'kind': 'unreadable', 'error': type(error).__name__}
        if is_reparse(info):
            return {'path': relative, 'exists': True, 'kind': 'reparse_point' if index == len(parts) - 1 else 'ancestor_reparse_point'}
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            return {'path': relative, 'exists': False, 'ancestor_not_directory': True}
    if stat.S_ISDIR(info.st_mode):
        tree = inventory_tree(current, max_entries, relative)
        return {'path': relative, 'exists': True, 'kind': 'dir', 'entry_count': tree['entry_count'],
                'truncated': tree['truncated'], 'entries': tree['entries']}
    return {'exists': True, **file_row(relative, current, info)}


def ordinary_root(path):
    info = os.lstat(path)
    if is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError('An inventoried root is not an ordinary directory')


class DuplicateJsonKey(ValueError):
    pass


def config_key_name(key):
    """A recordable key NAME (never a value); anything else is 'OTHER'."""
    if (isinstance(key, str) and CONFIG_KEY_PATTERN.fullmatch(key) and not UNSAFE_TEXT_PATTERN.search(key)
            and not sensitive_scan(key.encode('ascii'))):
        return key
    return 'OTHER'


def json_nesting_depth(text):
    """Maximum object/array nesting outside strings, computed before parsing so a hostile file cannot recurse."""
    depth = deepest = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in '[{':
            depth += 1
            deepest = max(deepest, depth)
        elif character in ']}':
            depth -= 1
    return deepest


def inspect_declared_config(data):
    """The Commander's rule for ~/.gemini/config/{config,skills,plugins}.json on bytes already read (bounded).

    Returns a record of key NAMES only: CLEAR, or FLAGGED with a reason from DECLARED_CONFIG_REASONS."""
    record = {'status': 'FLAGGED', 'reason': None, 'bytes': len(data), 'sha256': None, 'top_level_keys': [],
              'matching_keys': [], 'flagged_keys': []}
    if len(data) > DECLARED_CONFIG_MAXIMUM:
        record['reason'] = 'OVER_SIZE_BOUND'
        return record
    record['sha256'] = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError:
        record['reason'] = 'NOT_UTF8'
        return record
    if json_nesting_depth(text) > DECLARED_CONFIG_DEPTH:
        record['reason'] = 'TOO_DEEP'
        return record

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DuplicateJsonKey('Duplicate JSON key')
            result[key] = value
        return result

    def reject_constant(_):
        raise ValueError('Nonfinite JSON value')
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
    except DuplicateJsonKey:
        record['reason'] = 'DUPLICATE_KEY'
        return record
    except (ValueError, TypeError, RecursionError):
        record['reason'] = 'UNPARSEABLE'
        return record
    if not isinstance(value, dict):
        record['reason'] = 'NOT_AN_OBJECT'
        return record
    matching, flagged, stack = set(), set(), [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if any(fragment in key.casefold() for fragment in DECLARED_CONFIG_FRAGMENTS):
                    matching.add(config_key_name(key))
                    if child is True or (isinstance(child, (dict, list, str)) and len(child) > 0):
                        flagged.add(config_key_name(key))
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
    record.update(top_level_keys=sorted({config_key_name(key) for key in value})[:MAX_LISTED],
                  matching_keys=sorted(matching)[:MAX_LISTED], flagged_keys=sorted(flagged)[:MAX_LISTED])
    if flagged:
        record['reason'] = 'CUSTOMIZATION_KEYS'
    else:
        record['status'] = 'CLEAR'
    return record


def inspect_profile_config(path, row):
    """Read one declared configuration once (never a link, a reparse point or a hardlinked file) and inspect it; the
    bytes must be the ones the inventory row hashed."""
    record = {'status': 'FLAGGED', 'reason': None, 'bytes': None, 'sha256': None, 'top_level_keys': [],
              'matching_keys': [], 'flagged_keys': []}
    try:
        info = os.lstat(path)
        if is_reparse(info) or not stat.S_ISREG(info.st_mode):
            record['reason'] = 'NOT_A_REGULAR_FILE'
            return record
        if info.st_nlink != 1:
            record['reason'] = 'HARDLINKED'
            return record
        with open_for_hash(path) as stream:
            data = stream.read(DECLARED_CONFIG_MAXIMUM + 1)
    except OSError:
        record['reason'] = 'UNREADABLE'
        return record
    record = inspect_declared_config(data)
    del data
    if record['reason'] != 'OVER_SIZE_BOUND' and record['sha256'] != row.get('sha256'):
        record.update(status='FLAGGED', reason='CHANGED_DURING_INSPECTION', top_level_keys=[], matching_keys=[], flagged_keys=[])
    return record


def profile_inventory_rows(profile):
    """The PROFILE_PATHS rows of one profile; the declared user configurations also carry their content inspection."""
    rows = [inventory_path(profile, relative) for relative in PROFILE_PATHS]
    for row in rows:
        if row['path'] in DECLARED_CONFIG_PATHS and row.get('exists') is True and row.get('kind') == 'file':
            row['declared_config'] = inspect_profile_config(profile.joinpath(*row['path'].split('/')), row)
    return rows


def six_profile_inventory(layout_slots, profile_parent):
    profiles = []
    for slot in sorted(layout_slots, key=lambda name: int(name[4:])):
        identity = layout_slots[slot]['identity']
        profile = profile_parent / identity
        record = {'slot': slot, 'identity': identity, 'profile_root': str(profile)}
        try:
            ordinary_root(profile)
            record['profile_present'] = True
            record['paths'] = profile_inventory_rows(profile)
        except FileNotFoundError:
            record['profile_present'] = False
            record['paths'] = [{'path': relative, 'exists': False} for relative in PROFILE_PATHS]
        record['flags'] = inventory_flags(record['paths'])
        profiles.append(record)
    return profiles


def workspace_ancestors(root):
    """Every ancestor directory of a workspace up to its drive root, nearest first (path arithmetic only, no I/O)."""
    path = Path(root)
    if not path.is_absolute() or not path.drive:
        raise ValueError('A workspace root must be an absolute drive path')
    return list(path.parents)


def workspace_inventory(label, root):
    """The workspace root and EVERY ancestor up to the drive root, each for all WORKSPACE_PATHS (O-F1); an ancestor is
    inventoried even when the root (for example the RAM workspace before admission) does not exist yet."""
    record = {'label': label, 'root': str(root) if root is not None else None, 'ancestors': []}
    if root is None:
        record.update(root_present=False, paths=[{'path': relative, 'exists': False} for relative in WORKSPACE_PATHS])
    else:
        try:
            ordinary_root(root)
            record['root_present'] = True
            record['paths'] = [inventory_path(root, relative) for relative in WORKSPACE_PATHS]
        except FileNotFoundError:
            record['root_present'] = False
            record['paths'] = [{'path': relative, 'exists': False} for relative in WORKSPACE_PATHS]
        record['ancestors'] = [{'directory': str(directory), 'paths': [inventory_path(directory, relative) for relative in WORKSPACE_PATHS]}
                               for directory in workspace_ancestors(root)]
    flags = [inventory_flags(rows, workspace=True) for rows in (record['paths'], *(item['paths'] for item in record['ancestors']))]
    record['flags'] = {key: any(flag[key] for flag in flags) for key in flags[0]}
    return record


def slot_inventory(profile, workspace):
    trees = {label: inventory_tree(profile.joinpath(*parts), MAX_TREE_ENTRIES, label) for label, parts in SLOT1_TREES}
    trees['workspace'] = inventory_tree(workspace, MAX_TREE_ENTRIES, 'workspace')
    return {'profile_root': str(profile), 'workspace_root': str(workspace),
            'captured_at_unix_ms': int(time.time() * 1000), 'trees': trees}


slot1_inventory = slot_inventory


def inventory_changes(before, after):
    def rows(snapshot, kind):
        return {label + '/' + row['path']: row for label, tree in snapshot['trees'].items()
                for row in tree['entries'] if row['kind'] == kind}
    old, new = rows(before, 'file'), rows(after, 'file')
    new_files = [{'path': key, 'size': new[key]['size'], 'token_file': new[key].get('token_file', False)}
                 for key in sorted(set(new) - set(old))]
    changed = [key for key in sorted(set(new) & set(old))
               if (new[key]['size'], new[key]['sha256'], new[key].get('mtime_ns')) !=
                  (old[key]['size'], old[key]['sha256'], old[key].get('mtime_ns'))]
    removed = sorted(set(old) - set(new))
    directories = sorted(set(rows(after, 'dir')) - set(rows(before, 'dir')))
    prior = {key: {'size': old[key]['size'], 'sha256': old[key]['sha256']}
             for key in changed[:MAX_TREE_ENTRIES] if LOG_PATH_PATTERN.fullmatch(key) and not token_like(key)}
    return {'new_files': new_files[:MAX_TREE_ENTRIES], 'changed_files': changed[:MAX_TREE_ENTRIES], 'prior_logs': prior,
            'removed_files': removed[:MAX_TREE_ENTRIES], 'new_directories': directories[:MAX_TREE_ENTRIES]}


def scan_run_logs(profile, changes):
    """Scan new logs and additions to existing logs; never publish log contents.

    A prior bounded hash proves the unchanged prefix before it is excluded.
    Rewritten files are scanned from zero. An unprovable/over-limit range is
    recorded as incomplete, never promoted to a clean identity observation.
    """
    result = {'log_scanned': False, 'files': [], 'files_skipped': [], 'files_unscanned': 0, 'maximum_bytes_per_file': LOG_SCAN_MAXIMUM,
              'fallback_phrases': dict.fromkeys(LOG_FALLBACK_PHRASES, 0), 'benign_phrases': dict.fromkeys(LOG_BENIGN_PHRASES, 0),
              'fallback_found': False}
    changes = changes or {}
    changed = {name for name in changes.get('changed_files', []) if isinstance(name, str)}
    names = sorted({item['path'] for item in changes.get('new_files') or [] if isinstance(item.get('path'), str)} | changed)
    names = [name for name in names if LOG_PATH_PATTERN.fullmatch(name) and not token_like(name)]
    result['files_unscanned'] = max(0, len(names) - LOG_SCAN_FILES)
    for relative in names[:LOG_SCAN_FILES]:
        path = profile.joinpath(*relative.split('/'))
        try:
            info = os.lstat(path)
            if is_reparse(info) or not stat.S_ISREG(info.st_mode):
                result['files_skipped'].append(relative)
                continue
            offset = 0
            prefix_context = b''
            with open_for_hash(path) as stream:
                before = os.fstat(stream.fileno())
                prior = changes.get('prior_logs', {}).get(relative)
                if relative in changed:
                    if (not isinstance(prior, dict) or type(prior.get('size')) is not int
                            or not 0 <= prior['size'] <= LOG_SCAN_MAXIMUM
                            or not isinstance(prior.get('sha256'), str)):
                        result['files_skipped'].append(relative)
                        continue
                    prefix = stream.read(prior['size'])
                    if hashlib.sha256(prefix).hexdigest() == prior['sha256']:
                        offset = len(prefix)
                        prefix_context = prefix[-256:]
                    else:
                        stream.seek(0)
                data = stream.read(LOG_SCAN_MAXIMUM + 1)
                after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    result['files_skipped'].append(relative)
                    continue
        except OSError:
            result['files_skipped'].append(relative)
            continue
        truncated = len(data) > LOG_SCAN_MAXIMUM
        data = data[:LOG_SCAN_MAXIMUM]
        previous_text = strip_ansi(prefix_context.decode('utf-8', 'replace'))
        text = strip_ansi((prefix_context + data).decode('utf-8', 'replace'))
        for phrase in LOG_FALLBACK_PHRASES:
            result['fallback_phrases'][phrase] += text.count(phrase) - previous_text.count(phrase)
        for phrase in LOG_BENIGN_PHRASES:
            result['benign_phrases'][phrase] += text.count(phrase) - previous_text.count(phrase)
        row = {'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'truncated': truncated}
        if relative in changed:
            row['offset'] = offset
        result['files'].append(row)
        del data, text
    result['log_scanned'] = bool(result['files'])
    result['fallback_found'] = any(result['fallback_phrases'].values())
    result['incomplete'] = bool(result['files_skipped'] or result['files_unscanned']
                                or any(row['truncated'] for row in result['files']))
    return result


def log_fallback_found(run):
    scan = run.get('log_scan') if isinstance(run, dict) else None
    return isinstance(scan, dict) and scan.get('fallback_found') is True


def log_scan_incomplete(run):
    scan = run.get('log_scan') if isinstance(run, dict) else None
    return isinstance(scan, dict) and scan.get('incomplete') is True


# ----- the protected custom agent -----

def validate_agent_definition(raw):
    """The reviewed definition: exact frontmatter, then one H1 heading and one instruction line."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= AGENT_MAX_BYTES or not raw.isascii() or b'\r' in raw or b'\0' in raw:
        raise ValueError('Agent definition must be bounded LF-only ASCII')
    text = raw.decode('ascii')
    if not text.endswith('\n'):
        raise ValueError('Agent definition must end with a newline')
    lines = text[:-1].split('\n')
    expected = ['---', *[f'{key}: {value}' for key, value in AGENT_FRONTMATTER], '---']
    if lines[:len(expected)] != expected:
        raise ValueError('Agent frontmatter differs from the reviewed inference-only definition')
    body = [line for line in lines[len(expected):] if line.strip()]
    if (len(body) != 2 or not re.fullmatch(r'# [A-Za-z][ -~]{0,79}', body[0])
            or body[1].startswith('#') or not 20 <= len(body[1]) <= 400):
        raise ValueError('Agent body must be one H1 heading and one instruction line')
    return dict(AGENT_FRONTMATTER)


def apply_sddl(win, path, sddl):
    api = win._api()
    descriptor = win.HANDLE()
    win._check(api['advapi32'].ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None),
               'Build protected agent ACL')
    try:
        win._check(api['advapi32'].SetFileSecurityW(str(path), 0x80000005, descriptor), 'Apply protected agent ACL')
    finally:
        api['kernel32'].LocalFree(descriptor)


def verify_agent_acl(win, path, sid, directory):
    flags = 3 if directory else 0
    worker = WORKER_READ_DIRECTORY if directory else WORKER_READ_FILE
    owner, protected, rules = win._acl(path)
    if (owner != win.SYSTEM_SID or not protected or len(rules) != 3
            or set(rules) != {(win.SYSTEM_SID, FULL_CONTROL, flags), (win.ADMIN_SID, FULL_CONTROL, flags), (sid, worker, flags)}):
        raise ValueError('Staged agent ACL is not SYSTEM/BA full control with worker read-only')


def ensure_component(path):
    """Create one missing directory component; never accept a link or reparse point."""
    created = False
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        path.mkdir()
        created = True
        info = os.lstat(path)
    if is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError('Agent staging path component is not an ordinary directory')
    return created


def protect_agent_parent(win, directory, sid):
    """O-F3: the parent folder keeps the leaf: SYSTEM/BA full, worker list and traverse only (no delete-child).

    An existing parent that already carries exactly this ACL is reused; any other ACL (the inherited worker full
    control of the profile) is replaced by the protected one and then verified. Returns whether it was applied."""
    try:
        verify_agent_acl(win, directory, sid, True)
        return False
    except (ValueError, win.WindowsIsolationError):
        apply_sddl(win, directory, AGENT_PARENT_DIRECTORY_SDDL.format(sid=sid))
    verify_agent_acl(win, directory, sid, True)
    return True


def stage_agent(win, source, profile, sid, protect_parents=False):
    """Stage the reviewed definition at both discovery locations; identical bytes are reused, others refused.

    protect_parents (stage mode, O-F3) also protects .gemini/agents and .gemini/config/agents before the leaf."""
    raw = source.read_bytes()
    validate_agent_definition(raw)
    if hashlib.sha256(raw).hexdigest() != AGENT_SHA256 or len(raw) != AGENT_BYTES:
        raise ValueError('Agent definition differs from its reviewed pin')
    ordinary_root(profile)
    records = []
    for parts in AGENT_DESTINATION_PARTS:
        current, created, parent = profile, [], None
        for index, part in enumerate(parts[:-1]):
            current = current / part
            leaf = index == len(parts) - 2
            if ensure_component(current):
                created.append('/'.join(parts[:index + 1]))
                if leaf:
                    apply_sddl(win, current, AGENT_DIRECTORY_SDDL.format(sid=sid))
            if protect_parents and index == len(parts) - 3:
                parent = {'parent_relative': '/'.join(parts[:index + 1]), 'parent_path': str(current),
                          'parent_acl_applied': protect_agent_parent(win, current, sid), 'parent_acl_verified': True,
                          'parent_acl_sddl': AGENT_PARENT_DIRECTORY_SDDL.format(sid=sid)}
            if leaf:
                verify_agent_acl(win, current, sid, True)
        target = current / parts[-1]
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            info = None
        if info is None:
            with target.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            apply_sddl(win, target, AGENT_FILE_SDDL.format(sid=sid))
            preexisting = False
        else:
            if (is_reparse(info) or not stat.S_ISREG(info.st_mode) or info.st_size != len(raw)
                    or digest_file(target, AGENT_MAX_BYTES) != AGENT_SHA256):
                raise ValueError('A different agent definition is already staged; preserve it for review')
            preexisting = True
        verify_agent_acl(win, target, sid, False)
        record = {'path': str(target), 'relative': '/'.join(parts), 'sha256': digest_file(target, AGENT_MAX_BYTES),
                  'bytes': target.stat().st_size, 'preexisting': preexisting, 'created_directories': created,
                  'acl_verified': True, 'file_acl_sddl': AGENT_FILE_SDDL.format(sid=sid),
                  'directory_acl_sddl': AGENT_DIRECTORY_SDDL.format(sid=sid)}
        if parent is not None:
            record.update(parent)
        records.append(record)
    return records


def verify_staged_agent(win, records, sid):
    """Re-hash and re-check both staged copies immediately before (and after) every launch: the file, its leaf folder
    and (stage mode) the protected parent, so a renamed-and-replaced tree with inherited ACLs is refused."""
    digests = []
    for record in records:
        path = Path(record['path'])
        info = os.lstat(path)
        if is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError('Staged agent definition is no longer an ordinary file')
        digest = digest_file(path, AGENT_MAX_BYTES)
        if digest != AGENT_SHA256:
            raise ValueError('Staged agent definition changed before launch')
        verify_agent_acl(win, path, sid, False)
        verify_agent_acl(win, path.parent, sid, True)
        if record.get('parent_path') is not None:
            verify_agent_acl(win, Path(record['parent_path']), sid, True)
        digests.append(digest)
    return digests


# ----- C:\ProgramData\Antigravity (O-F2) -----

def programdata_antigravity_state(win, path=None):
    """Read-only: ABSENT, PROTECTED_EMPTY (exactly the stage-mode folder) or a named state that is not clear.

    Entry names are listed (sanitized); nothing inside is opened."""
    path = PROGRAMDATA_ANTIGRAVITY if path is None else Path(path)
    record = {'path': str(path), 'exists': False, 'state': 'ABSENT', 'entry_count': 0, 'entries': [], 'acl': None,
              'clear': True}
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return record
    record.update(exists=True, clear=False)
    if is_reparse(info):
        record['state'] = 'REPARSE_POINT'
        return record
    if not stat.S_ISDIR(info.st_mode):
        record['state'] = 'NOT_DIRECTORY'
        return record
    try:
        names = sorted(os.listdir(path))
    except OSError:
        record['state'] = 'UNREADABLE'
        return record
    record['entry_count'] = len(names)
    record['entries'] = [name if ENTRY_NAME_PATTERN.fullmatch(name) else 'OTHER' for name in names[:MAX_LISTED]]
    if names:
        record['state'] = 'NOT_EMPTY'
        return record
    try:
        owner, protected, rules = win._acl(path)
    except (OSError, ValueError, win.WindowsIsolationError):
        record['state'] = 'ACL_UNVERIFIABLE'
        return record
    record['acl'] = {'owner': owner, 'protected': bool(protected), 'rules': [[sid, mask, flags] for sid, mask, flags in rules]}
    expected = {(win.SYSTEM_SID, FULL_CONTROL, 3), (win.ADMIN_SID, FULL_CONTROL, 3), (USERS_SID, USERS_READ_EXECUTE, 3)}
    if owner != win.SYSTEM_SID or not protected or len(rules) != 3 or set(rules) != expected:
        record['state'] = 'WEAK_ACL'
        return record
    record.update(state='PROTECTED_EMPTY', clear=True)
    return record


def create_protected_directory(win, path, sddl):
    """CreateDirectoryW with the final security descriptor: no window with the inherited ProgramData ACL."""
    api = win._api()
    descriptor = win.HANDLE()
    win._check(api['advapi32'].ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None),
               'Build protected ProgramData folder ACL')
    try:
        attributes = win._SECURITY_ATTRIBUTES(C.sizeof(win._SECURITY_ATTRIBUTES), descriptor, False)
        create = api['kernel32'].CreateDirectoryW
        create.argtypes = [win.LPWSTR, win.HANDLE]
        create.restype = win.BOOL
        win._check(create(str(path), C.byref(attributes)), 'Create the protected empty ProgramData folder')
    finally:
        api['kernel32'].LocalFree(descriptor)


def protect_programdata_antigravity(win, path=None):
    """Stage mode (G4): create C:\\ProgramData\\Antigravity as the protected empty folder when absent; an existing
    folder is accepted only when it already is exactly that folder. Nothing existing is changed or removed."""
    path = PROGRAMDATA_ANTIGRAVITY if path is None else Path(path)
    before = programdata_antigravity_state(win, path)
    record = {'path': str(path), 'sddl': PROGRAMDATA_ANTIGRAVITY_SDDL, 'before': before, 'created': False,
              'state': before['state'], 'after_listing': None, 'clear': False}
    if before['state'] == 'ABSENT':
        ordinary_root(path.parent)
        create_protected_directory(win, path, PROGRAMDATA_ANTIGRAVITY_SDDL)
        record['created'] = True
        apply_sddl(win, path, PROGRAMDATA_ANTIGRAVITY_SDDL)
        current = programdata_antigravity_state(win, path)
        record['state'] = current['state']
        record['current'] = current
    record['clear'] = record['state'] == 'PROTECTED_EMPTY'
    return record


# ----- per-run Job accounting (O-F1) -----

def job_process_accounting(win, process):
    """JOBOBJECT_BASIC_ACCOUNTING_INFORMATION of the run's owned Job, read after TerminateJobObject on that Job (which
    the block exit would do next anyway), so TotalProcesses is final and covers every descendant ever started."""
    process.terminate()
    accounting = win._BASIC_ACCOUNTING()
    win._check(win._api()['kernel32'].QueryInformationJobObject(process._job, 1, C.byref(accounting), C.sizeof(accounting), None),
               'Read the owned Job process accounting')
    return {'total_processes': accounting.TotalProcesses, 'active_processes': accounting.ActiveProcesses,
            'total_terminated_processes': accounting.TotalTerminatedProcesses,
            'expected_maximum': JOB_EXPECTED_PROCESSES_MAXIMUM, 'queried_after_job_termination': True,
            'source': 'QueryInformationJobObject(JobObjectBasicAccountingInformation) on the owned Job'}


def shadow_check(profile, workspaces, name=AGENT_NAME):
    """Other discovery locations must not define the same agent name (workspace, .gemini/.agents, plugins)."""
    folded = name.casefold()
    names = {folded, folded + '.md', folded + '.agent.md'}
    staged = {profile / '.gemini' / 'agents' / name, profile / '.gemini' / 'config' / 'agents' / name}
    checked, found = [], []

    def scan(directory):
        checked.append(str(directory))
        try:
            info = os.lstat(directory)
        except FileNotFoundError:
            return
        except OSError as error:
            found.append({'path': str(directory), 'reason': 'unreadable_' + type(error).__name__})
            return
        if is_reparse(info):
            found.append({'path': str(directory), 'reason': 'reparse_point'})
            return
        if not stat.S_ISDIR(info.st_mode):
            return
        try:
            entries = sorted(os.listdir(directory))[:MAX_SHADOW_ENTRIES]
        except OSError as error:
            found.append({'path': str(directory), 'reason': 'unreadable_' + type(error).__name__})
            return
        for entry in entries:
            path = directory / entry
            if entry.casefold() in names and path not in staged:
                found.append({'path': str(path), 'reason': 'same_name'})

    scan(profile / '.gemini' / 'agents')
    scan(profile / '.gemini' / 'config' / 'agents')
    scan(profile / '.gemini' / '.agents')
    for _, root in workspaces:
        if root is not None:
            # O-F1: all four workspace folder names, in the root and every ancestor up to the drive root.
            for directory in (Path(root), *workspace_ancestors(root)):
                for folder in WORKSPACE_DIRS:
                    scan(directory / folder / 'agents')
                    scan(directory / folder)
    for base in (profile / '.gemini' / 'config' / 'plugins', profile / '.gemini' / 'antigravity-cli' / 'plugins'):
        checked.append(str(base))
        try:
            info = os.lstat(base)
        except FileNotFoundError:
            continue
        if is_reparse(info) or not stat.S_ISDIR(info.st_mode):
            found.append({'path': str(base), 'reason': 'reparse_point' if is_reparse(info) else 'not_directory'})
            continue
        for plugin in sorted(os.listdir(base))[:MAX_PLUGINS]:
            scan(base / plugin / 'agents')
    return checked, found


# ----- worker environment attestation (names only) -----

def environment_names(text, profile):
    names, binding = [], {}
    for entry in text.split('\x00'):
        if not entry or entry.startswith('=') or '=' not in entry:
            continue
        key, value = entry.split('=', 1)
        names.append(key.upper())
        if key.upper() in PROFILE_BINDING_KEYS:
            binding[key.upper()] = value
    flagged = sorted({name for name in names if ENV_NAME_PATTERN.match(name)})
    expected = {'HOME': str(profile), 'USERPROFILE': str(profile), 'APPDATA': str(profile / 'AppData' / 'Roaming'),
                'LOCALAPPDATA': str(profile / 'AppData' / 'Local')}
    rows = {key: {'present': key in binding,
                  'sha256': hashlib.sha256(binding[key].casefold().encode('utf-8', 'replace')).hexdigest() if key in binding else None,
                  'matches_worker_profile': key in binding and binding[key].casefold() == expected[key].casefold()}
            for key in PROFILE_BINDING_KEYS}
    del binding
    return {'source': 'win._worker_token + win._worker_environment(token, None, limits=limits) with the worker profile loaded',
            'variable_count': len(names), 'flagged_names_pattern': ENV_NAME_PATTERN.pattern,
            'flagged_names': flagged[:MAX_LISTED], 'flagged_names_expected': [], 'flagged_names_absent': not flagged,
            'profile_binding': rows, 'profile_binding_verified': all(row['matches_worker_profile'] for row in rows.values()),
            'values_recorded': False}


def attest_environment(win, identity, expected_sid, limits, profile):
    """Build the exact launch environment as SYSTEM without starting any process."""
    api = win._api()
    C.set_last_error(0)
    lock = api['kernel32'].CreateMutexW(None, False, 'Global\\CoChemPipeline422-' + expected_sid)
    win._check(lock, 'Reserve exclusive worker identity for the attestation')
    if C.get_last_error() == 183:
        win._close(lock)
        raise ValueError('The worker identity already has an active supervised process')
    token, info = None, None
    try:
        token = win._worker_token(identity)
        info = win._PROFILEINFOW(dwSize=C.sizeof(win._PROFILEINFOW), dwFlags=1, lpUserName=identity.name)
        win._check(api['userenv'].LoadUserProfileW(token, C.byref(info)), 'Load worker profile for the attestation')
        block = win._worker_environment(token, None, limits=limits)
        text = block[:]
        del block
        result = environment_names(text, profile)
        del text
        return result
    finally:
        try:
            if info is not None and info.hProfile:
                win._check(api['userenv'].UnloadUserProfile(token, info.hProfile), 'Unload attestation profile')
        finally:
            if token:
                win._close(token)
            win._close(lock)


# ----- launches -----

def read_raw(path, maximum=RAW_FILE_MAXIMUM):
    """Bounded read of one private raw capture (the child has exited and its Job is closed)."""
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('A raw capture exceeds its byte bound')
    return data


def redact(data):
    """Replace account- or credential-looking spans; returns (bytes, {pattern name: count})."""
    counts = {}
    for name, pattern, replacement in SENSITIVE_PATTERNS:
        data, count = pattern.subn(replacement, data)
        if count:
            counts[name] = count
    return data, counts


def sensitive_scan(data):
    """Pattern NAMES found in a raw stream (never the values)."""
    return sorted(redact(data)[1])


def raw_digest(path):
    data = read_raw(path)
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'sensitive_patterns': sensitive_scan(data)}


def write_replay(replay, run_id, stdout_path, stderr_path):
    """The G5 replay copy of one run: redacted stdout/stderr written CreateNew next to the raw root."""
    sources = {'stdout': read_raw(stdout_path), 'stderr': read_raw(stderr_path)}
    if any(len(data) > RUN_OUTPUT for data in sources.values()):
        return {'available': False, 'reason': 'raw_stream_over_bound'}
    copies = {}
    for stream, data in sources.items():
        redacted, counts = redact(data)
        if sensitive_scan(redacted):
            return {'available': False, 'reason': 'redaction_incomplete'}
        copies[stream] = (redacted, counts)
    result = {'available': True, 'reason': None}
    for stream, (redacted, counts) in copies.items():
        path = replay / f'{run_id}.{stream}'
        with path.open('xb') as handle:
            handle.write(redacted)
            handle.flush()
            os.fsync(handle.fileno())
        result[stream] = {'path': f'replay/{path.name}', 'bytes': len(redacted),
                          'sha256': hashlib.sha256(redacted).hexdigest(), 'redactions': counts}
    return result


def assert_inference_argv(argv):
    """The evidenced argv must equal the production argv form: no prompt flag, no extra native bound."""
    template = list(PRODUCTION_ARGUMENTS)
    model_index = template.index('{model}')
    arguments = list(argv[1:])
    if (not argv or argv[0] != str(EXECUTABLE) or len(arguments) < len(template)
            or arguments[:model_index] != template[:model_index]
            or arguments[model_index + 1:len(template)] != template[model_index + 1:]
            or not MODEL_PATTERN.fullmatch(arguments[model_index])
            or arguments[len(template):] not in ([], ['--effort', 'high'])
            or any(arg.split('=', 1)[0] in FORBIDDEN_FLAGS for arg in arguments)):
        raise ValueError('Inference argv differs from the reviewed production form')


def inference_argv(model, extra):
    argv = [str(EXECUTABLE), *[model if arg == '{model}' else arg for arg in PRODUCTION_ARGUMENTS], *extra]
    assert_inference_argv(argv)
    return argv


def deliver_prompt(writer):
    """Write the single NDJSON line and close the pipe (EOF ends the session after the turn)."""
    total, error = 0, None
    try:
        while total < len(PROMPT_LINE):
            total += os.write(writer, PROMPT_LINE[total:])
    except OSError as exc:
        error = re.sub('[^A-Za-z0-9_]', '', type(exc).__name__)[:80]
    finally:
        os.close(writer)
    return total, error


def run_probe(win, identity, probe_id, arguments, kind, cwd, raw, limits, expected_sid, profile_sha256, record, prefix=''):
    argv = [str(EXECUTABLE), *arguments]
    stdout_path, stderr_path, stdin_path = (raw / (prefix + probe_id + suffix) for suffix in ('.stdout', '.stderr', '.stdin'))
    record.update(id=probe_id, argv=argv, kind=kind, stdin_mode='empty_file', bound_seconds=PROBE_SECONDS,
                  output_limit_bytes=PROBE_OUTPUT, stdin_bytes_written=0,
                  raw_path={'stdout': 'raw/' + stdout_path.name, 'stderr': 'raw/' + stderr_path.name}, cleanup_verified=False,
                  phase_reached='precheck_launch')
    stdin_path.open('xb').close()
    record['stdin_sha256'] = digest_file(stdin_path, 0)
    with stdout_path.open('xb') as output, stderr_path.open('xb') as errors:
        with stdin_path.open('rb') as stdin:
            process = launch_native_process(win, identity, argv, cwd, stdin, output, errors, limits)
        started = time.monotonic()
        with process:
            record['phase_reached'] = 'native_attestation'
            record['process'] = observe_child(win, process, expected_sid, EXECUTABLE)
            record['process']['native_resource_limits'] = process.resource_limits_evidence
            record['process']['profile_matches_inventory_root'] = record['process']['profile_directory_sha256'] == profile_sha256
            if not record['process']['profile_matches_inventory_root']:
                raise ValueError('Observed worker profile differs from the inventoried profile')
            record['phase_reached'] = 'precheck_wait'
            outcome, code = wait_bounded(process, output, errors, PROBE_SECONDS, PROBE_OUTPUT)
            record['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            record['phase_reached'] = 'native_cleanup'
            # Recorded for every probe as the observed baseline of agy's own tree (not a gate input).
            record['job_accounting'] = job_process_accounting(win, process)
        record['cleanup_verified'] = True
    record['phase_reached'] = 'precheck_result'
    record['outcome'] = outcome
    record['exit_code'] = code if outcome == 'exited' else 'terminated'
    record['stdout'], record['stderr'] = raw_digest(stdout_path), raw_digest(stderr_path)
    with stdout_path.open('rb') as handle:
        stdout = handle.read(PROBE_OUTPUT + 1)
    with stderr_path.open('rb') as handle:
        stderr = handle.read(PROBE_OUTPUT + 1)
    record['classification'] = classify_probe(kind, stdout, stderr, outcome, record['exit_code'])
    del stdout, stderr
    return record


def run_inference(win, identity, run_id, model, extra, cwd, raw, limits, expected_sid, profile_sha256,
                  agent_records, protocol, record, replay=None):
    """One bounded stream-json run: one NDJSON line on a pipe, EOF, 120 s / 1 MiB, Job end on block exit."""
    argv = inference_argv(model, extra)
    stdout_path, stderr_path, stdin_path = (raw / (run_id + suffix) for suffix in ('.stdout', '.stderr', '.stdin'))
    record.update(id=run_id, requested_model=model, extra_arguments=list(extra), argv=argv,
                  stdin_mode='pipe_one_ndjson_line_then_eof', bound_seconds=RUN_SECONDS, output_limit_bytes=RUN_OUTPUT,
                  stdin_bytes_written=0, prompt_delivered=False, stdin_write_error=None,
                  raw_path={'stdout': 'raw/' + stdout_path.name, 'stderr': 'raw/' + stderr_path.name, 'stdin': 'raw/' + stdin_path.name},
                  cleanup_verified=False, phase_reached='inference_launch')
    with stdin_path.open('xb') as stream:
        stream.write(PROMPT_LINE)
    record['stdin_sha256'] = digest_file(stdin_path, len(PROMPT_LINE))
    if record['stdin_sha256'] != PROMPT_LINE_SHA256:
        raise ValueError('The prompt line differs from its reviewed bytes')
    record['agent_sha256_before_launch'] = verify_staged_agent(win, agent_records, expected_sid)
    writer = None
    with stdout_path.open('xb') as output, stderr_path.open('xb') as errors:
        try:
            read_end, writer = os.pipe()
            with os.fdopen(read_end, 'rb', buffering=0) as stdin:
                process = launch_native_process(win, identity, argv, cwd, stdin, output, errors, limits)
            started = time.monotonic()
            with process:
                record['phase_reached'] = 'native_attestation'
                record['process'] = observe_child(win, process, expected_sid, EXECUTABLE)
                record['process']['native_resource_limits'] = process.resource_limits_evidence
                record['process']['profile_matches_inventory_root'] = record['process']['profile_directory_sha256'] == profile_sha256
                if not record['process']['profile_matches_inventory_root']:
                    raise ValueError('Observed worker profile differs from the inventoried profile')
                record['phase_reached'] = 'inference_wait'
                pending, writer = writer, None
                record['stdin_bytes_written'], record['stdin_write_error'] = deliver_prompt(pending)
                record['prompt_delivered'] = record['stdin_bytes_written'] == len(PROMPT_LINE)
                outcome, code = wait_bounded(process, output, errors, RUN_SECONDS, RUN_OUTPUT)
                record['elapsed_ms'] = int((time.monotonic() - started) * 1000)
                record['phase_reached'] = 'native_cleanup'
                record['job_accounting'] = job_process_accounting(win, process)
            # Leaving the block closed the owned Job: descendants ended, profile unloaded.
            record['cleanup_verified'] = True
        finally:
            if writer is not None:
                os.close(writer)  # Never written: the launch or the attestation failed first.
    record['phase_reached'] = 'inference_result'
    record['outcome'] = outcome
    record['exit_code'] = code if outcome == 'exited' else 'terminated'
    record['terminated_by_bound'] = outcome != 'exited'
    record['stdout'], record['stderr'] = raw_digest(stdout_path), raw_digest(stderr_path)
    record['agent_sha256_after_run'] = verify_staged_agent(win, agent_records, expected_sid)
    with stdout_path.open('rb') as handle:
        stdout = handle.read(RUN_OUTPUT + 1)
    with stderr_path.open('rb') as handle:
        stderr = handle.read(RUN_OUTPUT + 1)
    record['classification'] = classify_run(stdout, stderr, outcome, record['exit_code'], model, protocol)
    del stdout, stderr
    record['checks'] = run_checks(record, model)
    if replay is not None:
        record['phase_reached'] = 'replay'
        record['replay'] = write_replay(replay, run_id, stdout_path, stderr_path)
        record['phase_reached'] = 'inference_result'
    return record


# ----- receipt -----

def bounded_receipt_text(report):
    text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    if len(text.encode('ascii')) <= RECEIPT_MAX_BYTES:
        return text
    for key in ('slot1_inventory_before', 'slot1_inventory_after'):
        snapshot = report.get(key)
        if isinstance(snapshot, dict):
            for tree in snapshot.get('trees', {}).values():
                tree['entries'] = []
                tree['entries_omitted_for_receipt_bound'] = True
    report['inventory_entries_omitted_for_receipt_bound'] = True
    text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    if len(text.encode('ascii')) > RECEIPT_MAX_BYTES:
        workspace_rows = [row for workspace in report.get('workspaces') or []
                          for rows in (workspace.get('paths', []), *(item.get('paths', []) for item in workspace.get('ancestors', [])))
                          for row in rows]
        for row in [row for profile in report.get('profiles') or [] for row in profile.get('paths', [])] + workspace_rows:
            if 'entries' in row:
                row['entries'] = []
                row['entries_omitted_for_receipt_bound'] = True
        report['profile_entries_omitted_for_receipt_bound'] = True
        text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    if len(text.encode('ascii')) > RECEIPT_MAX_BYTES:
        for item in [report, *(report.get('runs') or []), *(report.get('slots') or [])]:
            for key in ('staging_changes', 'precheck_changes', 'profile_changes'):
                if isinstance(item.get(key), dict):
                    item[key] = {name: [] for name in ('new_files', 'changed_files', 'removed_files', 'new_directories')}
                    item[key]['omitted_for_receipt_bound'] = True
        report['inventory_changes_omitted_for_receipt_bound'] = True
        text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    return text


def ram_workspace_root(config, slot):
    ramdisk = config.get('ramdisk')
    if not isinstance(ramdisk, dict) or ramdisk.get('enabled') is not True:
        return None
    mount, subdirectory = ramdisk.get('mount_root'), ramdisk.get('workspace_subdirectory') or ''
    if (not isinstance(mount, str) or not re.fullmatch(r'[A-Za-z]:\\', mount)
            or not isinstance(subdirectory, str) or (subdirectory and not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', subdirectory))):
        raise ValueError('RAM workspace configuration is not the reviewed drive-root form')
    return Path(mount) / subdirectory / slot if subdirectory else Path(mount) / slot


def count_jobs(report):
    report['model_jobs_executed'] = sum(1 for item in report['runs'] if item.get('prompt_delivered') is True)
    report['answers_produced'] = sum(1 for item in report['runs'] if item.get('checks', {}).get('result_success') is True)


def common_report(mode, schema, nonce, attempt, helper_sha256, system_sid):
    return {'schema': schema, 'mode': mode, 'attempt': attempt, 'nonce': nonce,
            'status': 'UNVERIFIED', 'system_sid': system_sid, 'started_at_unix_ms': int(time.time() * 1000),
            'helper_sha256': helper_sha256, 'runtime_root': str(INSTALL),
            'install_receipt_sha256': INSTALL_RECEIPT_SHA256, 'source_manifest_sha256': MANIFEST_SHA256,
            'resource_limits_sha256': RESOURCE_SHA256, 'windows_runtime_sha256': WINDOWS_SHA256,
            'layout_sha256': None, 'config_sha256': None, 'revision': None,
            'native_executable': str(EXECUTABLE), 'native_executable_sha256_before': None,
            'native_executable_sha256_after': None, 'native_version_at_pin': AGY_VERSION,
            'bounds': {'probe_seconds': PROBE_SECONDS, 'probe_output_bytes': PROBE_OUTPUT, 'run_seconds': RUN_SECONDS,
                       'run_output_bytes': RUN_OUTPUT, 'deadline_seconds': DEADLINE_SECONDS,
                       'launch_overhead_seconds': LAUNCH_OVERHEAD_SECONDS,
                       'cleanup_margin_seconds': CLEANUP_MARGIN_SECONDS, 'task_execution_time_limit': 'PT10M'},
            'production_argument_template': list(PRODUCTION_ARGUMENTS), 'production_arguments_validated': False,
            'model_jobs_executed': 0, 'answers_produced': 0, 'cleanup_verified': False,
            'runtime_custody_verified': False, 'require_stopped_before': False, 'require_stopped_after': False,
            'daemon_states_verified_before_and_after': False, 'profiles': [], 'gate': None,
            'raw_capture_paths': [], 'raw_output_access': 'SYSTEM and BUILTIN\\Administrators only (inherited from the private evidence root)',
            'raw_output_publication': 'never', 'raw_sensitive_patterns_found': [],
            'owner_credentials_read': False, 'token_files_opened': 0, 'raw_output_published': False,
            'login_inputs_written': 0, 'pipeline_started': False}


def new_report(slot, nonce, attempt, helper_sha256, system_sid, effort_null_slug=DEFAULT_EFFORT_NULL_SLUG):
    matrix = run_matrix(effort_null_slug)
    report = common_report('evidence', 'cochem-agy-isolation-evidence/1', nonce, attempt, helper_sha256, system_sid)
    report.update({
        'slot': slot, 'gemini_gate': 'G3', 'effort_null_slug': effort_null_slug, 'primary_model': PRIMARY_MODEL,
        'prompt_line_sha256': PROMPT_LINE_SHA256, 'prompt_line_bytes': len(PROMPT_LINE),
        'stderr_markers_scanned': list(STDERR_MARKERS),
        'precheck_planned': [probe_id for probe_id, _, _ in PRECHECK],
        'runs_planned': [{'id': run_id, 'requested_model': model, 'extra_arguments': list(extra), 'purpose': purpose}
                         for run_id, model, extra, purpose in matrix],
        'worker_identity': None, 'profile_root': None, 'slot_root': None, 'ram_workspace_root': None,
        'agent': {'name': AGENT_NAME, 'source_sha256': AGENT_SHA256, 'frontmatter': None, 'staged': [],
                  'shadow_locations_checked': [], 'shadows_found': [], 'verified_before_each_launch': False},
        'workspaces': [], 'environment_attestation': None, 'programdata_antigravity': None,
        'job_expected_processes_maximum': JOB_EXPECTED_PROCESSES_MAXIMUM,
        'precheck': {'probes': [], 'passed': False, 'reasons': []}, 'runs': [], 'runs_skipped': [],
        'isolation_verdict': None, 'identity_verdict': None, 'replay_streams': {},
        'slot1_inventory_before': None, 'slot1_inventory_after': None, 'staging_changes': None, 'precheck_changes': None})
    return report


def new_stage_report(nonce, attempt, helper_sha256, system_sid):
    report = common_report('stage', 'cochem-agy-agent-staging/1', nonce, attempt, helper_sha256, system_sid)
    report.update({
        'gemini_gate': 'G4', 'slots_planned': list(STAGE_SLOTS),
        'listing_probes_planned': [{'id': probe_id, 'arguments': list(arguments)} for probe_id, arguments, _ in STAGE_PROBES],
        'agent': {'name': AGENT_NAME, 'source_sha256': AGENT_SHA256, 'bytes': AGENT_BYTES, 'frontmatter': None,
                  'destinations': ['/'.join(parts) for parts in AGENT_DESTINATION_PARTS],
                  'file_acl_sddl_template': AGENT_FILE_SDDL, 'directory_acl_sddl_template': AGENT_DIRECTORY_SDDL,
                  'parent_destinations': list(AGENT_PARENT_RELATIVES),
                  'parent_acl_sddl_template': AGENT_PARENT_DIRECTORY_SDDL},
        'slots': [], 'slots_skipped': [], 'isolation_inventory_clear': None, 'programdata_antigravity': None})
    return report


def fits_deadline(deadline, bound, launches=1):
    """A launch starts only while its worst case (overhead, bound, close allowance) fits the deadline."""
    return time.monotonic() + launches * (LAUNCH_OVERHEAD_SECONDS + bound + CLEANUP_MARGIN_SECONDS) <= deadline


def evidence_root(mode, attempt):
    return EVIDENCE_BASE / (f'{ROOT_PREFIX}{attempt}' + (STAGE_ROOT_SUFFIX if mode == 'stage' else ''))


def reserve_native_setup(win):
    C.set_last_error(0)
    lock = win._api()['kernel32'].CreateMutexW(None, False, 'Global\\CoChem427-NativeStatusSetup')
    win._check(lock, 'Reserve exclusive native status check')
    if C.get_last_error() == 183:
        win._close(lock)
        raise ValueError('Another native status check owns the reservation')
    return lock


def bind_custody(win, agy_protocol, report, state):
    """Shared r4 custody, layout, boundary and native checks; nothing is changed here."""
    from cochem_pipeline.resource_limits import ResourceLimits
    from cochem_pipeline.ramdisk import ordinary_tree
    state['phase'] = 'runtime_custody'
    validate_interpreter()
    if digest_file(Path(win.__file__)) != WINDOWS_SHA256:
        raise ValueError('Installed Windows launch implementation differs from the reviewed pin')
    report['revision'] = verify_r4_runtime(win, INSTALL_RECEIPT_SHA256)
    agy_protocol.validate_arguments(list(PRODUCTION_ARGUMENTS))
    if agy_protocol.encode_prompt(PROMPT).encode('utf-8') != PROMPT_LINE:
        raise ValueError('The prompt line differs from the production encoder')
    report['production_arguments_validated'] = True
    state['phase'] = 'layout'
    layout, layout_hash = protected_json(win, INSTALL / 'windows-layout.json')
    config, config_hash = protected_json(win, INSTALL / 'pipeline.json')
    if layout_hash != LAYOUT_SHA256 or config_hash != CONFIG_SHA256:
        raise ValueError('Exact r4 layout/configuration binding differs')
    expected_slots = set(STAGE_SLOTS)
    if (set(layout['slots']) != expected_slots or set(config['workers']) != expected_slots
            or set(config['slot_roots']) != expected_slots or config.get('max_execution_slots') != 4
            or layout['private_root'] != config['private_root']
            or layout['operator_name'] != config['operator_name']):
        raise ValueError('Protected layout differs from the reviewed six-identity/four-slot configuration')
    for key in expected_slots:
        row = layout['slots'][key]
        worker = config['workers'][key]
        if (row['identity'] != worker['name'] or row['credential_target'] != worker['credential_target']
                or row['root'] != config['slot_roots'][key]
                or worker['name'] != 'CoChem422Worker' + key[4:]
                or worker['credential_target'] != 'CoChem422/' + key):
            raise ValueError('Installed identity mapping differs between layout and configuration')
    state['phase'] = 'boundaries'
    private = Path(config['private_root'])
    ordinary_tree(private)
    win.validate_private_directory(private)
    identities = {key: win.WorkerIdentity(row['name'], row['credential_target'])
                  for key, row in config['workers'].items()}
    private, roots = win._layout_paths(private, config['slot_roots'], identities)
    boundaries = win._layout_boundaries(private, roots)
    win._validate_control_ancestors(boundaries[0].parent)
    worker_sids = [win._sid_text(win._account_sid(value.name)) for value in identities.values()]
    for boundary in boundaries:
        win._validate_boundary(boundary, worker_sids)
    state['phase'] = 'native_custody'
    if Path(config['providers']['gemini']['executable']) != EXECUTABLE:
        raise ValueError('Protected provider path differs from the reviewed native executable')
    ordinary_tree(EXECUTABLE)
    win.validate_code_path(EXECUTABLE)
    before = digest_file(EXECUTABLE)
    if before != AGY_SHA256:
        raise ValueError('Native executable differs from the reviewed agy pin')
    report.update(layout_sha256=layout_hash, config_sha256=config_hash,
                  native_executable_sha256_before=before, runtime_custody_verified=True)
    return SimpleNamespace(layout=layout, config=config, limits=ResourceLimits.from_dict(config['execution_limits']),
                           before=before)


def bind_slot(win, layout, config, slot):
    spec = layout['slots'][slot]
    identity = win.WorkerIdentity(spec['identity'], spec['credential_target'])
    sid = win._sid_text(win._account_sid(identity.name))
    if sid != spec['sid']:
        raise ValueError('Provisioned worker SID changed')
    profile = PROFILE_PARENT / identity.name
    return SimpleNamespace(identity=identity, sid=sid, profile=profile, slot_root=Path(spec['root']),
                           ram_root=ram_workspace_root(config, slot),
                           profile_sha256=hashlib.sha256(str(profile).casefold().encode()).hexdigest())


def finish_custody(win, ctx, report, state):
    """Post-loop: the native binary unchanged and the four daemon tasks still stopped and disabled."""
    state['phase'] = 'native_custody'
    after = digest_file(EXECUTABLE)
    report['native_executable_sha256_after'] = after
    if after != ctx.before:
        raise ValueError('Native executable changed during the evidence run')
    state['phase'] = 'daemon_postcheck'
    require_stopped(win)
    report['require_stopped_after'] = True
    report['daemon_states_verified_before_and_after'] = True


def collect_evidence(win, agy_protocol, ctx, report, state, launched, deadline, root, raw, replay, matrix):
    """Mode 'evidence': slot1 staging, inventories, attestation, pre-check, then R1, R5, R2, R3, R4."""
    slot = bind_slot(win, ctx.layout, ctx.config, report['slot'])
    identity, expected_sid, profile, slot_root, ram_root = slot.identity, slot.sid, slot.profile, slot.slot_root, slot.ram_root
    report['worker_identity'] = identity.name
    report['slot_root'], report['ram_workspace_root'] = str(slot_root), (str(ram_root) if ram_root is not None else None)
    state['phase'] = 'daemon_precheck'
    require_stopped(win)
    report['require_stopped_before'] = True
    state['phase'] = 'inventory_before'
    ordinary_root(profile)
    report['profile_root'] = str(profile)
    snapshot = report['slot1_inventory_before'] = slot_inventory(profile, slot_root)
    state['phase'] = 'agent_staging'
    win._enable_system_privileges()
    agent_source = root / AGENT_FILE_NAME
    report['agent']['frontmatter'] = validate_agent_definition(agent_source.read_bytes())
    agent_records = report['agent']['staged'] = stage_agent(win, agent_source, profile, expected_sid)
    staged = slot_inventory(profile, slot_root)
    report['staging_changes'] = inventory_changes(snapshot, staged)
    snapshot = staged
    workspaces = (('slot_root', slot_root), ('ram_workspace', ram_root))
    checked, shadows = shadow_check(profile, workspaces)
    report['agent']['shadow_locations_checked'], report['agent']['shadows_found'] = checked, shadows
    state['phase'] = 'profile_inventory'
    report['profiles'] = six_profile_inventory(ctx.layout['slots'], PROFILE_PARENT)
    report['workspaces'] = [workspace_inventory(label, path) for label, path in workspaces]
    # O-F2: read-only here (never created by the evidence mode); checked again after the runs.
    report['programdata_antigravity'] = {'path': str(PROGRAMDATA_ANTIGRAVITY), 'before': programdata_antigravity_state(win),
                                         'after': None, 'clear': False}
    state['phase'] = 'environment_attestation'
    report['environment_attestation'] = attest_environment(win, identity, expected_sid, ctx.limits, profile)
    for probe_id, arguments, kind in PRECHECK:
        if not fits_deadline(deadline, PROBE_SECONDS):
            raise TimeoutError('The helper deadline does not leave room for the pre-check')
        state['phase'] = 'agent_verification'
        verify_staged_agent(win, agent_records, expected_sid)
        state['phase'] = 'precheck_launch'
        record = {}
        report['precheck']['probes'].append(record)
        launched.append(record)
        run_probe(win, identity, probe_id, arguments, kind, str(slot_root), raw, ctx.limits, expected_sid,
                  slot.profile_sha256, record)
    state['phase'] = 'precheck_result'
    report['agent']['verified_before_each_launch'] = True
    after_precheck = slot_inventory(profile, slot_root)
    report['precheck_changes'] = inventory_changes(snapshot, after_precheck)
    snapshot = after_precheck
    report['precheck'].update(precheck_decision(report['precheck']['probes'], report['agent']['shadows_found']))
    deadline_skipped = False
    if not report['precheck']['passed']:
        report['runs_skipped'] = [{'id': run_id, 'reason': 'PRECHECK_REFUSED'} for run_id, _, _, _ in matrix]
    else:
        for index, (run_id, model, extra, _) in enumerate(matrix):
            if not fits_deadline(deadline, RUN_SECONDS):
                report['runs_skipped'] = [{'id': item[0], 'reason': 'DEADLINE'} for item in matrix[index:]]
                deadline_skipped = True
                break
            state['phase'] = 'inference_launch'
            record = {}
            report['runs'].append(record)
            launched.append(record)
            run_inference(win, identity, run_id, model, extra, str(slot_root), raw, ctx.limits, expected_sid,
                          slot.profile_sha256, agent_records, agy_protocol, record, replay)
            state['phase'] = 'inference_result'
            current = slot_inventory(profile, slot_root)
            record['profile_changes'] = inventory_changes(snapshot, current)
            record['log_scan'] = scan_run_logs(profile, record['profile_changes'])
            snapshot = current
            if record['checks']['isolation_breach']:
                # A tool-bearing or delegating agent ends the isolation path (Decision 4): no further answers.
                report['runs_skipped'] = [{'id': item[0], 'reason': 'ISOLATION_BREACH_STOP'} for item in matrix[index + 1:]]
                break
    # O-F4: runs the deadline guard skipped after R1 passed keep the evidence complete; the gate then rests on R1 and the
    # skipped runs stay executed false (the builder binds the R1 slug and leaves effort-null and extended unbound).
    r1 = next((item for item in report['runs'] if item.get('id') == 'R1'), None)
    complete = not deadline_skipped or (isinstance(r1, dict) and r1.get('checks', {}).get('passes_contract') is True)
    count_jobs(report)
    report['cleanup_verified'] = all(item.get('cleanup_verified') is True for item in launched)
    state['phase'] = 'inventory_after'
    report['slot1_inventory_after'] = slot_inventory(profile, slot_root)
    guard = report['programdata_antigravity']
    guard['after'] = programdata_antigravity_state(win)
    guard['clear'] = guard['before']['clear'] is True and guard['after']['clear'] is True
    state['phase'] = 'agent_verification'
    verify_staged_agent(win, agent_records, expected_sid)
    finish_custody(win, ctx, report, state)
    state['phase'] = 'verdict'
    if not report['precheck']['passed']:
        report['status'] = 'EVIDENCE_PRECHECK_REFUSED'
    else:
        report['status'] = 'EVIDENCE_COMPLETE' if complete and report['cleanup_verified'] else 'EVIDENCE_INCOMPLETE'


def stage_slots(win, ctx, report, state, launched, deadline, root, raw):
    """Mode 'stage': the pinned agent into all six profiles at both locations, then the listing probes."""
    state['phase'] = 'daemon_precheck'
    require_stopped(win)
    report['require_stopped_before'] = True
    state['phase'] = 'agent_staging'
    win._enable_system_privileges()
    agent_source = root / AGENT_FILE_NAME
    report['agent']['frontmatter'] = validate_agent_definition(agent_source.read_bytes())
    # O-F2: before any profile is touched, C:\ProgramData\Antigravity becomes (or must already be) the protected empty
    # folder; any other state is refused and preserved for review, and no slot is staged or launched.
    state['phase'] = 'programdata_guard'
    guard = report['programdata_antigravity'] = protect_programdata_antigravity(win)
    if guard['clear'] is not True:
        raise ValueError('C:\\ProgramData\\Antigravity exists with content or a weaker ACL; preserve it for review')
    state['phase'] = 'profile_inventory'
    report['profiles'] = six_profile_inventory(ctx.layout['slots'], PROFILE_PARENT)
    flags = [profile['flags'] for profile in report['profiles']]
    report['isolation_inventory_clear'] = (len(flags) == 6 and not any(
        flag[key] for flag in flags for key in ('hooks_present', 'mcp_present', 'plugins_present', 'skills_present')))
    complete = True
    for index, slot_name in enumerate(STAGE_SLOTS):
        if not fits_deadline(deadline, PROBE_SECONDS, len(STAGE_PROBES)):
            report['slots_skipped'] = [{'slot': name, 'reason': 'DEADLINE'} for name in STAGE_SLOTS[index:]]
            complete = False
            break
        slot = bind_slot(win, ctx.layout, ctx.config, slot_name)
        entry = {'slot': slot_name, 'identity': slot.identity.name, 'profile_root': str(slot.profile),
                 'slot_root': str(slot.slot_root), 'ram_workspace_root': str(slot.ram_root) if slot.ram_root is not None else None,
                 'staged': [], 'shadow_locations_checked': [], 'shadows_found': [], 'staging_changes': None,
                 'probes': [], 'agent_sha256_after_listing': None, 'listing': None}
        report['slots'].append(entry)
        state['phase'] = 'agent_staging'
        report['failure_slot'] = slot_name
        ordinary_root(slot.profile)
        before = slot_inventory(slot.profile, slot.slot_root)
        entry['staged'] = stage_agent(win, agent_source, slot.profile, slot.sid, protect_parents=True)
        entry['staging_changes'] = inventory_changes(before, slot_inventory(slot.profile, slot.slot_root))
        checked, shadows = shadow_check(slot.profile, (('slot_root', slot.slot_root), ('ram_workspace', slot.ram_root)))
        entry['shadow_locations_checked'], entry['shadows_found'] = checked, shadows
        for probe_id, arguments, kind in STAGE_PROBES:
            state['phase'] = 'agent_verification'
            verify_staged_agent(win, entry['staged'], slot.sid)
            state['phase'] = 'stage_listing'
            record = {}
            entry['probes'].append(record)
            launched.append(record)
            run_probe(win, slot.identity, probe_id, arguments, kind, str(slot.slot_root), raw, ctx.limits, slot.sid,
                      slot.profile_sha256, record, prefix=slot_name + '-')
        state['phase'] = 'agent_verification'
        entry['agent_sha256_after_listing'] = verify_staged_agent(win, entry['staged'], slot.sid)
        entry['listing'] = {'passed': not listing_reasons(entry['probes']), 'reasons': listing_reasons(entry['probes'])}
        report.pop('failure_slot', None)
    report['cleanup_verified'] = all(item.get('cleanup_verified') is True for item in launched)
    state['phase'] = 'programdata_guard'
    guard['after_listing'] = programdata_antigravity_state(win)
    guard['clear'] = guard['after_listing']['state'] == 'PROTECTED_EMPTY'
    if guard['clear'] is not True:
        raise ValueError('C:\\ProgramData\\Antigravity changed during the staging; preserve it for review')
    finish_custody(win, ctx, report, state)
    state['phase'] = 'verdict'
    report['status'] = 'STAGING_COMPLETE' if complete and report['cleanup_verified'] else 'STAGING_INCOMPLETE'


def failure_phase(win, exc, state, launched):
    if isinstance(exc, win.WindowsCleanupError):
        return 'native_cleanup'
    phase = state['phase']
    if phase in LAUNCH_PHASES and launched and launched[-1].get('phase_reached') in FAILURE_PHASES:
        return launched[-1]['phase_reached']
    return phase


def run(mode, slot, nonce, attempt, effort_null_slug=DEFAULT_EFFORT_NULL_SLUG):
    if mode not in MODES:
        raise ValueError('Only the evidence and stage modes are reviewed')
    if not re.fullmatch(r'[a-f0-9]{32}', str(attempt)) or attempt == '0' * 32:
        raise ValueError('A nonzero lowercase 32-hex explicit attempt is required')
    if not re.fullmatch(r'[a-f0-9]{32}', str(nonce)):
        raise ValueError('A 32-hex nonce is required')
    if mode == 'evidence':
        if slot not in SLOTS:
            raise ValueError('Only slot1 runs the model-form matrix')
        matrix = run_matrix(effort_null_slug)
    elif slot is not None or effort_null_slug != DEFAULT_EFFORT_NULL_SLUG:
        raise ValueError('The stage mode covers all six slots and takes no slot or model')
    from cochem_pipeline import windows as win
    from cochem_pipeline import agy_protocol
    from cochem_pipeline.ramdisk import ordinary_tree
    win.require_system()
    root = evidence_root(mode, attempt)
    if Path(__file__).resolve() != root / HELPER_NAME or current_executable() != PYTHON:
        raise ValueError('Use only the reviewed protected helper and installed interpreter')
    agent_source = root / AGENT_FILE_NAME
    for path in (root, Path(__file__), agent_source, PYTHON, Path(win.__file__)):
        ordinary_tree(path)
        win.validate_code_path(path)
    win.validate_private_directory(root)
    helper_sha256 = digest_file(Path(__file__))
    if mode == 'evidence':
        report = new_report(slot, nonce, attempt, helper_sha256, win.SYSTEM_SID, effort_null_slug)
    else:
        report = new_stage_report(nonce, attempt, helper_sha256, win.SYSTEM_SID)
    with (root / RECEIPT_NAMES[mode]).open('x', encoding='ascii') as receipt:
        state, lock, deadline, launched = {'phase': 'reservation'}, None, time.monotonic() + DEADLINE_SECONDS, []
        try:
            lock = reserve_native_setup(win)
            ctx = bind_custody(win, agy_protocol, report, state)
            raw = root / 'raw'
            raw.mkdir()
            win.validate_private_directory(raw)
            if mode == 'evidence':
                replay = root / 'replay'
                replay.mkdir()
                win.validate_private_directory(replay)
                collect_evidence(win, agy_protocol, ctx, report, state, launched, deadline, root, raw, replay, matrix)
            else:
                stage_slots(win, ctx, report, state, launched, deadline, root, raw)
        except BaseException as exc:
            report['status'] = 'EVIDENCE_FAILED' if mode == 'evidence' else 'STAGING_FAILED'
            # Exception messages may contain native output; disclose a fixed classification only.
            report['failure_kind'] = ('cleanup_unverified' if isinstance(exc, win.WindowsCleanupError)
                                      else 'timeout' if isinstance(exc, TimeoutError) else 'verification_failed')
            report['operator_review_required'] = True
            report['failure'] = safe_failure(exc, failure_phase(win, exc, state, launched))
            report['cleanup_verified'] = False
            if mode == 'evidence':
                count_jobs(report)
                if report['slot1_inventory_before'] is not None and report['slot1_inventory_after'] is None:
                    try:  # Read-only evidence of what the steps that did run left behind.
                        report['slot1_inventory_after'] = slot_inventory(PROFILE_PARENT / report['worker_identity'], Path(report['slot_root']))
                    except BaseException as error:
                        report['slot1_inventory_after_error'] = re.sub('[^A-Za-z0-9_]', '', type(error).__name__)[:80]
        finally:
            if lock:
                win._close(lock)
            try:
                if mode == 'evidence':
                    report['isolation_verdict'] = isolation_verdict(report['runs'], report['profiles'], report['workspaces'],
                                                                    report['programdata_antigravity'])
                    report['identity_verdict'] = identity_verdict(report['runs'], matrix, effort_null_slug, report['runs_skipped'])
                    report['gate'] = isolation_gate(report['status'], report['precheck'], report['runs'], report['isolation_verdict'])
                    report['replay_streams'] = {item['id']: dict(item['replay'], requested_model=item['requested_model'],
                                                                 extra_arguments=item['extra_arguments'],
                                                                 exit_code=item.get('exit_code'), outcome=item.get('outcome'))
                                                for item in report['runs'] if isinstance(item.get('replay'), dict)}
                else:
                    report['gate'] = staging_gate(report['status'], report['slots'])
            except BaseException:
                report['gate'] = {'passed': False, 'reasons': ['EVIDENCE_NOT_COMPLETE' if mode == 'evidence' else 'STAGING_NOT_COMPLETE']}
            report['raw_capture_paths'] = sorted(path for item in launched for path in (item.get('raw_path') or {}).values())
            report['raw_sensitive_patterns_found'] = sorted({name for item in launched for stream in ('stdout', 'stderr')
                                                             for name in (item.get(stream) or {}).get('sensitive_patterns', [])})
            report['finished_at_unix_ms'] = int(time.time() * 1000)
            receipt.write(bounded_receipt_text(report))
            receipt.flush()
            os.fsync(receipt.fileno())
    return 0 if report['status'] in PASSING_STATUSES else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=list(MODES), required=True)
    parser.add_argument('--slot', choices=list(SLOTS))
    parser.add_argument('--effort-null-slug', choices=list(EFFORT_NULL_SLUGS))
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{32}', args.nonce):
        parser.error('A 32-hex one-shot receipt nonce is required')
    if args.mode == 'evidence' and (args.slot is None or args.effort_null_slug is None):
        parser.error('--mode evidence requires --slot slot1 and --effort-null-slug')
    if args.mode == 'stage' and (args.slot is not None or args.effort_null_slug is not None):
        parser.error('--mode stage covers all six slots and takes neither --slot nor --effort-null-slug')
    try:
        if args.mode == 'evidence':
            return run('evidence', args.slot, args.nonce, args.attempt, args.effort_null_slug)
        return run('stage', None, args.nonce, args.attempt)
    except BaseException as exc:
        print(json.dumps({'status': 'PRE_RECEIPT_FAILURE', 'failure': safe_failure(exc, 'trusted_preflight')}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
