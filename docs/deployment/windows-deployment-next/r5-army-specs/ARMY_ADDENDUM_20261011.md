# r5 army addendum (2026-10-11, after the 00:57 crash) - overrides the r5 spec where they conflict

A1. WARDEN IS DOWN. Since the crash reboot at 2026-10-11 00:57 the task CoChem-4.2.7-Warden is enabled
    but idle (0 instances). Its action is still the r4-v1 action, whose --queue-launch-output directory is
    consumed, so that action cannot start again. Consequences:
    - Sitting step S2 (stop-warden-r4) becomes CONDITIONAL: run it only if S0 finds a controller instance.
    - retarget-warden-r5 must accept the r4-v1 source action with 0 instances directly (no stop receipt needed).
    - R4-RESTORE must also work from this state.

A2. REBOOT-SAFE OPERATION (new requirement R1). Today every crash or reboot leaves the pipeline down until
    an elevated retarget. r5 adds two daemon options in src/cochem_pipeline/__main__.py:
    - --queue-launch-output-root DIR: creates a fresh child DIR\<UTC yyyymmddTHHMMSSZ>-<pid> on each start and
      passes it to QueueLaunchObserver exactly like --queue-launch-output today. Mutually exclusive with
      --queue-launch-output. The root is created if missing, with the same protection checks the daemon applies
      today (validate it lies under config.private_root and is not a reparse point).
    - --docker-wait-seconds N (default 0 = byte-for-byte today's behaviour). When N > 0 the daemon waits for the
      Docker engine before constructing Runtime: it polls the same Docker preflight the Runtime uses, with bounded
      backoff (5 s doubling, at most 30 s between tries), logs each failed try at WARNING, and after N seconds
      fails exactly as today. Choose the seam after reading runtime.py around lines 120-175; Runtime must never
      be constructed twice and nothing may leak.
    The r5 Warden task action becomes:
      <r5 python> -I -B -m cochem_pipeline daemon --config "<staged r5 config>"
        --queue-launch-output-root "C:\ProgramData\CoChemPipeline427\private\queue-launch-r5" --docker-wait-seconds 900
    retarget-warden-r5 -Target r5 adds a LOGON trigger for AETHERDESK\ansac with a 1-minute delay (Docker Desktop
    runs in the owner's interactive session, so a boot trigger would fail the Docker preflight). Keep
    MultipleInstancesPolicy IgnoreNew and no execution time limit. -Target r4 (restore) keeps the r4 flags
    (a fresh --queue-launch-output directory, no trigger) because r4 lacks the new options.

A3. CONTROLLER MEMORY BUDGET. The SRS S427-HOST-006 literal of 50 MiB leaves under 10 MiB headroom over the
    roughly 40 MiB idle Python footprint, so harmless allocator high-water closes admission. r5 raises the Warden
    self-budget to 200 MiB (CPU 5 % unchanged) as a named module constant in controller_guard.py and records an
    owner amendment dated 2026-10-11 in the repo-root 4.2.7_SRS.md (HOST-006 and PERF-005 lines). Do NOT edit
    knowledge/wiki/4.2.7_SRS.md, because the knowledge authority capture may hash it; flag it instead. M4's
    recovery hysteresis still applies.

A4. GEMINI IS ATTEMPTED. GEMINI=attempt is the sitting default; skip remains a switch. Any Gemini gate failure
    degrades to held without failing the sitting.

A5. NF-1 IS DROPPED. Do not build copy-native-attempt-evidence or its helpers; the sitting has no S4.
    N1 and N2 capture future native failures.

A6. FREEZE FILE SET. The r5 freeze changes the 12 spec files PLUS src/cochem_pipeline/__main__.py
    (r4 is pure CRLF, the repo is LF; commit it pure CRLF). 13 changed, verified_unchanged 153 of 166.
    Per-file line-ending convention for the commit (must equal r4's, normalised to pure):
    pure LF: agy_protocol.py. Pure CRLF: every other changed file.

A7. HOST SAFETY (AGENTS.md; this host crashed under load last night).
    - Every test run, harness run, multi-file parse check or build goes ONLY through
        C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe -I
          C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\serialize-heavy.py
          --timeout-minutes 120 --label <your-name> -- <command>
      It allows one heavy run at a time across all agents; waiting for it is expected.
    - Pytest always single-process: -p no:cacheprovider, never -n.
    - Use the Read, Grep, Glob, Edit and Write tools for file work. Use the shell only for git and for
      serialized runs.
    - Never run agy, claude, codex or gemini CLIs. Never start, stop, end, enable, disable or register scheduled
      tasks, services, WSL, Docker or VMs. Never elevate. Never write under C:\Program Files or C:\ProgramData.
    - Owner-facing scripts are written for Windows PowerShell 5.1, ASCII only, read-only plan by default and
      -Apply for change, and are tested only through inert harnesses with stubs.
