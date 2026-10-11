$ErrorActionPreference = 'Stop'
$inputPath = Join-Path $PSScriptRoot 'agent-handoff-publication-input-20261009.json'
$publication = Get-Content -LiteralPath $inputPath -Raw | ConvertFrom-Json
$artifactRoot = Join-Path $PSScriptRoot 'agent-handoff-github-publication-20261009'
if (Test-Path -LiteralPath $artifactRoot) { throw 'Publication artifacts already exist. Inspect outcome; do not retry automatically.' }
[void][IO.Directory]::CreateDirectory($artifactRoot)
$utf8 = New-Object Text.UTF8Encoding($false)
$apiCounter = 0

function Write-NewText([string]$Path,[string]$Content) {
    $bytes = $utf8.GetBytes($Content)
    $stream = [IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
function Invoke-GitHubGet([string]$Endpoint) {
    $output = & gh api $Endpoint
    if ($LASTEXITCODE -ne 0) { throw ('GitHub read failed: ' + $Endpoint) }
    return (($output -join "`n") | ConvertFrom-Json)
}
function Invoke-GitHubPost([string]$Endpoint,$Body) {
    $script:apiCounter += 1
    $bodyPath = Join-Path $artifactRoot ('request-' + $script:apiCounter.ToString('D2') + '.json')
    Write-NewText $bodyPath (($Body | ConvertTo-Json -Depth 12 -Compress) + "`n")
    $output = & gh api --method POST $Endpoint --input $bodyPath
    if ($LASTEXITCODE -ne 0) { throw ('GitHub write outcome needs inspection; no automatic retry: ' + $Endpoint) }
    $responseText = $output -join "`n"
    Write-NewText (Join-Path $artifactRoot ('response-' + $script:apiCounter.ToString('D2') + '.json')) ($responseText + "`n")
    return ($responseText | ConvertFrom-Json)
}

if ($publication.repository -cne 'ProfJJK/Pipeline-Mix-Model-Concurrent' -or $publication.files.Count -ne 14) {
    throw 'Publication inputs differ.'
}
$endpoint = 'repos/' + $publication.repository
$base = Invoke-GitHubGet ($endpoint + '/git/ref/heads/master')
if ($base.object.sha -cne $publication.expected_base_commit) { throw 'Remote master moved; inspect before publication.' }
$refs = @(Invoke-GitHubGet ($endpoint + '/git/matching-refs/heads/' + $publication.branch))
if ($refs.Count -ne 0) { throw 'Publication branch exists; inspect it instead of overwriting.' }
$baseCommit = Invoke-GitHubGet ($endpoint + '/git/commits/' + $base.object.sha)
$treeEntries = @()
foreach ($entry in $publication.files) {
    if ($entry.path -notlike 'docs/*' -or $entry.path.Contains('..')) { throw 'Publication path outside docs.' }
    $filePath = Join-Path $publication.local_repository_root ($entry.path -replace '/', '\')
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $filePath).Hash.ToLowerInvariant()
    if ($actual -cne $entry.sha256) { throw ('Local document changed: ' + $entry.path) }
    $bytes = [IO.File]::ReadAllBytes($filePath)
    $blob = Invoke-GitHubPost ($endpoint + '/git/blobs') ([ordered]@{content=[Convert]::ToBase64String($bytes);encoding='base64'})
    $treeEntries += [ordered]@{path=$entry.path;mode='100644';type='blob';sha=$blob.sha}
}
$tree = Invoke-GitHubPost ($endpoint + '/git/trees') ([ordered]@{base_tree=$baseCommit.tree.sha;tree=$treeEntries})
$commit = Invoke-GitHubPost ($endpoint + '/git/commits') ([ordered]@{
    message='Document Windows deployment state and telemetry leak handoff'
    tree=$tree.sha
    parents=@($base.object.sha)
})
$comparison = Invoke-GitHubGet ($endpoint + '/compare/' + $base.object.sha + '...' + $commit.sha)
$expectedPaths = @($publication.files.path | Sort-Object)
$actualPaths = @($comparison.files.filename | Sort-Object)
if ($comparison.ahead_by -ne 1 -or $comparison.behind_by -ne 0 -or $actualPaths.Count -ne 14) {
    throw 'Remote comparison contains unexpected changes; branch not published.'
}
if (@(Compare-Object $expectedPaths $actualPaths).Count -ne 0 -or @($comparison.files | Where-Object status -ne 'added').Count -ne 0) {
    throw 'Remote comparison changed existing files; branch not published.'
}
$ref = Invoke-GitHubPost ($endpoint + '/git/refs') ([ordered]@{ref=('refs/heads/' + $publication.branch);sha=$commit.sha})
$body = @'
This handoff records the actual Windows deployment state and the immediate engineering work needed to continue it. It includes the confirmed ctypes telemetry leak, the unimplemented candidate repair, the guarded runtime-switch requirements, the owner's existing approval for two synthetic workflows, and the remaining acceptance limitations.

The selected evidence is safe metadata and isolated experiment code/results. No credentials, private document contents or production databases are included. Existing local Windows implementation changes and local-only commits are not part of this documentation-only branch.

Validation: all 12 copied evidence artifacts matched their expected SHA256 pins. The published comparison contains exactly 14 added documentation/evidence files and one commit based on current master; no existing repository file is modified. Production processes, tasks, credentials, databases and budgets were not changed by preparing the handoff. No model workflow was submitted.

Start here: `docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md`. This is a draft handoff for the next agent, not full deployment or SRS acceptance.
'@
Write-NewText (Join-Path $artifactRoot 'pull-request-body.md') ($body + "`n")
$pull = Invoke-GitHubPost ($endpoint + '/pulls') ([ordered]@{
    title='Windows deployment agent handoff: current state and telemetry repair'
    head=$publication.branch
    base='master'
    draft=$true
    body=$body
})
$result = [ordered]@{
    schema='cochem-agent-handoff-publication-result/1'
    status='DOCUMENTATION_ONLY_DRAFT_PR_CREATED'
    repository=$publication.repository
    branch=$publication.branch
    base_commit=$base.object.sha
    commit=$commit.sha
    pull_request_url=$pull.html_url
    files=14
    prior_repository_files_modified=0
    local_git_head_changed=$false
    production_changed=$false
}
Write-NewText (Join-Path $artifactRoot 'publication-result.json') (($result | ConvertTo-Json -Depth 8) + "`n")
$result | ConvertTo-Json -Depth 8
