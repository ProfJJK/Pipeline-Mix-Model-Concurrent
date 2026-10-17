#Requires -Version 5.1
<# Read-only export of sanitized facts about the native catalog probes of one
   held owner sitting. It reads the protected attempt folders (Administrator)
   and writes one JSON report to an ordinary folder. It never exports raw
   native text, prompts, answers, credentials, e-mail or session identifiers:
   only allowlisted fields, sizes, hashes, typed tokens and keyword flags.
   No task, process, provider, service, Docker or deployment action. #>
[CmdletBinding()]
param([string]$OutputDirectory='C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next',
      [string]$AttemptsRoot='C:\ProgramData\CoChemPipeline427\private\attempts',
      [string]$SinceUtc='2026-10-17T01:38:00Z',[string]$UntilUtc='2026-10-17T01:41:00Z')

function Get-OpDiagMember {
    param($Value,[string]$Name)
    if($null -eq $Value){return $null}
    if($Value -is [Collections.IDictionary]){if($Value.Contains($Name)){return $Value[$Name]};return $null}
    $p=$Value.PSObject.Properties[$Name];if($null -ne $p){return $p.Value};return $null
}

function Get-OpDiagKeywords {
    # Reviewed vocabulary; only the names of matching entries leave the host.
    return [ordered]@{effort='\beffort\b';thinking='thinking';budget='budget';model='\bmodel\b';
        unsupported='not supported|unsupported|does not support|not available|is not enabled';invalid='invalid';
        permission='permission|forbidden|not allowed';max_tokens='max_tokens|max tokens|output token';
        overloaded='overload';rate_limit='rate.?limit|too many requests';usage_limit='usage limit|hit your (?:usage )?limit';
        credit='credit';context='context';timeout='timed? ?out';network='econn|enotfound|fetch failed|network|socket';
        auth='auth|log ?in|token';tool='\btools?\b';turns='max.?turns';deprecated='deprecat|retired|end of life';
        stream='stream';abort='abort|cancel';settings='setting';json='json';api_error='api error'}
}

function Get-OpTextFacts {
    param([string]$Text)
    if($null -eq $Text){return $null}
    $folded=$Text.ToLowerInvariant();$keywords=@()
    $vocabulary=Get-OpDiagKeywords
    foreach($name in $vocabulary.Keys){if($folded -match $vocabulary[$name]){$keywords+=$name}}
    $status=$null
    $m=[regex]::Match($folded,'^\s*(?:failed to authenticate\.\s*)?(?:api error:\s*|request failed with status code )([0-9]{3})\b')
    if($m.Success){$status=[int]$m.Groups[1].Value}
    $statuses=@([regex]::Matches($folded,'"status(?:_code)?"\s*:\s*([0-9]{3})')|ForEach-Object{[int]$_.Groups[1].Value}|Sort-Object -Unique)
    $tokens=@([regex]::Matches($folded,'"type"\s*:\s*"([a-z_]{1,48})"')|ForEach-Object{$_.Groups[1].Value}|Sort-Object -Unique)
    return [ordered]@{length=$Text.Length;leading_api_status=$status;embedded_statuses=$statuses;type_tokens=$tokens;keywords=$keywords}
}

function Read-OpDiagText {
    param([string]$Path,[int]$Maximum=1048576)
    if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    try{
        $length=[int][Math]::Min($stream.Length,$Maximum);$buffer=New-Object byte[] $length
        $read=0;while($read -lt $length){$n=$stream.Read($buffer,$read,$length-$read);if($n -le 0){break};$read+=$n}
        return [Text.Encoding]::UTF8.GetString($buffer,0,$read)
    }finally{$stream.Dispose()}
}

function Get-OpDiagRecords {
    # The whole text as one JSON value, otherwise one JSON value per line.
    param([string]$Text)
    if([string]::IsNullOrWhiteSpace($Text)){return @()}
    try{return @($Text|ConvertFrom-Json)}catch{}
    $records=@()
    foreach($line in ($Text -split "`r?`n")){
        if([string]::IsNullOrWhiteSpace($line)){continue}
        try{$records+=@($line|ConvertFrom-Json)}catch{}
    }
    return $records
}

function Get-OpResultFacts {
    param($Record)
    $type=[string](Get-OpDiagMember $Record 'type')
    $facts=[ordered]@{type=$type;subtype=(Get-OpDiagMember $Record 'subtype');is_error=(Get-OpDiagMember $Record 'is_error');
        num_turns=(Get-OpDiagMember $Record 'num_turns');duration_ms=(Get-OpDiagMember $Record 'duration_ms');
        keys=@($Record.PSObject.Properties.Name|Sort-Object)}
    $usage=Get-OpDiagMember $Record 'modelUsage'
    if($null -ne $usage){$facts.model_usage_models=@($usage.PSObject.Properties.Name|Sort-Object)}
    $result=Get-OpDiagMember $Record 'result'
    if($result -is [string]){$facts.result=Get-OpTextFacts $result}
    $errors=Get-OpDiagMember $Record 'errors'
    if($null -ne $errors){$facts.errors=@(@($errors)|ForEach-Object{if($_ -is [string]){Get-OpTextFacts $_}else{Get-OpTextFacts ($_|ConvertTo-Json -Compress -Depth 6)}})}
    $err=Get-OpDiagMember $Record 'error'
    if($null -ne $err){$facts.error=Get-OpTextFacts ($err|ConvertTo-Json -Compress -Depth 6)}
    return $facts
}

function Get-OpAuthFacts {
    # Sign-in state only; e-mail, organization and account identifiers stay private.
    param([string]$Text)
    $records=@(Get-OpDiagRecords $Text)
    if($records.Count -ne 1){return [ordered]@{parsed=$false;length=$(if($null -eq $Text){0}else{$Text.Length})}}
    $r=$records[0];$facts=[ordered]@{parsed=$true}
    foreach($name in @('loggedIn','authMethod','apiProvider','subscriptionType')){
        $value=Get-OpDiagMember $r $name
        if($value -is [bool] -or ($value -is [string] -and $value -cmatch '^[A-Za-z0-9_.-]{1,40}$')){$facts[$name]=$value}
    }
    return $facts
}

function Get-OpAttemptFacts {
    param([IO.DirectoryInfo]$Directory)
    $files=@(Get-ChildItem -LiteralPath $Directory.FullName -File -Force|ForEach-Object{[ordered]@{name=$_.Name;bytes=$_.Length}})
    $facts=[ordered]@{attempt=$Directory.Name;created_utc=$Directory.CreationTimeUtc.ToString('o');
        last_write_utc=$Directory.LastWriteTimeUtc.ToString('o');files=$files}
    $failureText=Read-OpDiagText (Join-Path $Directory.FullName 'failure.json')
    if($null -ne $failureText){
        $f=$failureText|ConvertFrom-Json;$facts.failure=[ordered]@{}
        foreach($name in @('schema','category','exit_code','stdout_bytes','stdout_sha256','stderr_bytes','stderr_sha256',
            'envelope_kind','claude_result_subtype','api_status','started_at','finished_at')){$facts.failure[$name]=Get-OpDiagMember $f $name}
    }
    $receiptText=Read-OpDiagText (Join-Path $Directory.FullName 'receipt.json')
    if($null -ne $receiptText){
        $r=$receiptText|ConvertFrom-Json;$facts.receipt=[ordered]@{}
        foreach($name in @('provider','requested_model','requested_effort','reported_model','reported_effort','exit_code',
            'worker_slot','execution_kind','started_at','finished_at')){$facts.receipt[$name]=Get-OpDiagMember $r $name}
        $effort=Get-OpDiagMember (Get-OpDiagMember $r 'inference_policy') 'reasoning_effort'
        $facts.receipt.effort_evidence=[ordered]@{requested_profile=(Get-OpDiagMember $effort 'requested_profile');
            model=(Get-OpDiagMember $effort 'model');version=(Get-OpDiagMember $effort 'version')}
    }
    $stdout=Read-OpDiagText (Join-Path $Directory.FullName 'stdout.log')
    if($null -ne $stdout){
        $records=@(Get-OpDiagRecords $stdout)
        $facts.stdout=[ordered]@{length=$stdout.Length;json_records=$records.Count;
            results=@($records|Where-Object{(Get-OpDiagMember $_ 'type') -ceq 'result' -or $null -ne (Get-OpDiagMember $_ 'error')}|ForEach-Object{Get-OpResultFacts $_});
            record_types=@($records|ForEach-Object{[string](Get-OpDiagMember $_ 'type')}|Sort-Object -Unique)}
        if($records.Count -eq 0){$facts.stdout.text=Get-OpTextFacts $stdout}
    }
    $stderr=Read-OpDiagText (Join-Path $Directory.FullName 'stderr.log')
    if($null -ne $stderr){$facts.stderr=Get-OpTextFacts $stderr}
    $auth=Read-OpDiagText (Join-Path $Directory.FullName 'auth.out')
    if($null -ne $auth){$facts.auth=Get-OpAuthFacts $auth}
    $authErr=Read-OpDiagText (Join-Path $Directory.FullName 'auth.err')
    if($null -ne $authErr){$facts.auth_stderr=Get-OpTextFacts $authErr}
    return $facts
}

function Invoke-OpProbeDiagnostic {
    param([string]$Root,[DateTime]$Since,[DateTime]$Until)
    $since=$Since.ToUniversalTime();$until=$Until.ToUniversalTime()
    $dirs=@(Get-ChildItem -LiteralPath $Root -Directory -Force|Where-Object{
        $_.CreationTimeUtc -ge $since -and $_.CreationTimeUtc -le $until}|Sort-Object CreationTimeUtc)
    return [ordered]@{schema='cochem-428-catalog-probe-diagnostic/1';observed_at_utc=[DateTime]::UtcNow.ToString('o');
        window=[ordered]@{since_utc=$since.ToString('o');until_utc=$until.ToString('o')};attempts=@($dirs|ForEach-Object{Get-OpAttemptFacts $_});
        raw_text_exported=$false;protected_state_modified=$false;provider_commands_executed=0;task_mutations=0}
}

if($MyInvocation.InvocationName -ne '.'){
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if(-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
        throw 'Run in Administrator Windows PowerShell (read-only; protected attempt metadata).'}
    if(-not (Test-Path -LiteralPath $OutputDirectory -PathType Container) -or
        $OutputDirectory.StartsWith('C:\Program Files',[StringComparison]::OrdinalIgnoreCase) -or
        $OutputDirectory.StartsWith('C:\ProgramData',[StringComparison]::OrdinalIgnoreCase)){throw 'Choose an existing ordinary output folder.'}
    $report=Invoke-OpProbeDiagnostic $AttemptsRoot ([DateTime]::Parse($SinceUtc).ToUniversalTime()) ([DateTime]::Parse($UntilUtc).ToUniversalTime())
    $json=$report|ConvertTo-Json -Depth 12
    $path=Join-Path $OutputDirectory ('r6-catalog-probe-diagnostic-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'.json')
    $stream=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$bytes=[Text.UTF8Encoding]::new($false).GetBytes($json);$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()}
    $json
    Write-Host ('Saved: '+$path)
}
