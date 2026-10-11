# Config interfaces for RUN_427_R5_SITTING.ps1 (final, 2026-10-11)

Files (audit fix wave B-F1..B-F7): build-pipeline-config-r5-candidate.py ab01d824... (89 tests), stage-pipeline-config-r5-v1.ps1
1066f6c3... (55 tests; its builderPin = ab01d824); builder->stager->retarget Assert-R5Config cross-check included. Take shas
from the pin generator.

## S9 (owner elevated session; the stager -Apply refuses SYSTEM and non-elevated)
$roots = exactly one 'C:\Program Files\CoChem\Pipeline4.2.7-windows-[0-9]{8}-r5' dir; $r5Python = <root>\.venv\Scripts\python.exe
$commissioned = 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\pipeline.json'
1. & $r5Python -I -B "$W\build-pipeline-config-r5-candidate.py" --commissioned $commissioned --login-root <S6 root>
     --capture-root <S7 signed-in root> --isolation-root <S8 root> --mode attempt --out-dir <fresh dir A>
   (use --mode held directly, with only --commissioned and --out-dir, when GEMINI is held or skipped)
   Exit 0 = a decision was written; 2 usage; 3 commissioned unreadable/not 135cd9ec; 4 out-dir not empty/link; 5 write failed.
2. If exit != 0 or any check fails: retry ONCE forced held with a fresh dir B.
3. powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$W\stage-pipeline-config-r5-v1.ps1" -BuildDirectory <A|B>          (plan: exit 0, PLAN_OK)
   $out = ... same ... -Apply   (exit 0, STAGED or ALREADY_STAGED_IDENTICAL); last stdout line = compact JSON
   {status, staged_path, staged_sha256, outcome, mode, receipt_path, target_state, exit_code, reason}
   Staging failure -> R4-RESTORE. A held staging record blocks the same -Attempt; a retry needs -Attempt v2 (path changes).
Checks on each build: decision.json schema cochem-r5-config-decision/1; candidate_sha256/candidate_length == pipeline.json on
disk; held outcome iff candidate sha == commissioned == 135cd9ec; enabled outcome (GEMINI_CONTRACT) requires mode attempt,
G1-G6 pass, error null, non-empty chosen_bindings equal to the candidate's providers.gemini.model_bindings (else exit 13);
decision.json and the candidate under a build directory with protected ancestry; builder.python == $r5Python;
builder.isolated_mode true; builder.script_sha256 == the pinned builder sha (else held phase PROVENANCE, exit 10).
The stager writes builder{...} into its staging receipt; decision.json carries evidence_binding (B-F1).
Roots: S6 C:\Program Files\CoChem\NativeAuthSix4.2.7-windows-20261011-r4-v1-<attempt>-gemini;
S7 ...\AgyCapture4.2.7-windows-20261010-r4-v1-<attempt>-slot1-signed-in; S8 ...\AgyIsolation4.2.7-windows-20261011-r4-v1-<attempt>
(take exact roots from those stages' result lines). --stage-root defaults to '<isolation-root>-stage'; an explicit
--stage-root must carry the same attempt in the same namespace (B-F1: one equal attempt across capture, isolation, stage
and login series, each root matching its namespace with protected ancestry; a different attempt forces a held decision).
S10 -CandidateSha256 = $s.staged_sha256. S11 -Config = $s.staged_path (C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json);
require $s.staged_sha256 -ceq decision.candidate_sha256; retarget reports GEMINI_CONTRACT or GEMINI_HELD_COMMISSIONED_BYTES == decision.outcome.
