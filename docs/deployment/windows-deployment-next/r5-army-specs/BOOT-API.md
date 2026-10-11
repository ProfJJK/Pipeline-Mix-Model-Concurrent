# BOOT-MAIN interface (cochem_pipeline daemon, r5) - as implemented 2026-10-11

- --queue-launch-output-root DIR (default none). Mutually exclusive with --queue-launch-output (argparse exit 2).
  DIR must lie strictly inside the staged config's private_root, compared case-insensitively after abspath and
  after resolve (8.3 or linked spellings are refused); DIR equal to private_root is refused; DIR or any directory
  between private_root and DIR must not be a reparse point (checked before and after mkdir(parents=True, exist_ok=True)).
  Child per start: DIR\<UTC %Y%m%dT%H%M%SZ>-<pid>, created by QueueLaunchObserver (exist_ok=False).
  INFO log: 'Queue launch evidence for this start: <child>'.
- --docker-wait-seconds N (whole number >= 0, default 0 = unchanged behaviour). N > 0 polls
  DockerRunner(config.docker, private_root\containers, trusted_operator=config.operator_name).preflight() before
  Runtime(config), sleeps 5, 10, 20, then 30 s; WARNING per failed try 'Docker engine not ready: preflight try <n> failed ...';
  on timeout it does not raise: Runtime is constructed once and its own preflight raises today's error (crash record
  category 'code'). May overrun N by one preflight (two Docker client calls, each capped at 30 s).
- r5 task action (retarget-warden-r5 -Target r5):
  -I -B -m cochem_pipeline daemon --config "<staged r5 config>"
    --queue-launch-output-root "C:\ProgramData\CoChemPipeline427\private\queue-launch-r5" --docker-wait-seconds 900
  The root must be spelled under exactly the staged config's private_root.
- Supervisor note: during the wait there is no heartbeat; a running cochem_supervisor would report a stale heartbeat
  for up to N seconds (the supervisor stays disabled in r5).
- Tests: pipeline_tests/test_daemon_start_options.py, 32 passed, 1 skipped (symlink privilege).
