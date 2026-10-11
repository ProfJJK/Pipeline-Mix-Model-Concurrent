$ErrorActionPreference = 'Stop'
$repositoryRoot = 'D:\Gdrive\__CoChem\GitHub-Repo\Antigravity_additions'
$stageRoot = $PSScriptRoot
$evidenceRoot = Join-Path $repositoryRoot 'docs\evidence\windows-2026-10-09\agent-handoff'
$documentTarget = Join-Path $repositoryRoot 'docs\WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md'
$documentSource = Join-Path $stageRoot 'WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md'
if (Test-Path -LiteralPath $documentTarget) { throw 'New handoff already exists; preserve it.' }
if (Test-Path -LiteralPath $evidenceRoot) { throw 'New handoff evidence root already exists; preserve it.' }

$copies = @(
    @{Name='LIVE_WORKFLOW_TEST_SCOPE_20261009.json'; Source=(Join-Path $stageRoot 'LIVE_WORKFLOW_TEST_SCOPE_20261009.json'); Sha='b35b01c72d68b58909a717c8641ef3c1bd48a191427237ec8cb5caefdd411949'},
    @{Name='LIVE_WORKFLOW_TEST_APPROVAL_20261009.json'; Source=(Join-Path $stageRoot 'LIVE_WORKFLOW_TEST_APPROVAL_20261009.json'); Sha='41511de098b4b4e8eba21c662d6ababdab2c087ea7f5a3830d114733775376cb'},
    @{Name='compare_commit_type_cache_memory_r3.py'; Source=(Join-Path $stageRoot 'compare_commit_type_cache_memory_r3.py'); Sha='ea4055871e9de6b35029424d3f778ed024e4f097f36ae05fe64d367e2a564ed7'},
    @{Name='commit-type-cache-comparison-r3-20261009.json'; Source=(Join-Path $stageRoot 'commit-type-cache-comparison-r3-20261009.json'); Sha='a4125e79893e91991617a29f9298d886c5013dd3547d8979c4b5a841f4b30d5c'},
    @{Name='reproduce-commit-probe-type-growth-20261009.py'; Source=(Join-Path $stageRoot 'reproduce-commit-probe-type-growth-20261009.py'); Sha='c98c0e6570c4c2f75a12e60ffd3fd86591f08c3af0cafe5cbac6d0dc3c0a201c'},
    @{Name='commit-probe-type-growth-actual-windows-20261009.json'; Source=(Join-Path $stageRoot 'commit-probe-type-growth-actual-windows-20261009.json'); Sha='91bf6dc32a7a86539c52a36e1d80afb1315b3dd8be1f05af396a31d3f2eaebd8'},
    @{Name='knowledge-memory-generated-fixture-r3-20261009.json'; Source=(Join-Path $stageRoot 'knowledge-memory-generated-fixture-r3-20261009.json'); Sha='eeaf52e12bc29874a7bf9008d57ac9b296414d8f0e7eeb6808d3c288378c12f6'},
    @{Name='post-recorder-activation-live-readiness-safe-20261009.json'; Source=(Join-Path $stageRoot 'post-recorder-activation-live-readiness-safe-20261009.json'); Sha='06efac14fa22d6cc6262ff5e9c9612b4ad32f546079ee5cefcaa24775e95e53c'},
    @{Name='observer-started.json'; Source='C:\Program Files\CoChem\ResourceObservation4.2.7-windows-20261008-r3-v4\observer-started.json'; Sha='1477eeb23e38e79c9fe701f1c973e6726dd2d107bac0013c31da73238ee3d01a'},
    @{Name='resource-recovery-complete.json'; Source='C:\Program Files\CoChem\ResourceObserverRecovery4.2.7-windows-20261009-r3-v1\recovery-complete.json'; Sha='9686c4a47243543931886dcc43224637e553f1fd5cebc954c28162fc1b30a4a0'},
    @{Name='held-supervisor-activation.json'; Source='C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1\activation.json'; Sha='5599e920e8b457e6389e5d7677a4eca6e5479e8dc72bba2f41ccb5d46e640171'},
    @{Name='held-observer-recovery-complete.json'; Source='C:\Program Files\CoChem\HeldObserverRecovery4.2.7-windows-20261008-r3-v1\recovery-complete.json'; Sha='20c2e18bf33409bed4813faec3f4917b000917b032dbb39113f00a6c9a216c4a'}
)

foreach ($entry in $copies) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Source).Hash.ToLowerInvariant()
    if ($actual -cne $entry.Sha) { throw ('Evidence pin differs: ' + $entry.Name) }
}

function Write-NewBytes([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}

[void][IO.Directory]::CreateDirectory($evidenceRoot)
$entries = @()
foreach ($entry in $copies) {
    $target = Join-Path $evidenceRoot $entry.Name
    $raw = [IO.File]::ReadAllBytes($entry.Source)
    Write-NewBytes $target $raw
    $copiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
    if ($copiedHash -cne $entry.Sha) { throw ('Copied evidence differs: ' + $entry.Name) }
    $entries += [ordered]@{path=$entry.Name;bytes=$raw.Length;sha256=$copiedHash}
}
$manifest = [ordered]@{
    schema='cochem-windows-agent-handoff-evidence/1'
    prepared_at_utc=[DateTime]::UtcNow.ToString('o')
    repository='ProfJJK/Pipeline-Mix-Model-Concurrent'
    scope='Selected safe metadata and isolated experiment code/results. No credentials, private document text or production database files.'
    entries=$entries
    model_jobs_submitted=0
    telemetry_repair_implemented=$false
    production_processes_changed=$false
    full_srs_acceptance=$false
}
$utf8 = New-Object Text.UTF8Encoding($false)
Write-NewBytes (Join-Path $evidenceRoot 'evidence-manifest.json') ($utf8.GetBytes(($manifest | ConvertTo-Json -Depth 8) + "`n"))
Write-NewBytes $documentTarget ([IO.File]::ReadAllBytes($documentSource))

$publicationFiles = @('docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md')
foreach ($entry in $copies) { $publicationFiles += ('docs/evidence/windows-2026-10-09/agent-handoff/' + $entry.Name) }
$publicationFiles += 'docs/evidence/windows-2026-10-09/agent-handoff/evidence-manifest.json'
$publication = [ordered]@{
    schema='cochem-handoff-publication-input/1'
    repository='ProfJJK/Pipeline-Mix-Model-Concurrent'
    base_branch='master'
    expected_base_commit='6894dddad946f09cfa12c0a03eef9128d58c1ff2'
    branch='docs/windows-agent-handoff-2026-10-09'
    local_repository_root=$repositoryRoot
    files=@($publicationFiles | ForEach-Object {
        $filePath = Join-Path $repositoryRoot ($_ -replace '/', '\')
        [ordered]@{path=$_;sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $filePath).Hash.ToLowerInvariant()}
    })
}
Write-NewBytes (Join-Path $stageRoot 'agent-handoff-publication-input-20261009.json') ($utf8.GetBytes(($publication | ConvertTo-Json -Depth 8) + "`n"))
[ordered]@{status='HANDOFF_CREATED_AND_PIN_VERIFIED';document=$documentTarget;selected_evidence_files=$copies.Count;publication_files=$publicationFiles.Count;existing_repo_files_overwritten=0;git_history_changed=$false;production_changed=$false} | ConvertTo-Json
