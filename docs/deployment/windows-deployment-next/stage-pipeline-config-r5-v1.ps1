#Requires -Version 5.1
<# Reviewed owner stager for the r5 Warden configuration (CONFIG-STAGER, r5 sitting stage S9, 2026-10-11).
   Installs the pipeline.json chosen by build-pipeline-config-r5-candidate.py at a NEW protected path, bound by content,
   for retarget-warden-r5.ps1 -Config. Derived from the repository's
   docs\evidence\windows-2026-10-09\continuation\owner-wrappers\stage_pipeline_config.ps1 (its stale 20261006 install root,
   InstallGuard root and D:\Gdrive repository root are replaced); the parser-only check, the r5 interpreter discovery and
   the only-Gemini rule are copies of retarget-warden-r5.ps1, so the staged file passes that script unchanged.

   Usage (owner, elevated 64-bit Windows PowerShell 5.1 on AETHERDESK for -Apply; without -Apply a read-only plan):
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File stage-pipeline-config-r5-v1.ps1 -BuildDirectory <builder --out-dir> [-Attempt vN] [-Apply]
   -Attempt (default v1) selects C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-<Attempt>\pipeline.json.

   Checks, plan and -Apply alike (the first failure refuses, changes nothing and prints the held reason; never a retry):
     decision.json in the build directory: inside a protected build directory (the house Assert-ProtectedPath rule up to
       C:\Program Files: owner and writers only SYSTEM, Administrators or TrustedInstaller, no reparse point), ASCII
       without BOM, at most 1 MiB, schema cochem-r5-config-decision/1, every contract field present by its exact name with
       its JSON type (extra fields are tolerated), gates G1..G6 present; builder provenance (deploy audit B-F2):
       builder.isolated_mode exactly true, builder.script_sha256 the pinned builder, builder.python the bound r5
       interpreter (checked once the r5 runtime is found);
     candidate: candidate_file exactly pipeline.json in the same protected directory, its length and sha256 on disk equal
       the decision, read once into memory behind a deny-write handle (the bytes staged are the bytes verified, never a
       re-read of the build directory);
     commissioned: decision commissioned_sha256 and the commissioned file on disk both equal the pin 135cd9ec...;
     outcome: GEMINI_HELD_COMMISSIONED_BYTES exactly when the candidate is the commissioned bytes (either mode);
       GEMINI_CONTRACT only from mode attempt with G1..G6 passed, error null and non-empty chosen_bindings that equal the
       candidate's providers.gemini.model_bindings;
     only Gemini: the structural rule of retarget-warden-r5.ps1 Assert-R5Config (an empty diff for the held outcome);
     target: retarget's -Config pattern, never the commissioned file and never inside the r4 runtime root; a pre-existing
       target directory is accepted only with the protected ACL, nothing but pipeline.json and earlier staging receipts,
       and a byte-identical pipeline.json (ALREADY_STAGED_IDENTICAL: nothing is verified-and-repaired, only recorded);
     parser: the installed r5 interpreter (exactly one Pipeline4.2.7-windows-<date>-r5 root, its python bound to its
       install-after.json) loads the held candidate as six worker identities, four shared slots and enabled knowledge.
   -Apply creates the directory with O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA), writes pipeline.json CreateNew from the verified
   in-memory bytes, re-hashes it and verifies both ACLs, then writes the receipt cochem-config-only-staging/2 CreateNew as
   staging-receipt-<UTC>-<nonce>.json in that directory. A failure once the directory exists leaves
   staging-held-<UTC>-<nonce>.json there: a reviewed recovery and another -Attempt, never an automatic retry. No task,
   service, daemon, credential, database, RAM disk or commissioned file is touched; plan mode writes nothing.

   Output: the last stdout line is one compact JSON object
     {status, staged_path, staged_sha256, outcome, mode, receipt_path, target_state, exit_code, reason}
   status PLAN_OK | STAGED | ALREADY_STAGED_IDENTICAL (exit 0) or HELD (non-zero). Exit codes: 0 success; 1 PowerShell
   refused the command line itself; 2 parameters; 3 host or reviewed helper; 4 -Apply without the owner elevated;
   10 decision.json or its builder provenance (held phase DECISION or PROVENANCE); 11 candidate; 12 commissioned pin;
   13 outcome or chosen bindings; 14 only-Gemini diff; 15 r5 runtime or parser; 16 target; 20 apply held; 21 receipt
   held; 30 internal. #>
[CmdletBinding()]
param([string]$BuildDirectory='',[switch]$Apply,[string]$Attempt='v1')

function Import-ReviewedFunctions {
    param([string]$Path,[string]$Hash,[string[]]$Names)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Hash){throw ('Reviewed function source changed: '+$Path)}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        $tokens=$null;$errors=$null;try{$ast=[Management.Automation.Language.Parser]::ParseInput($reader.ReadToEnd(),[ref]$tokens,[ref]$errors)}finally{$reader.Dispose()}
        if($errors.Count){throw 'Reviewed helper parse failure.'}
        foreach($name in $Names){
            $nodes=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object {$_.Name -ceq $name})
            if($nodes.Count -ne 1){throw ('Expected exactly one reviewed definition of '+$name)}
            $nodes[0].Extent.Text}
    }finally{$stream.Dispose()}
}

function Invoke-NativeJudged {
    # Windows PowerShell 5.1 turns native stderr into terminating errors under
    # ErrorActionPreference=Stop. Judge native commands by exit code only, and decode their
    # output as UTF-8 (every Python child runs with -X utf8).
    param([string]$Executable,[string[]]$Arguments)
    if(-not (Test-Path -LiteralPath $Executable -PathType Leaf)){throw ('Native executable is missing: '+$Executable)}
    $previous=$ErrorActionPreference;$previousEncoding=[Console]::OutputEncoding;$global:LASTEXITCODE=$null;$all=@();$code=$null
    try{$ErrorActionPreference='Continue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$all=@(& $Executable @Arguments 2>&1);$code=$global:LASTEXITCODE}
    finally{$ErrorActionPreference=$previous;[Console]::OutputEncoding=$previousEncoding}
    $stdout=@($all|Where-Object {$_ -isnot [Management.Automation.ErrorRecord]}|ForEach-Object {[string]$_})
    $stderr=@($all|Where-Object {$_ -is [Management.Automation.ErrorRecord]}|ForEach-Object {[string]$_.Exception.Message})
    [pscustomobject]@{code=$code;stdout=($stdout -join "`n");stderr=($stderr -join "`n")}
}

function Test-ExactBool {param($Value,[bool]$Expected)($Value -is [bool]) -and ($Value -eq $Expected)}
function Test-ExactInt {param($Value,[long]$Expected)(($Value -is [int]) -or ($Value -is [long])) -and ([long]$Value -eq $Expected)}
function Test-Sha256Text {param($Value)($Value -is [string]) -and ($Value -cmatch '^[a-f0-9]{64}$')}

function Get-JsonMember {
    param($Object,[string]$Path)
    # A dotted lookup in parsed JSON that never guesses and never throws under StrictMode: $null when any step is absent.
    $current=$Object
    foreach($name in $Path.Split('.')){
        if($null -eq $current -or $current -isnot [Management.Automation.PSCustomObject]){return $null}
        $property=$current.PSObject.Properties[$name]
        if($null -eq $property){return $null}
        $current=$property.Value}
    ,$current
}

function Get-R5RootCandidates {
    @(Get-ChildItem -LiteralPath $script:base -Directory -Force -ErrorAction Stop|Where-Object {$_.Name -cmatch $script:r5RootPattern}|ForEach-Object {$_.FullName})
}

function Find-R5Root {
    # The installer sets the dated r5 root name; exactly one installed r5 root may exist, and its receipt must name it.
    $found=@(Get-R5RootCandidates)
    if($found.Count -ne 1){throw ('Expected exactly one installed r5 runtime root Pipeline4.2.7-windows-<date>-r5 under '+$script:base+'; found '+$found.Count+'.')}
    $found[0]
}

function Invoke-R5ConfigParser {
    param([string]$Python,[string]$Path)
    # Parser-only validation with the r5 interpreter (single-quoted Python only, as Windows PowerShell 5.1 argv requires).
    $code='import json,sys'+"`n"+'from cochem_pipeline.config import load_config'+"`n"+'c=load_config(sys.argv[1])'+"`n"+
        'print(json.dumps({''parser_valid'':True,''worker_identities'':len(c.workers),''max_shared_slots'':c.max_execution_slots,''knowledge_enabled'':bool(c.knowledge.enabled)}))'
    $result=Invoke-NativeJudged $Python @('-I','-B','-X','utf8','-c',$code,$Path)
    if($result.code -ne 0){throw ('The r5 configuration parser failed (exit '+$result.code+'): '+$result.stderr)}
    $parsed=$null;try{$parsed=$result.stdout|ConvertFrom-Json}catch{throw 'The r5 configuration parser printed no JSON.'}
    if(-not (Test-ExactBool (Get-JsonMember $parsed 'parser_valid') $true) -or -not (Test-ExactInt (Get-JsonMember $parsed 'worker_identities') 6) -or
       -not (Test-ExactInt (Get-JsonMember $parsed 'max_shared_slots') 4) -or -not (Test-ExactBool (Get-JsonMember $parsed 'knowledge_enabled') $true)){
        throw 'The r5 configuration does not load as six worker identities, four shared slots and enabled knowledge.'}
    $parsed
}

function Assert-ApplyIdentity {
    param([bool]$ApplyRequested,$HostContext)
    if($ApplyRequested -and (-not [bool]$HostContext.admin -or [string]$HostContext.name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
}

function Stop-Staging {
    param([int]$Code,[string]$Message,[bool]$Changed=$false,[string]$HeldRecord='')
    # A refusal that carries its documented exit code; the main function turns it into the held output.
    $exception=[InvalidOperationException]::new($Message)
    $exception.Data['cochem_exit_code']=$Code;$exception.Data['cochem_changed']=$Changed;$exception.Data['cochem_held_record']=$HeldRecord
    throw $exception
}

function Assert-StagerParameters {
    param($Arguments)
    # Pure parameter rules, checked before the host is touched (indexer access: an absent key reads as empty under StrictMode).
    $build=[string]$Arguments['BuildDirectory'];$attemptValue=[string]$Arguments['Attempt'];$applyValue=[bool]$Arguments['Apply']
    if(-not $build){throw '-BuildDirectory <builder --out-dir> is required; nothing was read or changed.'}
    if($build -cnotmatch '^[A-Za-z]:\\' -or $build.Contains([string][char]0) -or $build.Substring(2).Contains(':') -or $build.IndexOfAny([char[]]'*?"<>|') -ge 0){
        throw '-BuildDirectory must be an absolute local path such as C:\...\out; nothing was read or changed.'}
    if($attemptValue -cnotmatch '^v[0-9]{1,3}$'){throw '-Attempt must be v followed by 1-3 digits; nothing was read or changed.'}
    [ordered]@{build_directory=[IO.Path]::GetFullPath($build).TrimEnd('\');attempt=$attemptValue;apply=$applyValue}
}

function Initialize-StagerHost {
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);name=[string]$identity.Name}
}

function Set-StagerConstants {
    # Pins recomputed from the files on disk on 2026-10-11. decision.json, the candidate, the r5 runtime and any existing
    # target cannot be pre-pinned: they are bound by content at run time.
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:commissionedRoot=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4'
    $script:commissionedPath=Join-Path $script:commissionedRoot 'pipeline.json'
    $script:commissioningCopyPath=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
    $script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    # Fixed namespace date of this sitting (the same as retarget-warden-r5.ps1); -Attempt selects the namespace.
    $script:namespaceDate='20261011'
    $script:targetRoot=Join-Path $script:base ('WardenConfig4.2.7-windows-'+$script:namespaceDate+'-r5-'+$script:Attempt)
    $script:targetPath=Join-Path $script:targetRoot 'pipeline.json'
    $script:r5ConfigPattern='^C:\\Program Files\\CoChem\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$'
    $script:r5RootPattern='^Pipeline4\.2\.7-windows-[0-9]{8}-r5$'
    $script:stagingSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
    $script:decisionSchema='cochem-r5-config-decision/1';$script:receiptSchema='cochem-config-only-staging/2'
    $script:decisionFields=@('schema','mode','outcome','gates','chosen_bindings','effort_contracts','error','candidate_file','candidate_sha256',
        'candidate_length','commissioned_path','commissioned_sha256','evidence','builder')
    $script:candidateFileName='pipeline.json';$script:maxJsonBytes=1048576
    # The reviewed build-pipeline-config-r5-candidate.py; decision.json builder.script_sha256 must equal it (B-F2).
    $script:builderPin='86c4d12d541d8dff2c5202ede6a854b00451de5da9fad4c241f4f1fb90b2d297'
    $script:receiptNamePattern='^staging-receipt-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.json$'
    $script:copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    $script:copyHelperPin='0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
    $script:readHelper=Join-Path $script:scriptDirectory 'check-worker-native-status-r3.ps1'
    $script:readHelperPin='18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7'
}

function Import-StagerHelpers {
    # Dot-sourced by the main function, so the reviewed functions are defined in its scope (hash-pinned, as retarget does).
    foreach($text in Import-ReviewedFunctions $script:copyHelper $script:copyHelperPin @('Assert-NoReparseAncestors','Assert-ProtectedPath','Initialize-FileIdentity','Open-VerifiedFile')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions $script:readHelper $script:readHelperPin @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
}

function Get-ScriptSha256 {
    param([string]$Path)
    if(-not $Path){return $null}
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-HeldBytes {
    param([string]$Path,[long]$Maximum)
    # A workspace file read once into memory behind a deny-write handle that stays open for the whole run: no reparse
    # ancestry, no hardlink, the handle resolves to the named path, and the bytes used later are the bytes hashed here.
    Assert-NoReparseAncestors $Path
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        [CoChemStagedFileIdentity]::Check($stream,$Path)
        if($stream.Length -gt $Maximum){throw ('File exceeds '+$Maximum+' bytes: '+$Path)}
        $bytes=[byte[]]::new([int]$stream.Length);$offset=0
        while($offset -lt $bytes.Length){$count=$stream.Read($bytes,$offset,$bytes.Length-$offset);if($count -le 0){throw ('Short read: '+$Path)};$offset+=$count}
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$digest=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        $stream.Position=0
    }catch{$stream.Dispose();throw}
    $held.Add($stream)
    [pscustomobject]@{path=$Path;Stream=$stream;bytes=$bytes;sha256=$digest;length=[long]$bytes.Length}
}

function Test-JsonObject {param($Value)($null -ne $Value) -and ($Value -is [Management.Automation.PSCustomObject])}

function Get-ExactField {
    param($Object,[string]$Name)
    # One JSON field by its exact, case-sensitive name (PSObject lookups ignore case); present is false when absent.
    if(Test-JsonObject $Object){foreach($property in $Object.PSObject.Properties){if($property.Name -ceq $Name){return [pscustomobject]@{present=$true;value=$property.Value}}}}
    [pscustomobject]@{present=$false;value=$null}
}

function Assert-DecisionDocument {
    param($Document)
    # The builder-to-stager contract: every listed field present by its exact name with its JSON type; extra fields tolerated.
    if(-not (Test-JsonObject $Document)){throw 'decision.json is not a JSON object.'}
    $values=@{}
    foreach($name in $script:decisionFields){
        $field=Get-ExactField $Document $name
        if(-not $field.present){throw ('decision.json lacks the required field '+$name+'.')}
        $values[$name]=$field.value}
    if($values['schema'] -isnot [string] -or $values['schema'] -cne $script:decisionSchema){throw ('decision.json schema is not '+$script:decisionSchema+'.')}
    if($values['mode'] -isnot [string] -or $values['mode'] -cnotin @('attempt','held')){throw 'decision.json mode must be attempt or held.'}
    if($values['outcome'] -isnot [string] -or $values['outcome'] -cnotin @('GEMINI_CONTRACT','GEMINI_HELD_COMMISSIONED_BYTES')){throw 'decision.json outcome must be GEMINI_CONTRACT or GEMINI_HELD_COMMISSIONED_BYTES.'}
    if(-not (Test-JsonObject $values['gates'])){throw 'decision.json gates is not a JSON object.'}
    $gates=[ordered]@{};$passed=0
    foreach($gate in @('G1','G2','G3','G4','G5','G6')){
        $entry=Get-ExactField $values['gates'] $gate
        if(-not $entry.present -or -not (Test-JsonObject $entry.value)){throw ('decision.json gates lacks the gate object '+$gate+'.')}
        $pass=Get-ExactField $entry.value 'pass';$reason=Get-ExactField $entry.value 'reason'
        if(-not $pass.present -or $pass.value -isnot [bool] -or -not $reason.present -or $reason.value -isnot [string]){throw ('decision.json gate '+$gate+' must carry a boolean pass and a string reason.')}
        $gates[$gate]=[ordered]@{pass=[bool]$pass.value;reason=[string]$reason.value}
        if($pass.value){$passed++}}
    foreach($name in @('chosen_bindings','effort_contracts')){if($null -ne $values[$name] -and -not (Test-JsonObject $values[$name])){throw ('decision.json '+$name+' must be a JSON object or null.')}}
    if($null -ne $values['error'] -and $values['error'] -isnot [string]){throw 'decision.json error must be null or a string.'}
    if($values['candidate_file'] -isnot [string]){throw 'decision.json candidate_file must be a string.'}
    if(-not (Test-Sha256Text $values['candidate_sha256'])){throw 'decision.json candidate_sha256 must be 64 lowercase hex characters.'}
    $length=$values['candidate_length']
    if(-not (($length -is [int]) -or ($length -is [long])) -or [long]$length -lt 1 -or [long]$length -gt $script:maxJsonBytes){throw ('decision.json candidate_length must be an integer from 1 to '+$script:maxJsonBytes+'.')}
    if($values['commissioned_path'] -isnot [string] -or -not $values['commissioned_path'].Trim()){throw 'decision.json commissioned_path must be a non-empty string.'}
    if(-not (Test-Sha256Text $values['commissioned_sha256'])){throw 'decision.json commissioned_sha256 must be 64 lowercase hex characters.'}
    foreach($name in @('evidence','builder')){if(-not (Test-JsonObject $values[$name])){throw ('decision.json '+$name+' must be a JSON object.')}}
    # Builder provenance (deploy audit B-F2): the pinned builder in isolated mode; builder.python is compared with the bound
    # r5 interpreter once the runtime is found (Assert-BuilderInterpreter).
    $builderPython=Get-ExactField $values['builder'] 'python';$isolated=Get-ExactField $values['builder'] 'isolated_mode';$builderSha=Get-ExactField $values['builder'] 'script_sha256'
    if(-not $builderPython.present -or $builderPython.value -isnot [string] -or $builderPython.value -cnotmatch '^[A-Za-z]:\\[^"*?<>|]+$'){throw 'decision.json builder.python must be the absolute path of the interpreter that ran the builder.'}
    if(-not $isolated.present -or $isolated.value -isnot [bool] -or -not $isolated.value){throw 'decision.json builder.isolated_mode must be true: the builder runs only as <r5 python> -I.'}
    if(-not $builderSha.present -or $builderSha.value -isnot [string] -or $builderSha.value -cne $script:builderPin){throw ('decision.json builder.script_sha256 is not the pinned builder '+$script:builderPin+'.')}
    $bindings=$values['chosen_bindings'];$bindingCount=0
    if($null -ne $bindings){$bindingCount=@($bindings.PSObject.Properties).Count}
    [ordered]@{schema=$values['schema'];mode=$values['mode'];outcome=$values['outcome'];gates=$gates;gates_passed=$passed;chosen_bindings=$bindings;
        chosen_bindings_count=$bindingCount;effort_contracts=$values['effort_contracts'];error=$values['error'];candidate_file=$values['candidate_file'];
        candidate_sha256=$values['candidate_sha256'];candidate_length=[long]$length;commissioned_path=$values['commissioned_path'];commissioned_sha256=$values['commissioned_sha256'];
        builder_python=$builderPython.value;builder_script_sha256=$builderSha.value}
}

function Assert-BuildCustody {
    param([string]$Path,[string]$Label)
    # Deploy audit B-F2: the builder's output is staged only from a protected build directory (the house
    # Assert-ProtectedPath rule from the file up to C:\Program Files), so no unelevated process can have written it.
    try{Assert-ProtectedPath $Path}catch{
        throw ($Label+' is not inside a protected build directory (owner and writers only SYSTEM, Administrators or TrustedInstaller up to C:\Program Files): '+$_.Exception.Message)}
}

function Read-StagingDecision {
    param([string]$BuildDirectory)
    # decision.json is the builder's commit marker (written last); it is ASCII JSON without a byte order mark.
    if(-not (Test-Path -LiteralPath $BuildDirectory -PathType Container)){throw ('The build directory does not exist: '+$BuildDirectory)}
    $path=Join-Path $BuildDirectory 'decision.json'
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw ('decision.json is missing from the build directory: '+$path)}
    Assert-BuildCustody $path 'decision.json'
    $read=Read-HeldBytes $path $script:maxJsonBytes;$bytes=$read.bytes
    if($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF){throw 'decision.json starts with a byte order mark; the builder contract is ASCII without BOM.'}
    $ascii=[Text.Encoding]::GetEncoding('us-ascii',[Text.EncoderFallback]::ExceptionFallback,[Text.DecoderFallback]::ExceptionFallback)
    $text=$null;try{$text=$ascii.GetString($bytes)}catch{throw 'decision.json is not ASCII JSON.'}
    $document=$null;try{$document=$text|ConvertFrom-Json}catch{throw 'decision.json is not JSON.'}
    $summary=Assert-DecisionDocument $document
    $summary['path']=$path;$summary['sha256']=$read.sha256;$summary['length']=$read.length
    $summary
}

function Read-StagingCandidate {
    param([string]$BuildDirectory,$Decision)
    # The candidate is BuildDirectory\pipeline.json only (no path, no traversal), verified by length and sha256 on disk.
    if($Decision.candidate_file -cne $script:candidateFileName){
        $shown=[string]$Decision.candidate_file;if($shown.Length -gt 200){$shown=$shown.Substring(0,200)}
        throw ('decision.json candidate_file must be exactly pipeline.json (no path); found "'+$shown+'".')}
    $path=Join-Path $BuildDirectory $script:candidateFileName
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw ('The candidate pipeline.json is missing from the build directory: '+$path)}
    Assert-BuildCustody $path 'The candidate pipeline.json'
    $read=Read-HeldBytes $path $script:maxJsonBytes
    if($read.length -ne $Decision.candidate_length){throw ('The candidate length on disk ('+$read.length+') differs from decision.json candidate_length ('+$Decision.candidate_length+').')}
    if($read.sha256 -cne $Decision.candidate_sha256){throw ('The candidate sha256 on disk ('+$read.sha256+') differs from decision.json candidate_sha256.')}
    $read
}

function Read-CommissionedReference {
    param($Decision)
    # The commissioned r4 configuration (gemini held by integration_hold), pinned and held behind a deny-write handle.
    if($Decision.commissioned_sha256 -cne $script:configPin){throw ('decision.json commissioned_sha256 is not the commissioned pin '+$script:configPin+'.')}
    $control=$null
    try{$control=Read-R3Control $script:commissionedPath $script:configPin $script:maxJsonBytes}catch{throw ('The commissioned configuration on disk does not verify against the pin '+$script:configPin+': '+$_.Exception.Message)}
    [pscustomobject]@{path=$script:commissionedPath;sha256=$control.Sha256;length=$control.Length;text=(Read-R3Text $control);decision_path=$Decision.commissioned_path}
}

function Assert-OutcomeConsistency {
    param($Decision,[string]$CandidateSha256)
    # GEMINI_HELD_COMMISSIONED_BYTES exactly when the candidate is the commissioned file (either mode); GEMINI_CONTRACT only
    # from an attempt in which every gate passed, without an error and with chosen bindings.
    $heldOutcome=($Decision.outcome -ceq 'GEMINI_HELD_COMMISSIONED_BYTES');$sameBytes=($CandidateSha256 -ceq $script:configPin)
    if($heldOutcome -and -not $sameBytes){throw 'decision.json says GEMINI_HELD_COMMISSIONED_BYTES but the candidate is not the commissioned bytes.'}
    if($sameBytes -and -not $heldOutcome){throw ('decision.json says '+$Decision.outcome+' but the candidate is the commissioned bytes.')}
    if($heldOutcome){return}
    if($Decision.mode -cne 'attempt'){throw 'GEMINI_CONTRACT requires decision mode attempt.'}
    $failed=@(foreach($gate in @($Decision.gates.Keys)){if(-not $Decision.gates[$gate].pass){$gate}})
    if($failed.Count){throw ('GEMINI_CONTRACT requires every gate G1..G6 to pass; failed: '+($failed -join ', ')+'.')}
    if($null -ne $Decision.error){throw 'GEMINI_CONTRACT requires error null; decision.json records an error.'}
    if($Decision.chosen_bindings_count -lt 1){throw 'GEMINI_CONTRACT requires non-empty chosen_bindings.'}
}

function Test-StagerJsonEqual {
    param($Left,$Right)
    # Structural equality of two ConvertFrom-Json values: objects by exact (case-sensitive) member names in any order,
    # arrays element by element, scalars by type and case-sensitive value.
    if($null -eq $Left -or $null -eq $Right){return ($null -eq $Left -and $null -eq $Right)}
    if($Left -is [Management.Automation.PSCustomObject] -or $Right -is [Management.Automation.PSCustomObject]){
        if($Left -isnot [Management.Automation.PSCustomObject] -or $Right -isnot [Management.Automation.PSCustomObject]){return $false}
        $leftMembers=@($Left.PSObject.Properties);$rightMembers=@($Right.PSObject.Properties)
        if($leftMembers.Count -ne $rightMembers.Count){return $false}
        foreach($member in $leftMembers){
            $match=@($rightMembers|Where-Object {$_.Name -ceq $member.Name})
            if($match.Count -ne 1 -or -not (Test-StagerJsonEqual $member.Value $match[0].Value)){return $false}}
        return $true}
    if($Left -is [array] -or $Right -is [array]){
        if($Left -isnot [array] -or $Right -isnot [array] -or $Left.Count -ne $Right.Count){return $false}
        for($index=0;$index -lt $Left.Count;$index++){if(-not (Test-StagerJsonEqual $Left[$index] $Right[$index])){return $false}}
        return $true}
    ($Left.GetType() -eq $Right.GetType()) -and ($Left -ceq $Right)
}

function Assert-DecisionBindings {
    param($Decision,[string]$CandidateText)
    # Deploy audit B-F2: a GEMINI_CONTRACT decision names exactly the bindings the staged candidate carries
    # (providers.gemini.model_bindings); the held outcome stages the commissioned bytes and has none.
    if($Decision.outcome -cne 'GEMINI_CONTRACT'){return}
    $candidate=$null;try{$candidate=$CandidateText|ConvertFrom-Json}catch{throw 'The candidate configuration is not JSON.'}
    $bindings=Get-JsonMember $candidate 'providers.gemini.model_bindings'
    if($bindings -isnot [Management.Automation.PSCustomObject]){throw 'decision.json says GEMINI_CONTRACT but the candidate providers.gemini has no model_bindings object.'}
    if(-not (Test-StagerJsonEqual $Decision.chosen_bindings $bindings)){throw 'decision.json chosen_bindings differs from the candidate providers.gemini.model_bindings.'}
}

function Assert-BuilderInterpreter {
    param($Decision,$Runtime)
    # Deploy audit B-F2: the builder ran under the bound r5 interpreter (the one install-after.json binds by sha256).
    $named=$null;$bound=$null
    try{$named=[IO.Path]::GetFullPath([string]$Decision.builder_python);$bound=[IO.Path]::GetFullPath([string]$Runtime.python)}catch{throw ('decision.json builder.python is not a usable path: '+[string]$Decision.builder_python)}
    if(-not [string]::Equals($named,$bound,[StringComparison]::OrdinalIgnoreCase)){throw ('decision.json builder.python '+[string]$Decision.builder_python+' is not the bound r5 interpreter '+[string]$Runtime.python+'.')}
}

function Assert-OnlyGeminiChanges {
    param([string]$CandidateText,[string]$CandidateSha256,[string]$CommissionedText)
    # The rule of retarget-warden-r5.ps1 Assert-R5Config, unchanged: either the commissioned bytes (an empty diff, Gemini
    # held) or the commissioned document with only providers.gemini changed, compared as compressed JSON, case-sensitively.
    if($CandidateSha256 -ceq $script:configPin){return 'GEMINI_HELD_COMMISSIONED_BYTES'}
    $candidate=$null;$commissioned=$null
    try{$candidate=$CandidateText|ConvertFrom-Json}catch{throw 'The candidate configuration is not JSON.'}
    $commissioned=$CommissionedText|ConvertFrom-Json
    if($candidate -isnot [Management.Automation.PSCustomObject] -or $null -eq (Get-JsonMember $candidate 'providers') -or
       (Get-JsonMember $candidate 'providers') -isnot [Management.Automation.PSCustomObject] -or
       (Get-JsonMember $candidate 'providers.gemini') -isnot [Management.Automation.PSCustomObject]){throw 'The candidate configuration has no providers.gemini object.'}
    $candidateGemini=(Get-JsonMember $candidate 'providers.gemini')|ConvertTo-Json -Depth 64 -Compress
    $commissionedGemini=(Get-JsonMember $commissioned 'providers.gemini')|ConvertTo-Json -Depth 64 -Compress
    $candidate.providers.PSObject.Properties.Remove('gemini');$commissioned.providers.PSObject.Properties.Remove('gemini')
    if(($candidate|ConvertTo-Json -Depth 64 -Compress) -cne ($commissioned|ConvertTo-Json -Depth 64 -Compress)){throw 'The candidate configuration changes more than providers.gemini; preserve it for review.'}
    if($candidateGemini -ceq $commissionedGemini){throw 'The candidate configuration differs from the commissioned bytes without a providers.gemini change; preserve it for review.'}
    'GEMINI_CONTRACT'
}

function Get-R5ParserRuntime {
    # The installed r5 interpreter, found as retarget-warden-r5.ps1 finds it, bound by content to its install-after.json and
    # held behind a deny-write handle while it parses (retarget re-verifies the whole r5 build before any cutover).
    $root=Find-R5Root
    $afterPath=Join-Path $root 'install-after.json'
    $afterControl=Read-R3Control $afterPath '' $script:maxJsonBytes
    $after=$null;try{$after=(Read-R3Text $afterControl)|ConvertFrom-Json}catch{throw 'The r5 installation receipt is not JSON.'}
    $venvPythonSha=Get-JsonMember $after 'runtime_bindings.venv_python_sha256'
    if((Get-JsonMember $after 'schema') -cne 'cochem-stopped-runtime-update/1' -or (Get-JsonMember $after 'mode') -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       (Get-JsonMember $after 'target_root') -cne $root -or -not (Test-Sha256Text $venvPythonSha)){
        throw ('The r5 installation receipt is not a successful stopped-runtime build of '+$root+'; run install-stopped-runtime-r5.ps1 -Apply first.')}
    $python=Join-Path $root '.venv\Scripts\python.exe'
    $null=Read-R3Control $python $venvPythonSha 4194304
    [ordered]@{root=$root;python=$python;python_sha256=$venvPythonSha;install_after_path=$afterPath;install_after_sha256=$afterControl.Sha256}
}

function Assert-StagingTargetPath {
    param([string]$Path)
    # retarget-warden-r5.ps1 accepts -Config only on this pattern; the commissioned file and the r4 runtime root are never targets.
    if($Path -cnotmatch $script:r5ConfigPattern){throw ('The staging target must be C:\Program Files\CoChem\WardenConfig4.2.7-windows-<date>-r5-vN\pipeline.json: '+$Path)}
    $full=[IO.Path]::GetFullPath($Path)
    if($full -cne $Path){throw ('The staging target is not a normalized path: '+$Path)}
    foreach($forbidden in @($script:commissionedPath,$script:commissioningCopyPath)){
        if([string]::Equals($full,[IO.Path]::GetFullPath($forbidden),[StringComparison]::OrdinalIgnoreCase)){throw ('The staging target is the commissioned configuration, which is never overwritten: '+$Path)}}
    $inside=[IO.Path]::GetFullPath($script:commissionedRoot).TrimEnd('\')+'\'
    if($full.StartsWith($inside,[StringComparison]::OrdinalIgnoreCase)){throw ('The staging target lies inside the commissioned runtime root '+$script:commissionedRoot+': '+$Path)}
}

function New-StagingSecurity {
    param([bool]$Directory)
    # O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA), applied when the object is created (never afterwards).
    $security=$(if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()})
    $security.SetSecurityDescriptorSddlForm($script:stagingSddl)
    ,$security
}

function Get-StagingAclSummary {
    param([string]$Path)
    $acl=Get-Acl -LiteralPath $Path
    $rules=@(foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
        [pscustomobject]@{sid=[string]$rule.IdentityReference.Value;type=[string]$rule.AccessControlType;rights=[long]$rule.FileSystemRights;inherited=[bool]$rule.IsInherited;
            inheritance=[string]$rule.InheritanceFlags;propagation=[string]$rule.PropagationFlags}})
    [pscustomobject]@{owner=[string]$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;protected=[bool]$acl.AreAccessRulesProtected;rules=$rules}
}

function Test-StagingAcl {
    param($Summary)
    # '' when the descriptor is exactly O:BA with a protected DACL of one explicit Allow FullControl each for SYSTEM and
    # Administrators; otherwise the first difference.
    if($Summary.owner -cne 'S-1-5-32-544'){return ('the owner is '+$Summary.owner+', not BUILTIN\Administrators')}
    if(-not $Summary.protected){return 'the DACL is not protected from inheritance'}
    $rules=@($Summary.rules)
    if($rules.Count -ne 2){return ('expected exactly two access rules, found '+$rules.Count)}
    foreach($rule in $rules){
        if($rule.type -cne 'Allow' -or $rule.inherited -or $rule.rights -ne 2032127 -or $rule.inheritance -cne 'None' -or $rule.propagation -cne 'None'){return ('unexpected access rule for '+$rule.sid)}}
    $sids=@($rules|ForEach-Object {[string]$_.sid})
    if(-not ($sids -ccontains 'S-1-5-18') -or -not ($sids -ccontains 'S-1-5-32-544')){return 'the access rules are not exactly SYSTEM and Administrators'}
    ''
}

function Assert-StagingAcl {
    param([string]$Path)
    $difference=Test-StagingAcl (Get-StagingAclSummary $Path)
    if($difference){throw ('The protected configuration path does not carry '+$script:stagingSddl+' ('+$difference+'): '+$Path)}
}

function Get-StagingTargetState {
    param([string]$Root,[string]$Path,[string]$CandidateSha256,[long]$CandidateLength)
    # ABSENT, or ALREADY_STAGED_IDENTICAL when the protected directory holds exactly this pipeline.json plus earlier staging
    # receipts; anything else is preserved for review and refused, never repaired or overwritten.
    if(-not (Test-Path -LiteralPath $Root)){
        Assert-ProtectedPath (Split-Path -Parent $Root)
        return [ordered]@{root=$Root;path=$Path;state='ABSENT';existing_receipts=@();existing_sha256=$null}}
    if(-not (Test-Path -LiteralPath $Root -PathType Container)){throw ('The staging target root exists and is not a directory; preserve it for review: '+$Root)}
    Assert-NoReparseAncestors $Root
    Assert-StagingAcl $Root
    $receipts=@();$unexpected=@();$hasConfig=$false
    foreach($entry in @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop)){
        if($entry.PSIsContainer){$unexpected+=$entry.Name}
        elseif($entry.Name -ceq 'pipeline.json'){$hasConfig=$true}
        elseif($entry.Name -cmatch $script:receiptNamePattern){$receipts+=$entry.Name}
        else{$unexpected+=$entry.Name}}
    if($unexpected.Count){throw ('The staging target directory holds unexpected entries (a held record needs a reviewed recovery); preserve it and choose another -Attempt: '+((@($unexpected)|Sort-Object) -join ', '))}
    if(-not $hasConfig){throw ('The staging target directory exists without pipeline.json (a partial staging); preserve it for review and choose another -Attempt: '+$Root)}
    Assert-StagingAcl $Path
    foreach($name in $receipts){Assert-StagingAcl (Join-Path $Root $name)}
    $control=Read-R3Control $Path '' $script:maxJsonBytes
    if($control.Sha256 -cne $CandidateSha256 -or $control.Length -ne $CandidateLength){
        throw ('A different pipeline.json is already staged at '+$Path+' (sha256 '+$control.Sha256+'); it is never overwritten. Preserve it and choose another -Attempt.')}
    [ordered]@{root=$Root;path=$Path;state='ALREADY_STAGED_IDENTICAL';existing_receipts=@($receipts|Sort-Object);existing_sha256=$control.Sha256}
}

function New-StagingDirectory {
    param([string]$Path)
    if(Test-Path -LiteralPath $Path){throw ('Protected configuration directory already exists; preserve it: '+$Path)}
    Assert-ProtectedPath (Split-Path -Parent $Path)
    $directory=[IO.DirectoryInfo]::new($Path);$directory.Create((New-StagingSecurity $true))
    Assert-NoReparseAncestors $Path
    Assert-StagingAcl $Path
    Assert-ProtectedPath $Path
}

function Write-NewProtectedFile {
    param([string]$Path,[byte[]]$Bytes,$Security)
    # CreateNew only (an existing file is never replaced), with the protected descriptor applied at creation.
    $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::WriteThrough,$Security)
    try{$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function New-StagingRecordName {
    param([string]$Prefix)
    $Prefix+'-'+[DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'",[Globalization.CultureInfo]::InvariantCulture)+'-'+[Guid]::NewGuid().ToString('N')+'.json'
}

function Write-StagingHeld {
    param($Context,[string]$Phase,[string]$Reason)
    # A held record is best effort on top of the refusal: its own failure is reported in the message, never swallowed.
    try{
        $path=Join-Path $Context.target.root (New-StagingRecordName 'staging-held')
        $record=[ordered]@{schema='cochem-config-only-staging-held/2';phase=$Phase;reason=$Reason;target_root=$Context.target.root;target_path=$Context.target.path;
            target_file_present=[bool](Test-Path -LiteralPath $Context.target.path);decision_path=$Context.decision.path;decision_sha256=$Context.decision.sha256;
            candidate_sha256=$Context.candidate.sha256;outcome=$Context.decision.outcome;mode=$Context.decision.mode;held_utc=[DateTime]::UtcNow.ToString('o');
            automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
        Write-NewProtectedFile $path ([Text.UTF8Encoding]::new($false).GetBytes(($record|ConvertTo-Json -Depth 6))) (New-StagingSecurity $false)
        return [pscustomobject]@{path=$path;note=(' Held record: '+$path)}
    }catch{return [pscustomobject]@{path='';note=(' The held record could not be written: '+$_.Exception.Message)}}
}

function New-StagingReceipt {
    param($Context,[string]$Status)
    $decision=$Context.decision
    [ordered]@{schema=$script:receiptSchema;status=$Status;staged_path=$Context.target.path;staged_sha256=$Context.candidate.sha256;staged_length=$Context.candidate.length;
        target_root=$Context.target.root;mode=$decision.mode;outcome=$decision.outcome;only_policy_change=$Context.diff.only_policy_change;
        decision_path=$decision.path;decision_sha256=$decision.sha256;decision_schema=$decision.schema;
        builder=[ordered]@{python=$decision.builder_python;script_sha256=$decision.builder_script_sha256;isolated_mode=$true;interpreter_is_bound_r5=$true};
        candidate_path=$Context.candidate.path;candidate_sha256=$Context.candidate.sha256;candidate_length=$Context.candidate.length;
        commissioned_path=$Context.commissioned.path;commissioned_sha256=$Context.commissioned.sha256;decision_commissioned_path=$Context.commissioned.decision_path;
        gates=$decision.gates;gates_passed=$decision.gates_passed;chosen_bindings=$decision.chosen_bindings;effort_contracts=$decision.effort_contracts;decision_error=$decision.error;
        parser=$Context.parser;r5_runtime=$Context.runtime;previous_receipts=@($Context.target.existing_receipts);staging_sddl=$script:stagingSddl;acl_verified=$true;
        script_path=$Context.script_path;script_sha256=$Context.script_sha256;operator=$Context.operator;administrator=$Context.administrator;
        staged_utc=[DateTime]::UtcNow.ToString('o');retarget_config_argument=$Context.target.path;commissioned_file_modified=$false;tasks_changed=0;started=$false;
        credentials_modified=$false;databases_modified=$false;automatic_retry_allowed=$false}
}

function Write-StagingReceipt {
    param([string]$Path,$Receipt)
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Receipt|ConvertTo-Json -Depth 10))
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$digest=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
    Write-NewProtectedFile $Path $bytes (New-StagingSecurity $false)
    $null=Read-R3Control $Path $digest $script:maxJsonBytes
    Assert-StagingAcl $Path
    $digest
}

function Invoke-StagingApply {
    param($Context)
    # The only mutation: one new protected directory, one pipeline.json CreateNew from the verified bytes, one receipt.
    $root=$Context.target.root;$path=$Context.target.path;$status=$null
    if($Context.target.state -ceq 'ABSENT'){
        try{New-StagingDirectory $root}catch{
            $reason=$_.Exception.Message
            if(-not (Test-Path -LiteralPath $root)){Stop-Staging 20 ('The protected configuration directory could not be created: '+$reason+' Nothing was changed.')}
            $record=Write-StagingHeld $Context 'DIRECTORY' $reason
            Stop-Staging 20 ('The protected configuration directory '+$root+' exists but could not be secured: '+$reason+' Nothing was staged; preserve it, review the held record and choose another -Attempt.'+$record.note) $true $record.path}
        try{
            Write-NewProtectedFile $path $Context.candidate.bytes (New-StagingSecurity $false)
            $control=Read-R3Control $path $Context.candidate.sha256 $script:maxJsonBytes
            if($control.Length -ne $Context.candidate.length){throw 'the staged length differs from the verified candidate'}
            Assert-StagingAcl $root;Assert-StagingAcl $path
        }catch{
            $reason=$_.Exception.Message
            $record=Write-StagingHeld $Context 'WRITE' $reason
            Stop-Staging 20 ('The staged configuration is held: '+$reason+' Preserve '+$root+' and review the held record; it is never overwritten or retried automatically.'+$record.note) $true $record.path}
        $status='STAGED'
    }else{$status='ALREADY_STAGED_IDENTICAL'}
    $receiptPath=Join-Path $root (New-StagingRecordName 'staging-receipt')
    $receipt=New-StagingReceipt $Context $status
    $receiptHash=$null
    try{$receiptHash=Write-StagingReceipt $receiptPath $receipt}catch{
        $reason=$_.Exception.Message
        $record=Write-StagingHeld $Context 'RECEIPT' $reason
        Stop-Staging 21 ('The configuration is '+$status+' at '+$path+' but its receipt could not be written CreateNew: '+$reason+' Do not retarget from this run; review the held record.'+$record.note) $true $record.path}
    [ordered]@{status=$status;receipt_path=$receiptPath;receipt_sha256=$receiptHash;receipt=$receipt}
}

function Format-StagerStatusLine {
    param([string]$Status,$StagedPath,$StagedSha256,$Outcome,$Mode,$ReceiptPath,$TargetState,[int]$ExitCode,$Reason)
    # The orchestrator's interface: one compact JSON object, always the last stdout line.
    [ordered]@{status=$Status;staged_path=$StagedPath;staged_sha256=$StagedSha256;outcome=$Outcome;mode=$Mode;receipt_path=$ReceiptPath;
        target_state=$TargetState;exit_code=$ExitCode;reason=$Reason}|ConvertTo-Json -Compress
}

function New-StagerOutput {
    param([int]$Code,$Document,[string]$StatusLine)
    [pscustomobject]@{exit_code=$Code;lines=@(($Document|ConvertTo-Json -Depth 10),$StatusLine)}
}

function Invoke-StagePipelineConfigR5Main {
    param($Arguments,[string]$ScriptPath,[string]$ScriptDirectory)
    # Never throws: returns one object {exit_code, lines}; every refusal becomes a HELD document and status line.
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $codes=@{PARAMETERS=2;HOST=3;IDENTITY=4;DECISION=10;PROVENANCE=10;CANDIDATE=11;COMMISSIONED=12;OUTCOME=13;DIFF=14;PARSER=15;TARGET=16;APPLY=20;OUTPUT=30}
    $phase='PARAMETERS';$request=$null;$hostContext=$null;$scriptSha=$null;$decision=$null;$candidate=$null;$commissioned=$null
    $diff=$null;$target=$null;$runtime=$null;$parser=$null;$context=$null
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $request=Assert-StagerParameters $Arguments
        $phase='HOST';$hostContext=Initialize-StagerHost
        $phase='IDENTITY';Assert-ApplyIdentity $request.apply $hostContext
        $phase='HOST';$script:Attempt=$request.attempt;$script:scriptDirectory=$ScriptDirectory;Set-StagerConstants
        $scriptSha=Get-ScriptSha256 $ScriptPath
        . Import-StagerHelpers
        $phase='DECISION';$decision=Read-StagingDecision $request.build_directory
        $phase='CANDIDATE';$candidate=Read-StagingCandidate $request.build_directory $decision
        $phase='COMMISSIONED';$commissioned=Read-CommissionedReference $decision
        $phase='OUTCOME';Assert-OutcomeConsistency $decision $candidate.sha256
        $phase='DIFF';$byContent=Assert-OnlyGeminiChanges (Read-R3Text $candidate) $candidate.sha256 $commissioned.text
        if($byContent -cne $decision.outcome){throw ('The content is '+$byContent+' but decision.json says '+$decision.outcome+'.')}
        $phase='OUTCOME';Assert-DecisionBindings $decision (Read-R3Text $candidate)
        $diff=[ordered]@{outcome_by_content=$byContent;only_policy_change=$(if($byContent -ceq 'GEMINI_CONTRACT'){'providers.gemini contract'}else{'none: the commissioned bytes, Gemini held by integration_hold'})}
        $phase='TARGET';Assert-StagingTargetPath $script:targetPath
        $target=Get-StagingTargetState $script:targetRoot $script:targetPath $candidate.sha256 $candidate.length
        $phase='PARSER';$runtime=Get-R5ParserRuntime
        $phase='PROVENANCE';Assert-BuilderInterpreter $decision $runtime
        $phase='PARSER';$parser=Invoke-R5ConfigParser $runtime.python $candidate.path
        $context=[ordered]@{decision=$decision;candidate=$candidate;commissioned=$commissioned;diff=$diff;target=$target;runtime=$runtime;parser=$parser;
            script_path=$ScriptPath;script_sha256=$scriptSha;operator=$hostContext.name;administrator=[bool]$hostContext.admin}
        $view=[ordered]@{build_directory=$request.build_directory;attempt=$request.attempt;
            decision=[ordered]@{path=$decision.path;sha256=$decision.sha256;schema=$decision.schema;mode=$decision.mode;outcome=$decision.outcome;gates=$decision.gates;
                gates_passed=$decision.gates_passed;chosen_bindings_count=$decision.chosen_bindings_count;error=$decision.error;
                builder_python=$decision.builder_python;builder_script_sha256=$decision.builder_script_sha256};
            candidate=[ordered]@{path=$candidate.path;sha256=$candidate.sha256;length=$candidate.length};
            commissioned=[ordered]@{path=$commissioned.path;sha256=$commissioned.sha256;decision_path=$commissioned.decision_path};diff=$diff;parser=$parser;r5_runtime=$runtime;
            target=[ordered]@{root=$target.root;path=$target.path;state=$target.state;existing_receipts=@($target.existing_receipts)};staging_sddl=$script:stagingSddl;
            administrator=[bool]$hostContext.admin;operator=$hostContext.name;script_sha256=$scriptSha}
        if(-not $request.apply){
            $phase='OUTPUT'
            $plan=[ordered]@{schema='cochem-config-only-staging-plan/2';mode='READ_ONLY_PLAN'};foreach($key in @($view.Keys)){$plan[$key]=$view[$key]}
            $plan['apply_would']=$(if($target.state -ceq 'ABSENT'){'create the protected directory, write pipeline.json CreateNew from the verified bytes, write one receipt'}else{'write one ALREADY_STAGED_IDENTICAL receipt; nothing else'})
            $plan['files_written']=0;$plan['tasks_changed']=0
            return New-StagerOutput 0 $plan (Format-StagerStatusLine 'PLAN_OK' $target.path $candidate.sha256 $decision.outcome $decision.mode $null $target.state 0 $null)}
        $phase='APPLY';$applied=Invoke-StagingApply $context
        $phase='OUTPUT'
        $result=[ordered]@{schema='cochem-config-only-staging-result/2';status=$applied.status;receipt_path=$applied.receipt_path;receipt_sha256=$applied.receipt_sha256;
            staged_path=$target.path;staged_sha256=$candidate.sha256;retarget_config_argument=$target.path;receipt=$applied.receipt}
        return New-StagerOutput 0 $result (Format-StagerStatusLine $applied.status $target.path $candidate.sha256 $decision.outcome $decision.mode $applied.receipt_path $target.state 0 $null)
    }catch{
        $exception=$_.Exception;$code=[int]$codes[$phase];$changed=$false;$heldRecord=$null
        if($exception.Data.Contains('cochem_exit_code')){
            $code=[int]$exception.Data['cochem_exit_code'];$changed=[bool]$exception.Data['cochem_changed']
            if([string]$exception.Data['cochem_held_record']){$heldRecord=[string]$exception.Data['cochem_held_record']}}
        $reason=[string]$exception.Message
        $outcome=$null;$mode=$null;if($null -ne $decision){$outcome=$decision.outcome;$mode=$decision.mode}
        $document=[ordered]@{schema='cochem-config-only-staging-held/2';status='HELD';phase=$phase;exit_code=$code;reason=$reason;changed=$changed;held_record=$heldRecord;
            build_directory=$(if($null -ne $request){$request.build_directory}else{$null});target_path=$(if($null -ne $request -and $phase -cne 'PARAMETERS' -and $phase -cne 'HOST' -and $phase -cne 'IDENTITY'){$script:targetPath}else{$null});
            decision_sha256=$(if($null -ne $decision){$decision.sha256}else{$null});candidate_sha256=$(if($null -ne $candidate){$candidate.sha256}else{$null});
            outcome=$outcome;mode=$mode;automatic_retry_allowed=$false}
        return New-StagerOutput $code $document (Format-StagerStatusLine 'HELD' $null $null $outcome $mode $null $(if($null -ne $target){$target.state}else{$null}) $code $reason)
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

function Invoke-StagePipelineConfigR5Entry {
    param($Arguments,[string]$ScriptPath,[string]$ScriptDirectory)
    # The run-time caller of the main function: prints its lines (the last is the compact status line) and returns the exit code.
    $exitCode=30
    try{
        $result=Invoke-StagePipelineConfigR5Main -Arguments $Arguments -ScriptPath $ScriptPath -ScriptDirectory $ScriptDirectory
        foreach($line in @($result.lines)){[Console]::Out.WriteLine([string]$line)}
        $exitCode=[int]$result.exit_code
    }catch{
        [Console]::Out.WriteLine((Format-StagerStatusLine 'HELD' $null $null $null $null $null $null 30 ('Internal error: '+$_.Exception.Message)))
        $exitCode=30}
    [Console]::Out.Flush()
    $exitCode
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
exit (Invoke-StagePipelineConfigR5Entry -Arguments ([ordered]@{BuildDirectory=$BuildDirectory;Apply=[bool]$Apply;Attempt=$Attempt}) -ScriptPath $PSCommandPath -ScriptDirectory $PSScriptRoot)
