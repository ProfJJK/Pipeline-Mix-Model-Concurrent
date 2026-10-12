#Requires -Version 5.1
<# Agy isolation and model-identity evidence under the worker tokens (Gemini build-manifest step 6; r5 sitting stage S8).
   Same task/launch skeleton as agy-status-capture-r4-v1.ps1 (sha256 90d56123..., the r5 onboarding-audit re-pin: preconditions, one-shot SYSTEM task, receipt
   verification) and the house pattern of retarget-warden-r4.ps1 v2.2 (sha256 8ee6b412...: Import-ReviewedFunctions, r4
   bindings, private directories). Every reviewed helper is imported by hash; the top level is a single invocation so fixtures
   can dot-source the functions from the AST without running anything.
   Default is a read-only plan (cochem-agy-isolation-evidence-plan/1); it creates nothing and runs no native command.
   Two modes, each a separate one-shot SYSTEM task (PT10M) under its own fresh root:
     -Slot slot1 [-EffortNullSlug gemini-3.8-flash-low] (evidence, gate G3): root
        C:\Program Files\CoChem\AgyIsolation4.2.7-windows-20261011-r4-v1-<attempt>, receipt isolation-receipt.json. The helper
        stages the protected agent (SYSTEM/BA full, worker read-only) at %USERPROFILE%\.gemini\agents\cochem-inference-only and
        %USERPROFILE%\.gemini\config\agents\cochem-inference-only of the slot1 worker, inventories the six worker profiles, attests
        the worker environment block (names only), runs four non-inference pre-check probes and, only when the slot is signed in
        and resolves exactly the protected agent, the model-form matrix R1 gemini-3.8-flash-high, R5 the owner's effort-null
        slug, R2 + --effort high, R3 gemini-3.8-flash + --effort high, R4 gemini-3.1-pro-preview (expected rejection): at most
        five bounded model jobs, up to four answers to the prompt 'Reply with exactly: ready true'. Raw streams stay in raw\
        (SYSTEM/BA only, never published); redacted replay copies for config-builder gate G5 are in replay\. G3 also inventories
        every agy customization location (profile ~/.gemini/config incl. config.json, skills.json, plugins.json; the .agents,
        .agent, _agents and _agent folders plus skills.json/plugins.json in the slot root, the RAM workspace and EVERY ancestor of
        both up to the drive root), requires C:\ProgramData\Antigravity absent or the protected empty folder, and fails on any
        process beyond agy's own tree in a run's Job, on any entry in ~/.gemini/config/sidecars, and on a true model-fallback
        phrase in a cli-*.log file an accepted run created (normal resolution lines are only counted). Runs skipped by the deadline guard after a passing R1 keep the evidence
        complete (gate on R1; the skipped runs stay unbound).
     -StageOnly (staging and listing, gate G4): root ...-<attempt>-stage, receipt stage-receipt.json. The helper first creates
        C:\ProgramData\Antigravity as the protected empty folder (SYSTEM owner, SYSTEM/BA full, Users read and execute) or accepts
        it only when it already is exactly that folder (anything else is refused and preserved), stages the same pinned agent
        with the same ACL into all six worker profiles at both locations, protects both parent folders (.gemini\agents and
        .gemini\config\agents: worker list and traverse only) and proves under each worker token that
        '--output-format json agents' and 'agents' list exactly cochem-inference-only. No model job.
   -Apply (AETHERDESK\ansac in elevated 64-bit Windows PowerShell 5.1, nonzero -Attempt):
     1. binds the reviewed r4 runtime (install receipt 629c87ec..., revision 38a99c3f..., layout, windows.py, resource_limits.py,
        preserved-denial pin), the agy.exe pin 38f30c7d..., this helper's pin and the cochem-inference-only.agent.md pin; requires
        the four daemon tasks stopped and disabled, no existing root or task, and inspects the r4, toolchain and native code trees;
     2. creates the root with a SYSTEM/BA-only DACL, copies the hash-pinned helper and agent definition and writes the intent
        record before any task exists;
     3. registers ONE trigger-free SYSTEM task (PT10M, private task DACL, registration flags 18 =
        TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE), requests exactly one Run and waits for it to end;
     4. verifies the receipt against the pins, recomputes every check, verdict and gate, verifies the raw and replay digests, and
        writes the summary (CreateNew).
   Exit codes: 0 gate passed (summary JSON on stdout); 10 GEMINI-HELD: the evidence is verified but its gate failed (A4: the
   sitting continues in Gemini-held mode; the held record and a COCHEM_AGY_..._RESULT line are written); 1 refused or held by an
   error (held record written when the root exists). Nothing is ever retried, deleted, stopped or killed; the task, the root and
   the staged agent are preserved as evidence. #>
[CmdletBinding(DefaultParameterSetName='Evidence')]
param(
    # No [ValidateSet] on -Slot or -EffortNullSlug: in -StageOnly mode Set-IsolationConstants writes '' to $script:Slot and
    # $script:effortNullSlug (the same variables), which a validated parameter rejects (2026-10-11 r5 sitting).
    # Invoke-AgyIsolationMain enforces slot1 and the three gemini-3.8-flash slugs case-sensitively.
    [Parameter(Mandatory=$true,ParameterSetName='Evidence')][string]$Slot,
    [Parameter(ParameterSetName='Evidence')][string]$EffortNullSlug='gemini-3.8-flash-low',
    [Parameter(Mandatory=$true,ParameterSetName='Stage')][switch]$StageOnly,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$Attempt='00000000000000000000000000000000',
    [switch]$Apply
)

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

function Set-IsolationConstants {
    param([string]$Mode,[string]$Slot,[string]$Attempt,[string]$Workspace,[string]$EffortNullSlug)
    $script:Mode=$Mode;$script:Slot=$Slot;$script:Attempt=$Attempt;$script:workspace=$Workspace;$script:effortNullSlug=$EffortNullSlug
    # The v2.2 pin block (values unchanged) used by the imported Assert-R4InstalledBindings.
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:r3Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261007-r3'
    $script:r4Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4';$script:r4Python=Join-Path $script:r4Root '.venv\Scripts\python.exe'
    $script:basePythonRoot=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    $script:probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:r3ManifestPin='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';$script:r3InstallPin='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
    $script:r3RevisionPin='309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
    $script:r4ManifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';$script:repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
    # The manifest's further r4 pins (install-after key names verified on disk).
    $script:r4InstallPin='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';$script:r4RevisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    $script:r4LayoutPin='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4';$script:windowsPin='ca07b3bba2b22d0eb095c1f05b9a6c0969207bf7d8b25741adbaee184f4618ba'
    $script:resourcePin='de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f';$script:preservedDenialPin='691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d'
    $script:venvConfigPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d';$script:venvPythonPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $script:nativeRoot=Join-Path $script:base 'Native4.2.7-windows-20261006';$script:nativeExecutable=Join-Path $script:nativeRoot 'agy.exe'
    $script:agyPin='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741';$script:agyVersion='1.3.1'
    $script:helperName='agy_isolation_evidence_r4_v1.py';$script:helperSource=Join-Path $Workspace $script:helperName
    $script:helperPin='e6e2af9a69a6b14a57b215d47dbd4d3040610b5f812f6ea3bd36d9ffbf1705d1'
    $script:agentFileName='cochem-inference-only.agent.md';$script:agentSource=Join-Path $Workspace $script:agentFileName
    $script:agentPin='5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810';$script:agentBytes=478;$script:agentName='cochem-inference-only'
    $script:agentRelatives=@('.gemini/agents/cochem-inference-only/agent.md','.gemini/config/agents/cochem-inference-only/agent.md')
    $script:fileSddlPattern='^O:SYG:SYD:P\(A;;FA;;;SY\)\(A;;FA;;;BA\)\(A;;0x120089;;;(S-1-5-21-[0-9-]+)\)$'
    $script:directorySddlPattern='^O:SYG:SYD:P\(A;OICI;FA;;;SY\)\(A;OICI;FA;;;BA\)\(A;OICI;0x1200a9;;;(S-1-5-21-[0-9-]+)\)$'
    # Fixed namespace date (this component's build date); the helper refuses any other root name.
    $script:isolationNamespaceDate='20261011'
    $suffix=$(if($Mode -ceq 'stage'){'-stage'}else{''})
    $script:targetRoot=Join-Path $script:base ('AgyIsolation4.2.7-windows-'+$script:isolationNamespaceDate+'-r4-v1-'+$Attempt+$suffix)
    $script:taskName='CoChem-4.2.7-AgyIsolation-'+$script:isolationNamespaceDate+'-r4-v1-'+$Attempt+$suffix
    $prefix=$(if($Mode -ceq 'stage'){'stage'}else{'isolation'})
    $script:receiptName=$prefix+'-receipt.json';$script:summaryName=$prefix+'-summary.json';$script:heldName=$prefix+'-held.json'
    $script:intentName=$prefix+'-intent.json';$script:taskXmlName=$prefix+'-task.xml'
    $script:resultTag=$(if($Mode -ceq 'stage'){'COCHEM_AGY_AGENT_STAGING_RESULT'}else{'COCHEM_AGY_ISOLATION_EVIDENCE_RESULT'})
    $script:geminiGate=$(if($Mode -ceq 'stage'){'G4'}else{'G3'})
    $script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';$script:taskTimeLimit='PT10M';$script:taskWaitSeconds=595
    # Registration flags 18 = TASK_CREATE (0x2) | TASK_DONT_ADD_PRINCIPAL_ACE (0x10), still create-only. With 2 alone this host
    # stores the task DACL unprotected with an appended (A;;FR;;;SY) ACE, which Assert-RegisteredTaskAcl refuses (r5 sitting v2,
    # 2026-10-11, same API path as the held S3/S5/S10 tasks). 18 kept the exact protected two-ACE DACL and passed the same
    # validator on 2026-10-08 (resume-pending-warden-r3-v7.ps1:125, TaskAclRecovery4.2.7-windows-20261008-r3-v1).
    $script:taskRegistrationFlags=18
    $script:daemonTaskNames=@('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')
    $script:profileParent='C:\Users';$script:workerIdentity='CoChem422Worker1'
    $script:workerIdentities=@(1..6|ForEach-Object {'CoChem422Worker'+$_});$script:stageSlots=@(1..6|ForEach-Object {'slot'+$_})
    $script:slotRootBase='C:\ProgramData\CoChemPipeline427\workers';$script:ramWorkspaceRoot='R:\CoChem427-windows-20261007\slot1'
    $script:effortNullSlugs=@('gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-3.8-flash-high')
    $script:probeSeconds=30;$script:probeOutputBytes=65536;$script:runSeconds=120;$script:runOutputBytes=1048576;$script:deadlineSeconds=480
    $script:receiptMaxBytes=1048576;$script:rawMaxBytes=16777216;$script:emptySha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    $script:promptLineSha256='383e4810ee804f34f037081155a02cf68a4d9a4f099c8577afe0a57597569bfb';$script:promptLineBytes=72
    $script:primaryModel='gemini-3.8-flash-high';$script:maxModelJobs=5
    $script:productionArguments=@('--agent','cochem-inference-only','--input-format','stream-json','--output-format','stream-json','--model','{model}','--disable-slash-commands')
    $script:forbiddenFlags=@('-p','--print','--prompt','-i','--prompt-interactive','-c','--continue','--conversation','--dangerously-skip-permissions',
        '--print-timeout','--project','--new-project','--log-file','--json-schema','--mode','--sandbox','--add-dir','--remote-control')
    $script:stderrMarkers=@('AGY_ERROR:','is no longer available. Using','Model resolved via','Restored session model','resolves to a different model','defaulting to')
    $script:sensitiveNames=@('url','email','google_access_token','google_refresh_token','authorization_code','jwt','bearer','secret_field')
    $script:profilePaths=@('.gemini/config/hooks.json','.gemini/config/mcp_config.json','.gemini/config/settings.json','.gemini/config/plugins','.gemini/config/skills',
        '.gemini/config/agents','.gemini/config/rules','.gemini/config/workflows','.gemini/agents','.gemini/.agents','.gemini/antigravity-cli/hooks.json',
        '.gemini/antigravity-cli/settings.json','.gemini/antigravity-cli/mcp','.gemini/antigravity-cli/plugin_data','.gemini/antigravity-cli/cache',
        '.gemini/antigravity-cli/updater','.gemini/antigravity-cli/antigravity-oauth-token','.gemini/antigravity-cli/plugins','.gemini/antigravity-cli/skills',
        'AppData/Local/agy/bin','.gemini/config/sidecars','.gemini/config/config.json','.gemini/config/skills.json','.gemini/config/plugins.json')
    # RG-2: phrase counts over the cli-*.log files each run created (bounded); only the true fallback phrases count.
    $script:logFallbackPhrases=@('is no longer available. Using','Restored session model','resolves to a different model','Restoring model')
    $script:logBenignPhrases=@('Model resolved via default','not in local config, defaulting to CCPA')
    $script:logPathPattern='^\.gemini/antigravity-cli/log/cli-[^/]{1,200}\.log$';$script:logScanMaximum=1048576;$script:logScanFiles=8
    # O-F1: the four documented workspace folder names x {hooks.json, mcp_config.json, skills, agents}, plus the declared
    # skills.json and plugins.json; inventoried in each workspace root and in every ancestor up to the drive root.
    # Commander rule: the declared user configurations are inspected by the helper (strict JSON <= 256 KiB, key NAMES only)
    # and count as present only when their inspection is not CLEAR; workspace files stay 'present = flagged'.
    $script:declaredConfigPaths=@('.gemini/config/config.json','.gemini/config/skills.json','.gemini/config/plugins.json')
    $script:declaredConfigReasons=@('CUSTOMIZATION_KEYS','NOT_A_REGULAR_FILE','HARDLINKED','UNREADABLE','OVER_SIZE_BOUND','CHANGED_DURING_INSPECTION',
        'NOT_UTF8','TOO_DEEP','DUPLICATE_KEY','UNPARSEABLE','NOT_AN_OBJECT')
    $script:declaredConfigFragments=@('plugin','mcp','hook','skill','agent','sidecar')
    $script:workspaceDirs=@('.agents','.agent','_agents','_agent')
    $script:workspacePaths=@(foreach($folder in $script:workspaceDirs){foreach($item in @('hooks.json','mcp_config.json','skills','agents')){$folder+'/'+$item}})+@('skills.json','plugins.json')
    $script:jobProcessMaximum=2
    # O-F2: absent, or exactly the protected empty folder the -StageOnly task creates.
    $script:programDataAntigravity='C:\ProgramData\Antigravity'
    $script:programDataSddl='O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
    $script:programDataRules=@('S-1-5-18|2032127|3','S-1-5-32-544|2032127|3','S-1-5-32-545|1179817|3')
    $script:programDataStates=@('ABSENT','PROTECTED_EMPTY','NOT_EMPTY','WEAK_ACL','ACL_UNVERIFIABLE','NOT_DIRECTORY','REPARSE_POINT','UNREADABLE')
    # O-F3: the protected parents of the two agent leaves (stage mode).
    $script:agentParentRelatives=@('.gemini/agents','.gemini/config/agents')
    $script:parentSddlTemplate='O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sid})'
    $script:runCheckReasons=[ordered]@{exited_zero='R1_EXIT_NOT_ZERO';init_present='R1_INIT_MISSING';stream_well_formed='R1_STREAM_MALFORMED';tools_empty='R1_TOOLS_NOT_EMPTY';
        agent_matches='R1_AGENT_MISMATCH';model_matches='R1_MODEL_MISMATCH';no_tool_steps='R1_TOOL_STEPS';no_subagent_steps='R1_SUBAGENT_STEPS';
        only_allowed_step_types='R1_UNEXPECTED_STEP_TYPES';step_models_match='R1_STEP_MODEL_MISMATCH';result_success='R1_RESULT_NOT_SUCCESS';
        num_turns_one='R1_NUM_TURNS_NOT_ONE';result_model_absent_or_equal='R1_RESULT_MODEL_MISMATCH';no_stderr_markers='R1_STDERR_MARKERS'}
    $script:echoExempt=@('model_matches','step_models_match','result_model_absent_or_equal')
    $script:isolationReasons=@('R1_TOOLS_NOT_EMPTY','R1_TOOL_STEPS','R1_SUBAGENT_STEPS','ISOLATION_BREACH_IN_MATRIX','JOB_PROCESSES_BEYOND_AGY_TREE')
    $script:failurePhases=@('trusted_preflight','reservation','runtime_custody','layout','boundaries','native_custody','daemon_precheck','inventory_before',
        'agent_staging','profile_inventory','environment_attestation','agent_verification','precheck_launch','native_attestation','precheck_wait',
        'precheck_result','inference_launch','inference_wait','native_cleanup','inference_result','replay','stage_listing','inventory_after',
        'daemon_postcheck','verdict','programdata_guard')
}

function Get-AncestorDirectories {
    param([string]$Path)
    # Mirrors workspace_ancestors: every ancestor directory up to the drive root, nearest first.
    $current=[IO.Path]::GetDirectoryName($Path)
    while(-not [string]::IsNullOrEmpty($current)){$current;$current=[IO.Path]::GetDirectoryName($current)}
}

function Get-WorkerProfileRoot {param([string]$Identity)Join-Path $script:profileParent $Identity}

function Get-SlotRoot {param([string]$Slot)Join-Path $script:slotRootBase $Slot}

function Get-AgentDestinations {
    param([string]$Identity)
    foreach($relative in $script:agentRelatives){(Get-WorkerProfileRoot $Identity)+'\'+$relative.Replace('/','\')}
}

function Get-ExpectedPrecheck {
    # Mirrors PRECHECK of the helper (a test compares both tables).
    [pscustomobject]@{id='PC1';arguments=@('--version');kind='version'}
    [pscustomobject]@{id='PC2';arguments=@('--output-format','json','models');kind='models_json'}
    [pscustomobject]@{id='PC3';arguments=@('--output-format','json','agents');kind='agents_json'}
    [pscustomobject]@{id='PC4';arguments=@('agents');kind='agents_text'}
}

function Get-ExpectedStageProbes {
    # Mirrors STAGE_PROBES: the two agent-listing probes under every worker token.
    @(Get-ExpectedPrecheck)[2..3]
}

function Get-ExpectedRuns {
    # Mirrors run_matrix: R1, the owner's effort-null slug R5 (kept first under the deadline guard), R2, R3, R4.
    $rows=@(@('R1',$script:primaryModel,@()),@('R5',$script:effortNullSlug,@()),@('R2',$script:primaryModel,@('--effort','high')),
        @('R3','gemini-3.8-flash',@('--effort','high')),@('R4','gemini-3.1-pro-preview',@()))
    foreach($row in $rows){
        $model=$row[1];$extra=@($row[2])
        $argv=@($script:nativeExecutable)+@($script:productionArguments|ForEach-Object {if($_ -ceq '{model}'){$model}else{$_}})+$extra
        [pscustomobject]@{id=$row[0];model=$model;extra=$extra;argv=$argv}
    }
}

function Get-IsolationTaskArguments {
    param([string]$Destination,[string]$Nonce)
    if($script:Mode -ceq 'stage'){return ('-I -B "'+$Destination+'" --mode stage --nonce '+$Nonce+' --attempt '+$script:Attempt)}
    '-I -B "'+$Destination+'" --mode evidence --slot '+$script:Slot+' --effort-null-slug '+$script:effortNullSlug+' --nonce '+$Nonce+' --attempt '+$script:Attempt
}

function New-IsolationNonce {[Guid]::NewGuid().ToString('N')}

function Get-SeriesDaemonTaskStates {
    param($Folder)
    # The four daemon names of the sign-in series precondition; observer/recorder tasks are deliberately not listed.
    $states=@()
    foreach($name in $script:daemonTaskNames){
        $task=$null;$absent=$false;$denied=$false
        try{$task=$Folder.GetTask($name)}catch{
            $errorItem=$_.Exception
            while($null -ne $errorItem){
                if($errorItem.HResult -eq -2147024894){$absent=$true;break}
                if($errorItem.HResult -eq -2147024891){$denied=$true;break}
                $errorItem=$errorItem.InnerException}
            if(-not $absent -and -not $denied){throw ('Daemon task state is unknown: '+$name)}}
        if($absent){$states+=[pscustomobject]@{name=$name;state='ABSENT';active=$false};continue}
        if($denied){$states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';active=$null};continue}
        try{$active=([bool]$task.Enabled -or [int]$task.State -notin @(1,3) -or [int]$task.GetInstances(0).Count -ne 0)}catch{
            $errorItem=$_.Exception;$partial=$false
            while($null -ne $errorItem){if($errorItem.HResult -eq -2147024891){$partial=$true;break};$errorItem=$errorItem.InnerException}
            if(-not $partial){throw ('Daemon task could not be read: '+$name)}
            $states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';active=$null};continue}
        $states+=[pscustomobject]@{name=$name;state=$(if($active){'ACTIVE'}else{'STOPPED_DISABLED'});active=$active}
    }
    $states
}

function Get-TaskPresence {
    param($Folder,[string]$Name)
    try{$null=$Folder.GetTask($Name);return 'PRESENT'}catch{
        $errorItem=$_.Exception
        while($null -ne $errorItem){
            if($errorItem.HResult -eq -2147024894){return 'ABSENT'}
            if($errorItem.HResult -eq -2147024891){return 'PRESENT_UNREADABLE'}
            $errorItem=$errorItem.InnerException}
        throw ('Task Scheduler state is unknown for '+$Name)}
}

function Assert-IsolationRuntimePins {
    param($Runtime)
    # The manifest's r4 pins beyond the v2.2 content bindings, with the real install-after key names.
    if($Runtime.install_receipt_sha256 -cne $script:r4InstallPin){throw 'The r4 installation receipt is not the pinned receipt.'}
    if($Runtime.revision_sha256 -cne $script:r4RevisionPin){throw 'The r4 installed revision is not the pinned revision.'}
    $after=(Read-R3Text (Read-R3Control (Join-Path $script:r4Root 'install-after.json') $script:r4InstallPin 1048576))|ConvertFrom-Json
    if($after.preserved_denial_receipt_sha256 -cne $script:preservedDenialPin -or $after.reviewed_repair_sha256 -cne $script:repairPin -or
       $after.previous_install_receipt_sha256 -cne $script:r3InstallPin -or $after.previous_source_manifest_sha256 -cne $script:r3ManifestPin -or
       $after.source_manifest_sha256 -cne $script:r4ManifestPin -or $after.configuration_sha256 -cne $script:configPin -or
       -not (Test-ExactInt $after.source_files 166) -or $after.mode -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       $after.verification.revision.source_sha256 -cne $script:r4RevisionPin){throw 'The r4 install-after bindings differ from the manifest pins.'}
    $layout=Read-R3Control (Join-Path $script:r4Root 'windows-layout.json') $script:r4LayoutPin
    $null=Read-R3Control (Join-Path $script:r4Root '.venv\Lib\site-packages\cochem_pipeline\windows.py') $script:windowsPin
    $null=Read-R3Control (Join-Path $script:r4Root '.venv\Lib\site-packages\cochem_pipeline\resource_limits.py') $script:resourcePin
    [ordered]@{install_receipt_sha256=$Runtime.install_receipt_sha256;source_manifest_sha256=$Runtime.source_manifest_sha256;revision_sha256=$Runtime.revision_sha256;
        configuration_sha256=$script:configPin;layout_sha256=$layout.Sha256;windows_runtime_sha256=$script:windowsPin;resource_limits_sha256=$script:resourcePin;
        reviewed_repair_sha256=$script:repairPin;preserved_denial_receipt_sha256=$script:preservedDenialPin}
}

function New-IsolationTaskDefinition {
    param($Scheduler,[string]$Destination,[string]$Nonce)
    $definition=$Scheduler.NewTask(0)
    if($script:Mode -ceq 'stage'){
        $definition.RegistrationInfo.Description='One bounded staging of the pinned cochem-inference-only agent into the six worker profiles (r5 sitting S8, gate G4) with the agent listing checked under each worker token. No model job, login input, daemon activation or credential copying.'}
    else{
        $definition.RegistrationInfo.Description='One bounded agy isolation and model-identity evidence run (build-manifest step 6, r5 sitting S8, gate G3) in the slot1 worker profile: protected agent staging, six-profile inventory, environment attestation, non-inference pre-check and at most five bounded stream-json model jobs. No login input, daemon activation or credential copying.'}
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$true;$definition.Settings.AllowDemandStart=$true
    $definition.Settings.MultipleInstances=2;$definition.Settings.ExecutionTimeLimit=$script:taskTimeLimit;$definition.Settings.RestartCount=0
    $action=$definition.Actions.Create(0);$action.Path=$script:r4Python
    $action.Arguments=Get-IsolationTaskArguments $Destination $Nonce
    $action.WorkingDirectory=$script:targetRoot
    $definition
}

function Assert-IsolationTaskRegistration {
    param($Task,[string]$Destination,[string]$Nonce)
    $definition=$Task.Definition
    if($Task.Enabled -ne $true -or $Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0 -or
       $definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $definition.Principal.LogonType -ne 5 -or $definition.Principal.RunLevel -ne 1 -or
       $definition.Settings.AllowDemandStart -ne $true -or $definition.Settings.MultipleInstances -ne 2 -or $definition.Settings.RestartCount -ne 0 -or
       $definition.Settings.ExecutionTimeLimit -cne $script:taskTimeLimit -or $definition.Triggers.Count -ne 0 -or $definition.Actions.Count -ne 1){
        throw 'The isolation task is not the exact idle, trigger-free, bounded SYSTEM definition.'}
    $action=$definition.Actions.Item(1)
    if($action.Type -ne 0 -or $action.Path -cne $script:r4Python -or $action.Arguments -cne (Get-IsolationTaskArguments $Destination $Nonce) -or
       $action.WorkingDirectory -cne $script:targetRoot){throw 'The registered isolation action differs from the pinned interpreter, helper and arguments.'}
    Assert-RegisteredTaskAcl ($Task.GetSecurityDescriptor(7))
}

function Wait-IsolationTaskInstance {
    param($Instance,[int]$TimeoutSeconds)
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do{
        Start-Sleep -Milliseconds 250
        try{$Instance.Refresh()}catch{
            $completed=$false;$exception=$_.Exception
            while($null -ne $exception){if($exception.HResult -eq -2147216629){$completed=$true;break};$exception=$exception.InnerException}
            # SCHED_E_TASK_NOT_RUNNING ends polling only; it never proves success.
            if($completed){return}
            throw}
        if([DateTime]::UtcNow -gt $deadline){throw ('the isolation task did not end within '+$TimeoutSeconds+' s (task limit '+$script:taskTimeLimit+')')}
    }while($Instance.State -in @(2,4))
}

function Assert-CompletedIsolationTask {
    param($Task)
    if($Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0){throw 'the isolation task is not conclusively terminal'}
}

function Test-StringList {
    param($Value,[string]$Pattern,[int]$Maximum)
    if($null -eq $Value){return $false}
    $items=@($Value)
    if($items.Count -gt $Maximum){return $false}
    foreach($item in $items){if($item -isnot [string] -or $item -cnotmatch $Pattern){return $false}}
    $true
}

function Test-SameStrings {
    param($Actual,[object[]]$Expected)
    $items=@($Actual)
    if($null -eq $Actual){$items=@()}
    if($items.Count -ne $Expected.Count){return $false}
    for($i=0;$i -lt $Expected.Count;$i++){if($items[$i] -isnot [string] -or $items[$i] -cne $Expected[$i]){return $false}}
    $true
}

function Test-HasProperty {param($Value,[string]$Name)($null -ne $Value) -and ($null -ne $Value.PSObject.Properties[$Name])}

function Test-SensitiveText {
    # Independent re-check of a replay copy: account- or credential-looking spans must have been redacted by the helper.
    param([string]$Text)
    foreach($pattern in @('(?i)https?://','[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+','ya29\.[A-Za-z0-9._-]{8,}','1//0[A-Za-z0-9._-]{8,}',
        '4/0[A-Za-z0-9._-]{8,}','eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}','(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}',
        '(?i)(access_token|refresh_token|id_token|client_secret|api[_-]?key|password)["'']?\s*[:=]\s*["'']?(?!REDACTED_)[^"''\s,}]')){
        if($Text -cmatch $pattern){return $true}}
    $false
}

function Assert-RawStream {
    param($Record,[string]$Stream,[string]$Root,[string]$Label,[string]$BaseName)
    $value=$Record.$Stream
    if($Record.raw_path.$Stream -cne ('raw/'+$BaseName+'.'+$Stream) -or $value.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
       (($value.bytes -isnot [int]) -and ($value.bytes -isnot [long])) -or $value.bytes -lt 0 -or $value.bytes -gt $script:rawMaxBytes -or
       -not (Test-HasProperty $value 'sensitive_patterns')){throw ($Label+' '+$Stream+' evidence is invalid.')}
    $patterns=@($value.sensitive_patterns);if($null -eq $value.sensitive_patterns){$patterns=@()}
    foreach($name in $patterns){if($name -isnot [string] -or $name -cnotin $script:sensitiveNames){throw ($Label+' '+$Stream+' sensitive-pattern names are outside their allowlist.')}}
    $control=Read-R3Control (Join-Path $Root ('raw\'+$BaseName+'.'+$Stream)) $value.sha256 $script:rawMaxBytes
    if($control.Length -ne $value.bytes){throw ($Label+' raw '+$Stream+' length differs from the receipt.')}
    $patterns
}

function Assert-ReplayStreams {
    param($Record,[string]$Root,[string]$Label)
    # The G5 replay copy: CreateNew files under replay\, digests bound, and no account- or credential-looking text left.
    if(-not (Test-HasProperty $Record 'replay')){throw ($Label+' carries no replay record.')}
    $r=$Record.replay
    if(-not (Test-ExactBool $r.available $true)){
        if($r.available -isnot [bool] -or $r.reason -cnotin @('raw_stream_over_bound','redaction_incomplete')){throw ($Label+' replay record is invalid.')}
        return $false}
    if($null -ne $r.reason){throw ($Label+' replay record is invalid.')}
    foreach($stream in @('stdout','stderr')){
        $v=$r.$stream
        if($v.path -cne ('replay/'+$Record.id+'.'+$stream) -or $v.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
           (($v.bytes -isnot [int]) -and ($v.bytes -isnot [long])) -or $v.bytes -lt 0 -or $v.bytes -gt $script:runOutputBytes){throw ($Label+' replay '+$stream+' evidence is invalid.')}
        foreach($p in @($v.redactions.PSObject.Properties)){
            if($p.Name -cnotin $script:sensitiveNames -or -not ((($p.Value -is [int]) -or ($p.Value -is [long])) -and $p.Value -gt 0)){throw ($Label+' replay '+$stream+' redaction counts are invalid.')}}
        $control=Read-R3Control (Join-Path $Root ('replay\'+$Record.id+'.'+$stream)) $v.sha256 $script:runOutputBytes
        if($control.Length -ne $v.bytes){throw ($Label+' replay '+$stream+' length differs from the receipt.')}
        if(Test-SensitiveText (Read-R3Text $control)){throw ($Label+' replay '+$stream+' still carries account- or credential-looking text.')}}
    $true
}

function Assert-ProcessAttestation {
    param($Record,[string]$Label)
    $p=$Record.process
    foreach($key in @('token_matches_selected_worker','image_matches_reviewed_executable','owned_job_membership_verified','profile_matches_inventory_root')){
        if(-not (Test-ExactBool $p.$key $true)){throw ($Label+' process attestation is incomplete.')}}
    if($p.image_query_format -cnotin @('win32','native_after_exit')){throw ($Label+' image attestation format is invalid.')}
}

function Assert-JobAccounting {
    param($Record,[string]$Label)
    # O-F1: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION of the owned Job, read after TerminateJobObject (final counts).
    if(-not (Test-HasProperty $Record 'job_accounting') -or $null -eq $Record.job_accounting){throw ($Label+' carries no Job process accounting.')}
    $j=$Record.job_accounting
    foreach($key in @('total_processes','active_processes','total_terminated_processes')){
        if(-not (Test-HasProperty $j $key)){throw ($Label+' Job process accounting is invalid.')}
        $v=$j.$key;if((($v -isnot [int]) -and ($v -isnot [long])) -or $v -lt 0){throw ($Label+' Job process accounting is invalid.')}}
    if(-not (Test-HasProperty $j 'expected_maximum') -or -not (Test-ExactInt $j.expected_maximum $script:jobProcessMaximum) -or
       -not (Test-HasProperty $j 'queried_after_job_termination') -or -not (Test-ExactBool $j.queried_after_job_termination $true)){throw ($Label+' Job process accounting is invalid.')}
}

function Assert-LogScan {
    param($Record,[string]$Label)
    # Mirrors scan_run_logs (RG-2): new and changed cli-*.log files; no log contents.
    if(-not (Test-HasProperty $Record 'log_scan') -or $null -eq $Record.log_scan){throw ($Label+' carries no log scan.')}
    $l=$Record.log_scan
    foreach($key in @('log_scanned','files','files_skipped','files_unscanned','maximum_bytes_per_file','fallback_phrases','benign_phrases','fallback_found')){
        if(-not (Test-HasProperty $l $key)){throw ($Label+' log scan is incomplete.')}}
    $files=@($l.files);if($null -eq $l.files){$files=@()}
    $skipped=@($l.files_skipped);if($null -eq $l.files_skipped){$skipped=@()}
    if(-not (Test-ExactInt $l.maximum_bytes_per_file $script:logScanMaximum) -or (($l.files_unscanned -isnot [int]) -and ($l.files_unscanned -isnot [long])) -or
       $l.files_unscanned -lt 0 -or ($files.Count+$skipped.Count) -gt $script:logScanFiles){throw ($Label+' log scan bounds are invalid.')}
    foreach($f in $files){
        if($f.path -cnotmatch $script:logPathPattern -or $f.sha256 -cnotmatch '^[a-f0-9]{64}$' -or (($f.bytes -isnot [int]) -and ($f.bytes -isnot [long])) -or
           $f.bytes -lt 0 -or $f.bytes -gt $script:logScanMaximum -or $f.truncated -isnot [bool]){throw ($Label+' log scan file record is invalid.')}}
    foreach($p in $skipped){if($p -isnot [string] -or $p -cnotmatch $script:logPathPattern){throw ($Label+' log scan file record is invalid.')}}
    $incomplete=($skipped.Count -gt 0 -or $l.files_unscanned -gt 0 -or @($files|Where-Object {$_.truncated}).Count -gt 0)
    if(-not (Test-HasProperty $l 'incomplete') -or -not (Test-ExactBool $l.incomplete $incomplete)){throw ($Label+' log scan completeness differs from its retained ranges.')}
    $changes=$(if(Test-HasProperty $Record 'profile_changes'){$Record.profile_changes}else{$null})
    if($null -ne $changes -and -not (Test-HasProperty $changes 'omitted_for_receipt_bound')){
        $created=@(@($changes.new_files)|Where-Object {$null -ne $_ -and $_.path -cmatch $script:logPathPattern -and $_.path -cnotmatch '(?i)token'}|ForEach-Object {$_.path})
        $created=@(@($created)+@($changes.changed_files|Where-Object {$_ -is [string] -and $_ -cmatch $script:logPathPattern -and $_ -cnotmatch '(?i)token'})|Sort-Object -Unique -CaseSensitive)
        $covered=@(@($files|ForEach-Object {$_.path})+$skipped)
        $exact=$(if($created.Count -le $script:logScanFiles){Test-SameStrings @($covered|Sort-Object -CaseSensitive) @($created|Sort-Object -CaseSensitive)}
                 else{($covered.Count -eq $script:logScanFiles) -and @($covered|Where-Object {$_ -cnotin $created}).Count -eq 0})
        if(-not $exact -or -not (Test-ExactInt $l.files_unscanned ([long][Math]::Max(0,$created.Count-$script:logScanFiles)))){
            throw ($Label+' log scan does not cover exactly the log files this run created or changed.')}}
    $sums=@{}
    foreach($pair in @(@('fallback_phrases',$script:logFallbackPhrases),@('benign_phrases',$script:logBenignPhrases))){
        $counts=$l.($pair[0]);$sum=0
        if($null -eq $counts -or -not (Test-SameStrings @(@($counts.PSObject.Properties|ForEach-Object {$_.Name})|Sort-Object -CaseSensitive) @(@($pair[1])|Sort-Object -CaseSensitive))){
            throw ($Label+' log scan phrases differ from the reviewed phrases.')}
        foreach($p in $counts.PSObject.Properties){$v=$p.Value;if((($v -isnot [int]) -and ($v -isnot [long])) -or $v -lt 0){throw ($Label+' log scan counts are invalid.')};$sum+=$v}
        $sums[$pair[0]]=$sum}
    if(-not (Test-ExactBool $l.fallback_found ($sums['fallback_phrases'] -gt 0)) -or -not (Test-ExactBool $l.log_scanned ($files.Count -gt 0)) -or
       ($files.Count -eq 0 -and ($sums['fallback_phrases'] -ne 0 -or $sums['benign_phrases'] -ne 0))){throw ($Label+' log scan summary contradicts its counts.')}
}

function Assert-LaunchOutcome {
    param($Record,[int]$Bound,[string]$Label)
    if($Record.outcome -cnotin @('exited','timed_out_terminated','output_bound_terminated')){throw ($Label+' outcome is invalid.')}
    if($Record.outcome -ceq 'exited'){if(($Record.exit_code -isnot [int]) -and ($Record.exit_code -isnot [long])){throw ($Label+' exit code is invalid.')}}
    elseif($Record.exit_code -isnot [string] -or $Record.exit_code -cne 'terminated'){throw ($Label+' exit code is invalid.')}
    if((($Record.elapsed_ms -isnot [int]) -and ($Record.elapsed_ms -isnot [long])) -or $Record.elapsed_ms -lt 0 -or $Record.elapsed_ms -gt (($Bound+15)*1000)){throw ($Label+' elapsed time is invalid.')}
    if(-not (Test-ExactBool $Record.cleanup_verified $true)){throw ($Label+' cleanup is not verified.')}
}

function Assert-PrecheckRecord {
    param($Record,$Expected,[string]$Root,[string]$BaseName)
    $label='Pre-check '+$BaseName
    if($Record.id -cne $Expected.id -or $Record.kind -cne $Expected.kind -or $Record.stdin_mode -cne 'empty_file'){throw ('The pre-check order differs at '+$BaseName+'.')}
    if(-not (Test-SameStrings $Record.argv (@($script:nativeExecutable)+@($Expected.arguments)))){throw ($label+' argv differs.')}
    if(-not (Test-ExactInt $Record.bound_seconds $script:probeSeconds) -or -not (Test-ExactInt $Record.output_limit_bytes $script:probeOutputBytes) -or
       -not (Test-ExactInt $Record.stdin_bytes_written 0) -or $Record.stdin_sha256 -cne $script:emptySha256 -or $Record.phase_reached -cne 'precheck_result'){
        throw ($label+' bound or stdin evidence differs.')}
    Assert-LaunchOutcome $Record $script:probeSeconds $label
    Assert-ProcessAttestation $Record $label
    Assert-JobAccounting $Record $label
    foreach($stream in @('stdout','stderr')){$null=Assert-RawStream $Record $stream $Root $label $BaseName}
    $c=$Record.classification
    foreach($key in @('timed_out','output_bound_exceeded','utf8_valid','stdout_empty','stderr_empty')){if($c.$key -isnot [bool]){throw ($label+' classification '+$key+' is not a boolean.')}}
    if($c.timed_out -ne ($Record.outcome -ceq 'timed_out_terminated')){throw ($label+' timeout classification contradicts its outcome.')}
    switch($Expected.kind){
        'version'{if($c.version_matches -isnot [bool]){throw ($label+' version classification is invalid.')}}
        'models_json'{if($c.status_helper_classification -cnotin @('LOGGED_IN','LOGGED_OUT','HOLD') -or $c.gemini_row_present -isnot [bool] -or
            ((-not (Test-StringList @($c.model_ids) '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$' 64)) -and @($c.model_ids).Count -ne 0)){throw ($label+' models classification is outside its allowlist.')}
            if($c.status_helper_classification -ceq 'LOGGED_IN' -and -not ((Test-ExactInt $Record.exit_code 0) -and $c.status_value -ceq 'SUCCESS' -and $c.gemini_row_present -eq $true)){
                throw ($label+' signed-in classification contradicts its envelope fields.')}}
        default{if(-not (Test-StringList @($c.agents) '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' 64) -and @($c.agents).Count -ne 0){throw ($label+' agents list is outside its allowlist.')}
            if(($null -ne $c.agents_count -and (($c.agents_count -isnot [int]) -and ($c.agents_count -isnot [long]))) -or -not (Test-ExactInt $c.agents_unlisted ([long]$c.agents_unlisted))){
                throw ($label+' agents counts are invalid.')}
            if($Expected.kind -ceq 'agents_json' -and (($null -ne $c.command_name -and $c.command_name -cnotin @('agents','models','OTHER')) -or
               ($null -ne $c.status_value -and $c.status_value -cnotin @('SUCCESS','ERROR','CANCELED','INTERRUPTED','INVALID','WAITING','RUNNING','OTHER')))){
                throw ($label+' agents envelope fields are outside their allowlist.')}}
    }
}

function Test-AgentsProbe {
    param($Probe,[bool]$JsonForm)
    # Mirrors agents_probe_ok: exit 0 and exactly ['cochem-inference-only'] (plus status SUCCESS / command.name agents for JSON).
    if($null -eq $Probe){return $false}
    $c=$Probe.classification
    if($Probe.outcome -cne 'exited' -or -not (Test-ExactInt $Probe.exit_code 0) -or -not (Test-SameStrings $c.agents @($script:agentName)) -or
       -not (Test-ExactInt $c.agents_unlisted 0) -or -not (Test-ExactInt $c.agents_count 1)){return $false}
    if($JsonForm -and ($c.status_value -cne 'SUCCESS' -or $c.command_name -cne 'agents')){return $false}
    $true
}

function Get-ListingReasons {
    param($Probes)
    $by=@{};foreach($p in @($Probes)){if($null -ne $p){$by[$p.id]=$p}}
    # Emitted one reason per pipeline item; callers collect with @(...).
    if(-not (Test-AgentsProbe $by['PC3'] $true)){'AGENTS_JSON_LISTING_FAILED'}
    if(-not (Test-AgentsProbe $by['PC4'] $false)){'AGENTS_TEXT_LISTING_FAILED'}
}

function Get-PrecheckDecision {
    param($Probes,$Shadows)
    # Mirrors precheck_decision: model jobs run only when the slot is signed in and resolves exactly the protected agent.
    $by=@{};foreach($p in @($Probes)){$by[$p.id]=$p.classification}
    $reasons=[Collections.Generic.List[string]]::new()
    if(-not $by.ContainsKey('PC1') -or -not (Test-ExactBool $by['PC1'].version_matches $true)){$reasons.Add('PRECHECK_VERSION_MISMATCH')}
    if(-not $by.ContainsKey('PC2') -or $by['PC2'].status_helper_classification -cne 'LOGGED_IN'){$reasons.Add('PRECHECK_NOT_SIGNED_IN')}
    if(@(Get-ListingReasons $Probes).Count){$reasons.Add('AGENTS_PRECHECK_FAILED')}
    if(@($Shadows).Count -gt 0 -and $null -ne $Shadows){$reasons.Add('AGENT_SHADOW_FOUND')}
    [pscustomobject]@{passed=($reasons.Count -eq 0);reasons=@($reasons)}
}

function Get-RunChecks {
    param($Run)
    # Mirrors run_checks: the 3B identity and isolation contract recomputed from the classification fields.
    $c=$Run.classification;$s=$c.stream;$init=$s.init;$steps=$s.steps;$res=$s.result
    $initPresent=(Test-ExactBool $s.init_present $true) -and ($null -ne $init)
    $resultPresent=(Test-ExactBool $s.result_present $true) -and ($null -ne $res)
    $checks=[ordered]@{}
    $checks.exited_zero=(($Run.outcome -ceq 'exited') -and (Test-ExactInt $Run.exit_code 0))
    $checks.init_present=$initPresent
    $checks.stream_well_formed=((Test-ExactBool $c.utf8_valid $true) -and (Test-ExactBool $c.output_bound_exceeded $false) -and (Test-ExactInt $s.malformed_lines 0) -and
        (Test-ExactInt $s.non_object_lines 0) -and (Test-ExactBool $s.lines_truncated $false) -and (Test-ExactBool $s.first_event_init $true) -and
        (Test-ExactBool $s.last_event_result $true) -and (Test-ExactBool $s.conversation_ids_consistent $true))
    $checks.tools_empty=($initPresent -and (Test-ExactBool $init.tools_is_list $true) -and (Test-ExactInt $init.tools_count 0))
    $checks.agent_matches=($initPresent -and ($init.agent -ceq $script:agentName))
    $checks.model_matches=($initPresent -and ($init.model -ceq $Run.requested_model))
    $checks.no_tool_steps=((Test-ExactInt $steps.tool_name_count 0) -and (Test-ExactInt $steps.tool_info_count 0) -and (Test-ExactInt $steps.step_type_tool_count 0))
    $checks.no_subagent_steps=(Test-ExactInt $steps.subagent_info_count 0)
    $checks.only_allowed_step_types=(Test-ExactInt $steps.disallowed_step_type_count 0)
    $checks.step_models_match=(Test-ExactInt $steps.model_mismatch_count 0)
    $checks.result_success=($resultPresent -and ($res.status -ceq 'SUCCESS') -and (Test-ExactBool $res.error_present $false) -and
        (Test-ExactBool $res.response_present $true) -and (Test-ExactBool $res.permission_denials_present $false))
    $checks.num_turns_one=($resultPresent -and (Test-ExactInt $res.num_turns 1))
    $checks.result_model_absent_or_equal=(-not ($resultPresent -and (Test-ExactBool $res.model_field_present $true) -and ($res.model -cne $Run.requested_model)))
    $markerHit=$false;foreach($marker in $script:stderrMarkers){if(-not (Test-ExactBool $c.stderr_markers.$marker $false)){$markerHit=$true}}
    $checks.no_stderr_markers=(-not $markerHit)
    $checks.accepted=($checks.exited_zero -and $checks.result_success)
    $total=$null;if((Test-HasProperty $Run 'job_accounting') -and (Test-HasProperty $Run.job_accounting 'total_processes')){$total=$Run.job_accounting.total_processes}
    $checks.job_processes_within_tree=((($total -is [int]) -or ($total -is [long])) -and $total -ge 1 -and $total -le $script:jobProcessMaximum)
    $checks.isolation_breach=(($initPresent -and -not $checks.tools_empty) -or -not $checks.no_tool_steps -or -not $checks.no_subagent_steps -or
        -not $checks.job_processes_within_tree)
    $all=$true;foreach($name in $script:runCheckReasons.Keys){if(-not $checks[$name]){$all=$false}}
    $checks.passes_contract=$all
    $echoed=$(if($initPresent){$init.model}else{$null})
    $checks.echo_consistent=($initPresent -and (Test-ExactBool $init.model_present $true) -and ($echoed -is [string]) -and ($echoed -cne 'OTHER') -and
        (Test-ExactInt $steps.model_init_mismatch_count 0) -and -not ($resultPresent -and (Test-ExactBool $res.model_field_present $true) -and ($res.model -cne $echoed)))
    $withEcho=$checks.echo_consistent;foreach($name in $script:runCheckReasons.Keys){if($name -cnotin $script:echoExempt -and -not $checks[$name]){$withEcho=$false}}
    $checks.passes_with_echo=$withEcho
    $checks
}

function Assert-RunRecord {
    param($Record,$Expected,[string]$Root)
    $label='Run '+$Expected.id
    if($Record.id -cne $Expected.id -or $Record.requested_model -cne $Expected.model -or -not (Test-SameStrings $Record.extra_arguments $Expected.extra)){throw ('The run order differs at '+$Expected.id+'.')}
    if(-not (Test-SameStrings $Record.argv $Expected.argv)){throw ($label+' argv differs from the production form.')}
    foreach($arg in @($Record.argv)){if($arg.Split('=')[0] -cin $script:forbiddenFlags){throw ($label+' argv carries a forbidden flag.')}}
    if($Record.stdin_mode -cne 'pipe_one_ndjson_line_then_eof' -or -not (Test-ExactInt $Record.bound_seconds $script:runSeconds) -or
       -not (Test-ExactInt $Record.output_limit_bytes $script:runOutputBytes) -or $Record.stdin_sha256 -cne $script:promptLineSha256 -or
       $Record.raw_path.stdin -cne ('raw/'+$Expected.id+'.stdin') -or $Record.phase_reached -cne 'inference_result'){throw ($label+' bound or stdin evidence differs.')}
    $written=$Record.stdin_bytes_written
    if((($written -isnot [int]) -and ($written -isnot [long])) -or $written -lt 0 -or $written -gt $script:promptLineBytes -or
       -not (Test-ExactBool $Record.prompt_delivered ([long]$written -eq $script:promptLineBytes))){throw ($label+' prompt delivery evidence is invalid.')}
    $null=Read-R3Control (Join-Path $Root ('raw\'+$Expected.id+'.stdin')) $script:promptLineSha256 1024
    Assert-LaunchOutcome $Record $script:runSeconds $label
    if(-not (Test-ExactBool $Record.terminated_by_bound ($Record.outcome -cne 'exited'))){throw ($label+' bound termination evidence contradicts its outcome.')}
    Assert-ProcessAttestation $Record $label
    Assert-JobAccounting $Record $label
    Assert-LogScan $Record $label
    foreach($stream in @('stdout','stderr')){$null=Assert-RawStream $Record $stream $Root $label $Expected.id}
    $null=Assert-ReplayStreams $Record $Root $label
    foreach($key in @('agent_sha256_before_launch','agent_sha256_after_run')){
        if(-not (Test-SameStrings $Record.$key @($script:agentPin,$script:agentPin))){throw ($label+' staged agent digests differ from the pin.')}}
    $c=$Record.classification;$s=$c.stream
    foreach($key in @('utf8_valid','output_bound_exceeded','timed_out','stdout_empty','stderr_empty')){if($c.$key -isnot [bool]){throw ($label+' classification '+$key+' is not a boolean.')}}
    if($c.timed_out -ne ($Record.outcome -ceq 'timed_out_terminated')){throw ($label+' timeout classification contradicts its outcome.')}
    foreach($marker in $script:stderrMarkers){if($c.stderr_markers.$marker -isnot [bool]){throw ($label+' stderr marker classification is incomplete.')}}
    if(@($c.stderr_markers.PSObject.Properties).Count -ne $script:stderrMarkers.Count){throw ($label+' stderr marker classification is incomplete.')}
    if(-not (Test-StringList @($s.reroute_keys) '^([A-Za-z_][A-Za-z0-9_]{0,63}|OTHER)$' 64) -and @($s.reroute_keys).Count -ne 0){throw ($label+' reroute key names are outside their allowlist.')}
    if($null -ne $s.init){
        if(-not (Test-StringList @($s.init.tools) '^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$' 64) -and @($s.init.tools).Count -ne 0){throw ($label+' init tool names are outside their allowlist.')}
        foreach($key in @('model','agent')){if($null -ne $s.init.$key -and $s.init.$key -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'){throw ($label+' init '+$key+' is outside its allowlist.')}}}
    if($null -ne $s.result -and $null -ne $s.result.status -and $s.result.status -cnotin @('SUCCESS','ERROR','CANCELED','INTERRUPTED','INVALID','WAITING','RUNNING','OTHER')){throw ($label+' result status is outside its allowlist.')}
    $recomputed=Get-RunChecks $Record
    foreach($key in $recomputed.Keys){if(-not (Test-ExactBool $Record.checks.$key $recomputed[$key])){throw ($label+' check '+$key+' contradicts the retained classification.')}}
    $recomputed
}

function Test-InventoryPresent {
    param($Row)
    # Mirrors present(): absence is proven only by a missing path or an empty, fully listed directory.
    if($null -eq $Row -or -not (Test-ExactBool $Row.exists $true)){return $false}
    $kind=$null;if($null -ne $Row.PSObject.Properties['kind']){$kind=$Row.kind}
    # An inspected declared user configuration is present only when its inspection is not CLEAR.
    if($kind -ceq 'file' -and (Test-HasProperty $Row 'declared_config') -and $null -ne $Row.declared_config){return ($Row.declared_config.status -cne 'CLEAR')}
    if($kind -ceq 'dir' -and (Test-ExactInt $Row.entry_count 0) -and (Test-ExactBool $Row.truncated $false)){return $false}
    $true
}

function Get-InventoryFlags {
    param($Paths,[bool]$Workspace)
    $rows=@{};foreach($row in @($Paths)){$rows[$row.path]=$row}
    $hit={param([string[]]$Names)foreach($name in $Names){if(Test-InventoryPresent $rows[$name]){return $true}};$false}
    if($Workspace){
        $wsPlugins=(& $hit @('plugins.json'))
        return [ordered]@{hooks_present=((& $hit @($script:workspaceDirs|ForEach-Object {$_+'/hooks.json'})) -or $wsPlugins);
            mcp_present=((& $hit @($script:workspaceDirs|ForEach-Object {$_+'/mcp_config.json'})) -or $wsPlugins);plugins_present=$wsPlugins;
            skills_present=((& $hit (@($script:workspaceDirs|ForEach-Object {$_+'/skills'})+@('skills.json'))) -or $wsPlugins)}}
    $plugins=(& $hit @('.gemini/config/plugins','.gemini/antigravity-cli/plugins','.gemini/antigravity-cli/plugin_data','.gemini/config/plugins.json','.gemini/config/config.json'))
    [ordered]@{hooks_present=((& $hit @('.gemini/config/hooks.json','.gemini/antigravity-cli/hooks.json','.gemini/antigravity-cli/settings.json','.gemini/config/sidecars')) -or $plugins);
        mcp_present=((& $hit @('.gemini/config/mcp_config.json','.gemini/antigravity-cli/mcp')) -or $plugins);plugins_present=$plugins;
        skills_present=((& $hit @('.gemini/config/skills','.gemini/antigravity-cli/skills','.gemini/config/skills.json')) -or $plugins);
        rules_present=(& $hit @('.gemini/config/rules'));workflows_present=(& $hit @('.gemini/config/workflows'))}
}

function Assert-InventoryRecords {
    param($Profiles,$Workspaces,[bool]$WithWorkspaces)
    $profiles=@($Profiles)
    if($profiles.Count -ne 6){throw 'The receipt does not carry exactly six worker-profile inventories.'}
    for($i=0;$i -lt 6;$i++){
        $p=$profiles[$i];$identity=$script:workerIdentities[$i]
        if($p.slot -cne ('slot'+($i+1)) -or $p.identity -cne $identity -or $p.profile_root -cne (Get-WorkerProfileRoot $identity) -or $p.profile_present -isnot [bool] -or
           -not (Test-SameStrings @($p.paths|ForEach-Object {$_.path}) $script:profilePaths)){throw ('Profile inventory '+($i+1)+' differs from the reviewed path list.')}
        foreach($row in @($p.paths)){
            if($row.exists -isnot [bool]){throw ('Profile inventory '+($i+1)+' has an untyped path record.')}
            $declared=($row.path -cin $script:declaredConfigPaths -and $row.exists -and $null -ne $row.PSObject.Properties['kind'] -and $row.kind -ceq 'file')
            if($declared){Assert-DeclaredConfig $row ('Profile inventory '+($i+1)+' '+$row.path)}
            elseif(Test-HasProperty $row 'declared_config'){throw ('Profile inventory '+($i+1)+' inspects a path that is not a declared configuration file.')}
            if($null -ne $row.PSObject.Properties['token_file'] -and $null -ne $row.sha256){throw 'A token file was hashed.'}
            if($null -ne $row.PSObject.Properties['entries']){foreach($entry in @($row.entries)){if($null -ne $entry.PSObject.Properties['token_file'] -and $null -ne $entry.sha256){throw 'A token file was hashed.'}}}}
        $flags=Get-InventoryFlags $p.paths $false
        foreach($key in $flags.Keys){if(-not (Test-ExactBool $p.flags.$key $flags[$key])){throw ('Profile inventory '+($i+1)+' flag '+$key+' contradicts its path records.')}}}
    if(-not $WithWorkspaces){return}
    $workspaces=@($Workspaces)
    if($workspaces.Count -ne 2 -or $workspaces[0].label -cne 'slot_root' -or $workspaces[1].label -cne 'ram_workspace'){throw 'The receipt does not carry the two workspace inventories.'}
    $roots=@((Get-SlotRoot 'slot1'),$script:ramWorkspaceRoot)
    for($k=0;$k -lt 2;$k++){
        $w=$workspaces[$k]
        if($w.root -cne $roots[$k]){throw ('Workspace inventory '+$w.label+' is not the reviewed workspace root.')}
        if(-not (Test-SameStrings @($w.paths|ForEach-Object {$_.path}) $script:workspacePaths)){throw ('Workspace inventory '+$w.label+' differs from the reviewed path list.')}
        # O-F1: the root and EVERY ancestor up to the drive root, each with the full path list.
        $ancestors=@();if((Test-HasProperty $w 'ancestors') -and $null -ne $w.ancestors){$ancestors=@($w.ancestors)}
        if(-not (Test-SameStrings @($ancestors|ForEach-Object {$_.directory}) @(Get-AncestorDirectories $w.root))){
            throw ('Workspace inventory '+$w.label+' does not cover every ancestor directory up to the drive root.')}
        $flags=Get-InventoryFlags $w.paths $true
        foreach($a in $ancestors){
            if(-not (Test-SameStrings @($a.paths|ForEach-Object {$_.path}) $script:workspacePaths)){throw ('Workspace inventory '+$w.label+' ancestor '+$a.directory+' differs from the reviewed path list.')}
            foreach($row in @($a.paths)){if($row.exists -isnot [bool]){throw ('Workspace inventory '+$w.label+' has an untyped ancestor path record.')}}
            $more=Get-InventoryFlags $a.paths $true
            foreach($key in @($more.Keys)){if($more[$key]){$flags[$key]=$true}}}
        foreach($key in @($flags.Keys)){if(-not (Test-ExactBool $w.flags.$key $flags[$key])){throw ('Workspace inventory '+$w.label+' flag '+$key+' contradicts its path records.')}}}
}

function Assert-DeclaredConfig {
    param($Row,[string]$Label)
    # Mirrors inspect_declared_config / inspect_profile_config: key NAMES only; CLEAR only for the bytes the row hashed, parsed
    # as a strict-JSON object without any non-empty customization key.
    if(-not (Test-HasProperty $Row 'declared_config') -or $null -eq $Row.declared_config){throw ($Label+' was not inspected.')}
    $d=$Row.declared_config
    foreach($key in @('status','reason','bytes','sha256','top_level_keys','matching_keys','flagged_keys')){if(-not (Test-HasProperty $d $key)){throw ($Label+' inspection record is incomplete.')}}
    $lists=@{}
    foreach($key in @('top_level_keys','matching_keys','flagged_keys')){
        $items=@($d.$key);if($null -eq $d.$key){$items=@()}
        if($items.Count -and -not (Test-StringList $items '^([A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}|OTHER)$' 64)){throw ($Label+' inspection records something other than key names.')}
        $lists[$key]=$items}
    foreach($k in $lists['matching_keys']){
        $hit=($k -ceq 'OTHER');foreach($f in $script:declaredConfigFragments){if($k.ToLowerInvariant().Contains($f)){$hit=$true}}
        if(-not $hit){throw ($Label+' inspection lists a key that is not a customization key.')}}
    foreach($k in $lists['flagged_keys']){if($k -cnotin $lists['matching_keys']){throw ($Label+' inspection flags a key it did not match.')}}
    if($d.status -ceq 'CLEAR'){
        if($null -ne $d.reason -or $lists['flagged_keys'].Count -or $d.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $d.sha256 -cne $Row.sha256 -or
           -not (Test-ExactInt $d.bytes ([long]$Row.size)) -or $d.bytes -gt 262144){throw ($Label+' CLEAR inspection contradicts its record.')}}
    elseif($d.status -ceq 'FLAGGED'){
        if($d.reason -cnotin $script:declaredConfigReasons -or (($d.reason -ceq 'CUSTOMIZATION_KEYS') -ne ($lists['flagged_keys'].Count -gt 0))){
            throw ($Label+' FLAGGED inspection contradicts its record.')}}
    else{throw ($Label+' inspection status is invalid.')}
}

function Get-FlaggedProfileConfigs {
    param($Profiles)
    # Mirrors flagged_profile_configs: '<slot>:<path>:<customization key names, else the inspection reason or path kind>'.
    foreach($p in @($Profiles)){
        if($null -eq $p -or -not (Test-HasProperty $p 'paths')){continue}
        $rows=@{};foreach($row in @($p.paths)){$rows[$row.path]=$row}
        foreach($relative in $script:declaredConfigPaths){
            $row=$rows[$relative]
            if(-not (Test-InventoryPresent $row)){continue}
            $detail=[string]$row.kind
            if($row.kind -ceq 'file' -and (Test-HasProperty $row 'declared_config') -and $null -ne $row.declared_config){
                $keys=@($row.declared_config.flagged_keys);if($null -eq $row.declared_config.flagged_keys){$keys=@()}
                $detail=$(if($keys.Count){$keys -join ','}else{[string]$row.declared_config.reason})}
            $p.slot+':'+$relative+':'+$detail}}
}

function Test-ProgramDataState {
    param($State,[string]$Label)
    # Mirrors programdata_antigravity_state: returns whether the state is clear; throws on a self-contradicting record.
    if($null -eq $State){throw ($Label+' is missing.')}
    foreach($key in @('path','exists','state','entry_count','entries','acl','clear')){if(-not (Test-HasProperty $State $key)){throw ($Label+' is incomplete.')}}
    $count=$State.entry_count;$entries=@($State.entries);if($null -eq $State.entries){$entries=@()}
    if($State.path -cne $script:programDataAntigravity -or $State.state -cnotin $script:programDataStates -or $State.exists -isnot [bool] -or $State.clear -isnot [bool] -or
       (($count -isnot [int]) -and ($count -isnot [long])) -or $count -lt 0 -or $entries.Count -gt 64 -or $entries.Count -gt $count -or
       ($entries.Count -and -not (Test-StringList $entries '^([A-Za-z0-9][A-Za-z0-9._ -]{0,127}|OTHER)$' 64))){throw ($Label+' is not a valid C:\ProgramData\Antigravity record.')}
    $clear=($State.state -cin @('ABSENT','PROTECTED_EMPTY'))
    switch($State.state){
        'ABSENT'{if($State.exists -or $count -ne 0 -or $null -ne $State.acl){throw ($Label+' contradicts its ABSENT state.')}}
        'PROTECTED_EMPTY'{
            $acl=$State.acl
            if(-not $State.exists -or $count -ne 0 -or $null -eq $acl -or $acl.owner -cne 'S-1-5-18' -or -not (Test-ExactBool $acl.protected $true)){throw ($Label+' is not the protected empty folder.')}
            $rules=@(@($acl.rules)|ForEach-Object {$r=@($_);if($r.Count -ne 3){'INVALID'}else{[string]$r[0]+'|'+[string]$r[1]+'|'+[string]$r[2]}}|Sort-Object -CaseSensitive)
            if(-not (Test-SameStrings $rules @($script:programDataRules|Sort-Object -CaseSensitive))){throw ($Label+' is not the protected empty folder (SYSTEM/BA full, Users read and execute).')}}
        'NOT_EMPTY'{if(-not $State.exists -or $count -lt 1){throw ($Label+' contradicts its NOT_EMPTY state.')}}
        default{if(-not $State.exists){throw ($Label+' contradicts its state.')}}}
    if(-not (Test-ExactBool $State.clear $clear)){throw ($Label+' clear flag contradicts its state.')}
    $clear
}

function Assert-EvidenceProgramData {
    param($Record)
    # O-F2 (G3): read-only before and after the runs; clear only when both are absent or the protected empty folder.
    if($null -eq $Record -or -not (Test-HasProperty $Record 'before') -or -not (Test-HasProperty $Record 'after') -or $Record.path -cne $script:programDataAntigravity){
        throw 'The receipt does not carry the C:\ProgramData\Antigravity inventory.'}
    $before=Test-ProgramDataState $Record.before 'The C:\ProgramData\Antigravity inventory before the runs'
    $after=Test-ProgramDataState $Record.after 'The C:\ProgramData\Antigravity inventory after the runs'
    $clear=($before -and $after)
    if(-not (Test-ExactBool $Record.clear $clear)){throw 'The C:\ProgramData\Antigravity summary contradicts its inventories.'}
    $clear
}

function Assert-StageProgramData {
    param($Record)
    # O-F2 (G4): the folder is the protected empty folder (created now, or already exactly that) before and after the listing.
    if($null -eq $Record -or $Record.path -cne $script:programDataAntigravity -or $Record.sddl -cne $script:programDataSddl -or $Record.created -isnot [bool] -or
       -not (Test-HasProperty $Record 'before') -or -not (Test-HasProperty $Record 'after_listing')){throw 'The stage receipt does not record the protected C:\ProgramData\Antigravity folder.'}
    $null=Test-ProgramDataState $Record.before 'The C:\ProgramData\Antigravity state before the staging'
    if($Record.created -ne ($Record.before.state -ceq 'ABSENT')){throw 'C:\ProgramData\Antigravity was created although it existed, or not created although it was absent.'}
    if($Record.created){
        if(-not (Test-HasProperty $Record 'current')){throw 'The created C:\ProgramData\Antigravity folder was not verified.'}
        $null=Test-ProgramDataState $Record.current 'The created C:\ProgramData\Antigravity folder'
        if($Record.current.state -cne 'PROTECTED_EMPTY'){throw 'The created C:\ProgramData\Antigravity folder is not the protected empty folder.'}}
    elseif($Record.before.state -cne 'PROTECTED_EMPTY'){throw 'An existing C:\ProgramData\Antigravity that is not the protected empty folder was accepted.'}
    $null=Test-ProgramDataState $Record.after_listing 'The C:\ProgramData\Antigravity state after the listing'
    if($Record.state -cne 'PROTECTED_EMPTY' -or $Record.after_listing.state -cne 'PROTECTED_EMPTY' -or -not (Test-ExactBool $Record.clear $true)){
        throw 'C:\ProgramData\Antigravity is not the protected empty folder.'}
}

function Get-IsolationVerdict {
    param($Runs,$RunChecks,$Profiles,$Workspaces,[bool]$ProgramDataClear)
    # Mirrors isolation_verdict; $RunChecks are the wrapper's recomputed checks keyed by run id.
    $executed=@(@($Runs)|Where-Object {$RunChecks.Contains($_.id)})
    $withInit=@($executed|Where-Object {$RunChecks[$_.id].init_present})
    $flags=@(@($Profiles)|ForEach-Object {$_.flags})+@(@($Workspaces)|ForEach-Object {$_.flags})
    $complete=(@($Profiles).Count -eq 6)
    $any={param([string]$Key)foreach($f in $flags){if($f.$Key -eq $true){return $true}};$false}
    $r1Init=@($withInit|Where-Object {$_.id -ceq 'R1'}).Count -eq 1
    $v=[ordered]@{tools_empty=($r1Init -and @($withInit|Where-Object {-not $RunChecks[$_.id].tools_empty}).Count -eq 0);
        no_tool_steps=($executed.Count -gt 0 -and @($executed|Where-Object {-not $RunChecks[$_.id].no_tool_steps}).Count -eq 0);
        no_subagent_steps=($executed.Count -gt 0 -and @($executed|Where-Object {-not $RunChecks[$_.id].no_subagent_steps}).Count -eq 0);
        hooks_absent=($complete -and -not (& $any 'hooks_present'));mcp_absent=($complete -and -not (& $any 'mcp_present'));
        plugins_absent=($complete -and -not (& $any 'plugins_present'));skills_absent=($complete -and -not (& $any 'skills_present'))}
    # O-F1/O-F2: hooks and MCP count as disabled only with the extended inventory clear AND clean Job process accounting.
    $v.process_accounting_clean=($executed.Count -gt 0 -and @($executed|Where-Object {-not $RunChecks[$_.id].job_processes_within_tree}).Count -eq 0)
    $v.programdata_antigravity_clear=$ProgramDataClear
    $clean=($v.process_accounting_clean -and $v.programdata_antigravity_clear)
    $v.disables_tools=($v.tools_empty -and $v.no_tool_steps);$v.disables_mcp=($v.mcp_absent -and $v.plugins_absent -and $clean)
    $v.disables_hooks=($v.hooks_absent -and $v.plugins_absent -and $clean);$v.disables_subagents=($v.no_subagent_steps -and $v.tools_empty)
    $v
}

function Get-IsolationGate {
    param([string]$Status,$Precheck,$Runs,$RunChecks,$Verdict,[string[]]$FlaggedConfigs=@())
    # Mirrors isolation_gate (G3): agents == ['cochem-inference-only'] and R1 meets the contract; any breach in the matrix fails it;
    # with the verdict, the six-profile inventory must show no hooks, MCP, plugins or skills.
    if($Status -cnotin @('EVIDENCE_COMPLETE','EVIDENCE_PRECHECK_REFUSED')){return [pscustomobject]@{passed=$false;reasons=@('EVIDENCE_NOT_COMPLETE')}}
    $reasons=[Collections.Generic.List[string]]::new();foreach($r in @($Precheck.reasons)){if($null -ne $r){$reasons.Add($r)}}
    if($Status -ceq 'EVIDENCE_PRECHECK_REFUSED' -or $reasons.Count){
        if($reasons.Count -eq 0){$reasons.Add('EVIDENCE_NOT_COMPLETE')}
        return [pscustomobject]@{passed=$false;reasons=@($reasons)}}
    if(-not $RunChecks.Contains('R1')){$reasons.Add('R1_NOT_RUN')}
    else{foreach($name in $script:runCheckReasons.Keys){if(-not $RunChecks['R1'][$name]){$reasons.Add($script:runCheckReasons[$name])}}}
    foreach($run in @($Runs)){if($run.id -cne 'R1' -and $RunChecks.Contains($run.id) -and $RunChecks[$run.id].isolation_breach){$reasons.Add('ISOLATION_BREACH_IN_MATRIX');break}}
    foreach($run in @($Runs)){if($RunChecks.Contains($run.id) -and -not $RunChecks[$run.id].job_processes_within_tree){$reasons.Add('JOB_PROCESSES_BEYOND_AGY_TREE');break}}
    foreach($run in @($Runs)){
        if($RunChecks.Contains($run.id) -and $RunChecks[$run.id].accepted -and (Test-HasProperty $run 'log_scan') -and $null -ne $run.log_scan -and $run.log_scan.fallback_found -eq $true){
            $reasons.Add('MODEL_FALLBACK_LOGGED');break}}
    foreach($run in @($Runs)){
        if($RunChecks.Contains($run.id) -and $RunChecks[$run.id].accepted -and (Test-HasProperty $run 'log_scan') -and $null -ne $run.log_scan -and
           (Test-HasProperty $run.log_scan 'incomplete') -and $run.log_scan.incomplete -eq $true){$reasons.Add('MODEL_LOG_SCAN_INCOMPLETE');break}}
    if($null -ne $Verdict){foreach($key in @('hooks_absent','mcp_absent','plugins_absent','skills_absent')){if(-not (Test-ExactBool $Verdict[$key] $true)){$reasons.Add('PROFILE_INVENTORY_NOT_CLEAR');break}}}
    if($null -ne $Verdict){foreach($item in @($FlaggedConfigs)){if($null -ne $item){$reasons.Add('PROFILE_CONFIG_FLAGGED:'+$item)}}}
    if($null -ne $Verdict -and -not (Test-ExactBool $Verdict['programdata_antigravity_clear'] $true)){$reasons.Add('PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR')}
    [pscustomobject]@{passed=($reasons.Count -eq 0);reasons=@($reasons)}
}

function Get-IdentityExpectation {
    param($Runs,$RunChecks)
    # Mirrors the boolean fields of identity_verdict from the recomputed checks.
    $c={param([string]$Id)if($RunChecks.Contains($Id)){$RunChecks[$Id]}else{$null}}
    $r1=& $c 'R1';$r2=& $c 'R2';$r3=& $c 'R3';$r4=& $c 'R4';$r5=& $c 'R5'
    $clean=($null -ne $r1)
    $acceptedCount=0
    foreach($run in @($Runs)){
        if(-not $RunChecks.Contains($run.id) -or -not $RunChecks[$run.id].accepted){continue}
        $acceptedCount++
        $markers=@($script:stderrMarkers|Where-Object {$run.classification.stderr_markers.$_ -eq $true})
        if($markers.Count -or @($run.classification.stream.reroute_keys).Count){$clean=$false}
        if((Test-HasProperty $run 'log_scan') -and $null -ne $run.log_scan){
            if($run.log_scan.fallback_found -eq $true -or ((Test-HasProperty $run.log_scan 'incomplete') -and $run.log_scan.incomplete -eq $true)){$clean=$false}}}
    [ordered]@{slug_form_accepted=($null -ne $r1 -and $r1.accepted -and $r1.model_matches);slug_form_passes_contract=($null -ne $r1 -and $r1.passes_contract);
        slug_with_effort_accepted=($null -ne $r2 -and $r2.accepted);slug_with_effort_passes_contract=($null -ne $r2 -and $r2.passes_contract);
        family_with_effort_accepted=($null -ne $r3 -and $r3.accepted);family_with_effort_passes_with_echo=($null -ne $r3 -and $r3.passes_with_echo);
        unknown_model_rejected=($null -ne $r4 -and -not $r4.accepted);reroute_scan_clean=($clean -and $acceptedCount -gt 0);
        effort_null_executed=($null -ne $r5);effort_null_passed=($null -ne $r5 -and $r5.passes_contract)}
}

function Assert-IsolationFailureMetadata {
    param($Value)
    if($null -eq $Value.PSObject.Properties['failure']){return $null}
    $f=$Value.failure
    if($f.phase -cnotin $script:failurePhases -or $f.error_type -cnotmatch '^[A-Za-z][A-Za-z0-9_]{0,79}$' -or
       ($null -ne $f.winerror -and (($f.winerror -isnot [int] -and $f.winerror -isnot [long]) -or $f.winerror -lt 0 -or $f.winerror -gt 4294967295))){throw 'Invalid sanitized isolation failure metadata.'}
    [ordered]@{phase=$f.phase;error_type=$f.error_type;winerror=$f.winerror}
}

function Assert-StagedAgentRecords {
    param($Staged,[string]$Identity,[string]$Label,[bool]$Parents)
    $rows=@($Staged);if($null -eq $Staged){$rows=@()}
    $destinations=@(Get-AgentDestinations $Identity)
    if($rows.Count -ne 2){throw ($Label+': the agent is not staged at both discovery locations.')}
    $sids=@()
    for($i=0;$i -lt 2;$i++){
        $row=$rows[$i]
        $file=[regex]::Match([string]$row.file_acl_sddl,$script:fileSddlPattern);$directory=[regex]::Match([string]$row.directory_acl_sddl,$script:directorySddlPattern)
        if($row.relative -cne $script:agentRelatives[$i] -or $row.path -cne $destinations[$i] -or $row.sha256 -cne $script:agentPin -or
           -not (Test-ExactInt $row.bytes $script:agentBytes) -or -not (Test-ExactBool $row.acl_verified $true) -or $row.preexisting -isnot [bool] -or
           -not $file.Success){throw ($Label+': the staged agent evidence differs from the reviewed definition.')}
        if(-not $directory.Success){throw ($Label+': the staged agent directory ACL differs from SYSTEM/BA full with worker read-only.')}
        $sids+=$file.Groups[1].Value;$sids+=$directory.Groups[1].Value
        if($Parents){
            # O-F3: the parent folder is protected too (worker list and traverse only: no add, no delete-child).
            $parentPath=(Get-WorkerProfileRoot $Identity)+'\'+$script:agentParentRelatives[$i].Replace('/','\')
            foreach($key in @('parent_relative','parent_path','parent_acl_sddl','parent_acl_verified','parent_acl_applied')){
                if(-not (Test-HasProperty $row $key)){throw ($Label+': the parent folder '+$script:agentParentRelatives[$i]+' is not recorded as protected.')}}
            $parent=[regex]::Match([string]$row.parent_acl_sddl,$script:directorySddlPattern)
            if($row.parent_relative -cne $script:agentParentRelatives[$i] -or $row.parent_path -cne $parentPath -or -not (Test-ExactBool $row.parent_acl_verified $true) -or
               $row.parent_acl_applied -isnot [bool] -or -not $parent.Success){
                throw ($Label+': the parent folder '+$script:agentParentRelatives[$i]+' ACL differs from SYSTEM/BA full with worker list and traverse only.')}
            $sids+=$parent.Groups[1].Value}}
    if(@($sids|Sort-Object -Unique).Count -ne 1){throw ($Label+': the staged agent ACLs name more than one worker SID.')}
}

function Assert-ReceiptIdentity {
    param($Value,$Pins,[string]$Nonce,[string]$Schema)
    if($Value.schema -cne $Schema -or $Value.mode -cne $script:Mode -or $Value.attempt -cne $script:Attempt -or $Value.nonce -cne $Nonce -or
       $Value.system_sid -cne 'S-1-5-18' -or $Value.helper_sha256 -cne $script:helperPin -or $Value.runtime_root -cne $script:r4Root -or
       $Value.install_receipt_sha256 -cne $Pins.install_receipt_sha256 -or $Value.source_manifest_sha256 -cne $Pins.source_manifest_sha256 -or
       $Value.resource_limits_sha256 -cne $script:resourcePin -or $Value.windows_runtime_sha256 -cne $script:windowsPin -or $Value.native_executable -cne $script:nativeExecutable -or
       $Value.gemini_gate -cne $script:geminiGate){
        throw 'The isolation receipt identity/runtime binding differs.'}
}

function Assert-ReceiptCustody {
    param($Value,$Task,$Pins)
    if($Task.LastTaskResult -ne 0 -or $Value.config_sha256 -cne $Pins.configuration_sha256 -or $Value.layout_sha256 -cne $Pins.layout_sha256 -or
       -not (Test-ExactBool $Value.revision.verified $true) -or $Value.revision.source_sha256 -cne $Pins.revision_sha256 -or
       $Value.native_executable_sha256_before -cne $script:agyPin -or $Value.native_executable_sha256_after -cne $script:agyPin -or $Value.native_version_at_pin -cne $script:agyVersion){
        throw 'The isolation receipt configuration/result binding differs.'}
    foreach($key in @('cleanup_verified','runtime_custody_verified','require_stopped_before','require_stopped_after','daemon_states_verified_before_and_after','production_arguments_validated')){
        if(-not (Test-ExactBool $Value.$key $true)){throw ('The isolation receipt lacks verified '+$key+'.')}}
    foreach($key in @('token_files_opened','login_inputs_written')){if(-not (Test-ExactInt $Value.$key 0)){throw ('Out-of-scope execution was reported: '+$key+'.')}}
    foreach($key in @('owner_credentials_read','raw_output_published','pipeline_started')){if(-not (Test-ExactBool $Value.$key $false)){throw ('Out-of-scope action was reported: '+$key+'.')}}
    if($Value.raw_output_publication -cne 'never'){throw 'The raw output publication rule differs.'}
}

function Assert-IsolationReceipt {
    param($Value,$Task,$Pins,[string]$Nonce,[string]$Root)
    Assert-ReceiptIdentity $Value $Pins $Nonce 'cochem-agy-isolation-evidence/1'
    if($Value.slot -cne $script:Slot -or $Value.effort_null_slug -cne $script:effortNullSlug -or $Value.primary_model -cne $script:primaryModel){
        throw 'The isolation receipt identity/runtime binding differs.'}
    $failure=Assert-IsolationFailureMetadata $Value
    $jobs=$Value.model_jobs_executed
    if((($jobs -isnot [int]) -and ($jobs -isnot [long])) -or $jobs -lt 0 -or $jobs -gt $script:maxModelJobs){throw 'The model job count is invalid.'}
    $expectedRuns=@(Get-ExpectedRuns)
    $planned=@($Value.runs_planned)
    if($planned.Count -ne $expectedRuns.Count){throw 'The planned run matrix differs.'}
    for($i=0;$i -lt $planned.Count;$i++){
        if($planned[$i].id -cne $expectedRuns[$i].id -or $planned[$i].requested_model -cne $expectedRuns[$i].model -or -not (Test-SameStrings $planned[$i].extra_arguments $expectedRuns[$i].extra)){
            throw 'The planned run matrix differs.'}}
    if($Value.status -cin @('EVIDENCE_FAILED','EVIDENCE_INCOMPLETE')){
        return [pscustomobject]@{decision=$(if($Value.status -ceq 'EVIDENCE_FAILED'){'FAILED'}else{'INCOMPLETE'});failure=$failure;
            gate=(Get-IsolationGate $Value.status $null @() @{});isolation_verdict=$null;run_checks=@{};identity=$null;programdata_clear=$null;deadline_skipped=@()}}
    if($Value.status -cnotin @('EVIDENCE_COMPLETE','EVIDENCE_PRECHECK_REFUSED') -or $null -ne $failure){throw 'The isolation receipt status is not a known terminal status.'}
    Assert-ReceiptCustody $Value $Task $Pins
    if($Value.worker_identity -cne $script:workerIdentity -or $Value.profile_root -cne (Get-WorkerProfileRoot $script:workerIdentity) -or $Value.slot_root -cne (Get-SlotRoot 'slot1') -or
       -not (Test-SameStrings $Value.production_argument_template $script:productionArguments) -or $Value.prompt_line_sha256 -cne $script:promptLineSha256){
        throw 'The isolation receipt worker/transport binding differs.'}
    $agent=$Value.agent
    if($agent.name -cne $script:agentName -or $agent.source_sha256 -cne $script:agentPin -or -not (Test-ExactBool $agent.verified_before_each_launch $true)){
        throw 'The staged agent evidence differs from the reviewed definition.'}
    Assert-StagedAgentRecords $agent.staged $script:workerIdentity 'slot1' $false
    if(-not (Test-HasProperty $Value 'job_expected_processes_maximum') -or -not (Test-ExactInt $Value.job_expected_processes_maximum $script:jobProcessMaximum) -or
       $Value.ram_workspace_root -cne $script:ramWorkspaceRoot){throw 'The isolation receipt worker/transport binding differs.'}
    $shadows=@($agent.shadows_found);if($null -eq $agent.shadows_found){$shadows=@()}
    $expectedPre=@(Get-ExpectedPrecheck);$probes=@($Value.precheck.probes)
    if($probes.Count -ne $expectedPre.Count){throw 'The isolation receipt does not carry exactly the planned pre-check probes.'}
    $sensitive=[Collections.Generic.List[string]]::new()
    for($i=0;$i -lt $expectedPre.Count;$i++){Assert-PrecheckRecord $probes[$i] $expectedPre[$i] $Root $expectedPre[$i].id
        foreach($stream in @('stdout','stderr')){foreach($n in @($probes[$i].$stream.sensitive_patterns)){if($null -ne $n){$sensitive.Add($n)}}}}
    $decision=Get-PrecheckDecision $probes $shadows
    if(-not (Test-ExactBool $Value.precheck.passed $decision.passed) -or (@($Value.precheck.reasons) -join ',') -cne (@($decision.reasons) -join ',')){
        throw 'The pre-check decision contradicts the retained probes.'}
    if(($Value.status -ceq 'EVIDENCE_PRECHECK_REFUSED') -ne (-not $decision.passed)){throw 'The isolation status contradicts the pre-check decision.'}
    $runs=@($Value.runs);if($null -eq $Value.runs){$runs=@()}
    $skipped=@($Value.runs_skipped);if($null -eq $Value.runs_skipped){$skipped=@()}
    if($runs.Count + $skipped.Count -ne $expectedRuns.Count){throw 'The executed and skipped runs do not cover the planned matrix.'}
    $checks=[ordered]@{}
    for($i=0;$i -lt $runs.Count;$i++){$checks[$runs[$i].id]=Assert-RunRecord $runs[$i] $expectedRuns[$i] $Root
        foreach($stream in @('stdout','stderr')){foreach($n in @($runs[$i].$stream.sensitive_patterns)){if($null -ne $n){$sensitive.Add($n)}}}}
    $lastBreach=($runs.Count -gt 0 -and $checks[$runs[$runs.Count-1].id].isolation_breach)
    for($i=0;$i -lt $skipped.Count;$i++){
        $expectedId=$expectedRuns[$runs.Count+$i].id
        $reason=if(-not $decision.passed){'PRECHECK_REFUSED'}elseif($lastBreach){'ISOLATION_BREACH_STOP'}else{'DEADLINE'}
        if($skipped[$i].id -cne $expectedId -or $skipped[$i].reason -cne $reason){throw 'The skipped runs contradict the pre-check, isolation stop and deadline rules.'}}
    if(-not $decision.passed -and $runs.Count -ne 0){throw 'A model job ran although the pre-check refused.'}
    # O-F4: a complete receipt may skip runs only after an isolation breach, or by the deadline guard after a passing R1.
    if($decision.passed -and $skipped.Count -and -not $lastBreach -and -not ($checks.Contains('R1') -and $checks['R1'].passes_contract)){
        throw 'Runs were skipped without an isolation breach or a passing R1 before the deadline.'}
    $delivered=@($runs|Where-Object {$_.prompt_delivered -eq $true}).Count;$answers=@($runs|Where-Object {$checks[$_.id].result_success}).Count
    if(-not (Test-ExactInt $Value.model_jobs_executed $delivered) -or -not (Test-ExactInt $Value.answers_produced $answers)){throw 'The model job or answer count contradicts the runs.'}
    $found=@($sensitive|Sort-Object -Unique -CaseSensitive)
    if((@($Value.raw_sensitive_patterns_found|Sort-Object -CaseSensitive) -join ',') -cne ($found -join ',')){throw 'The raw sensitive-pattern summary contradicts the raw records.'}
    $replay=$Value.replay_streams
    $replayIds=@($runs|Where-Object {(Test-HasProperty $_ 'replay')}|ForEach-Object {$_.id})
    if(-not (Test-SameStrings @($replay.PSObject.Properties|ForEach-Object {$_.Name}|Sort-Object -CaseSensitive) @($replayIds|Sort-Object -CaseSensitive))){throw 'The replay map contradicts the runs.'}
    foreach($run in $runs){
        $entry=$replay.($run.id)
        if(-not (Test-ExactBool $entry.available $run.replay.available) -or $entry.requested_model -cne $run.requested_model -or
           -not (Test-SameStrings $entry.extra_arguments @($run.extra_arguments)) -or $entry.outcome -cne $run.outcome){throw ('The replay map entry for '+$run.id+' contradicts its run.')}
        if($run.replay.available -eq $true){foreach($stream in @('stdout','stderr')){
            if($entry.$stream.path -cne $run.replay.$stream.path -or $entry.$stream.sha256 -cne $run.replay.$stream.sha256){throw ('The replay map entry for '+$run.id+' contradicts its run.')}}}}
    Assert-InventoryRecords $Value.profiles $Value.workspaces $true
    $programDataClear=Assert-EvidenceProgramData $Value.programdata_antigravity
    $attestation=$Value.environment_attestation
    if($null -eq $attestation){throw 'The environment attestation is missing.'}
    if(((-not (Test-StringList @($attestation.flagged_names) '^[A-Z0-9_]{1,128}$' 64)) -and @($attestation.flagged_names).Count -ne 0) -or
       -not (Test-ExactBool $attestation.flagged_names_absent (@($attestation.flagged_names).Count -eq 0)) -or $attestation.profile_binding_verified -isnot [bool] -or
       -not (Test-ExactBool $attestation.values_recorded $false)){throw 'The environment attestation is not a names-only record.'}
    foreach($name in @($attestation.flagged_names)){if($name -cnotmatch '^(AGY_|ANTIGRAVITY_|XDG_|GEMINI_|GOOGLE_|CLOUDSDK_|GCLOUD_|CODEX_HOME$|CLAUDE_CONFIG_DIR$)'){throw 'The environment attestation lists a name outside its filter.'}}
    $verdict=Get-IsolationVerdict $runs $checks $Value.profiles $Value.workspaces $programDataClear
    foreach($key in $verdict.Keys){if(-not (Test-ExactBool $Value.isolation_verdict.$key $verdict[$key])){throw ('The isolation verdict '+$key+' contradicts the retained evidence.')}}
    $flaggedConfigs=@(Get-FlaggedProfileConfigs $Value.profiles)
    if(-not (Test-HasProperty $Value.isolation_verdict 'profile_configs_flagged') -or -not (Test-SameStrings $Value.isolation_verdict.profile_configs_flagged $flaggedConfigs)){
        throw 'The isolation verdict profile_configs_flagged contradicts the retained evidence.'}
    if($Value.isolation_verdict.model_fallback_basis -cne 'UNKNOWN'){throw 'The model fallback basis must stay UNKNOWN.'}
    $identity=$Value.identity_verdict
    $expectIdentity=Get-IdentityExpectation $runs $checks
    foreach($key in @('slug_form_accepted','slug_form_passes_contract','slug_with_effort_accepted','slug_with_effort_passes_contract','family_with_effort_accepted',
        'family_with_effort_passes_with_echo','unknown_model_rejected','reroute_scan_clean')){
        if(-not (Test-ExactBool $identity.$key $expectIdentity[$key])){throw ('The identity verdict '+$key+' contradicts the retained runs.')}}
    $effortNull=$identity.effort_null
    if($effortNull.slug -cne $script:effortNullSlug -or $effortNull.run_id -cne 'R5' -or -not (Test-ExactBool $effortNull.executed $expectIdentity.effort_null_executed) -or
       -not (Test-ExactBool $effortNull.passed $expectIdentity.effort_null_passed)){throw 'The identity verdict effort_null contradicts the retained runs.'}
    foreach($run in $runs){
        $row=$identity.runs.($run.id)
        if(-not (Test-ExactBool $row.executed $true) -or -not (Test-ExactBool $row.accepted $checks[$run.id].accepted) -or
           -not (Test-ExactBool $row.passes_contract $checks[$run.id].passes_contract) -or -not (Test-ExactBool $row.passes_with_echo $checks[$run.id].passes_with_echo) -or
           $(if($null -eq $run.classification.stream.init){$null -ne $row.init_model}else{$row.init_model -cne $run.classification.stream.init.model})){throw ('The identity verdict for '+$run.id+' contradicts its run.')}
        if(-not (Test-HasProperty $row 'log_fallback_found') -or -not (Test-ExactBool $row.log_fallback_found ($run.log_scan.fallback_found -eq $true)) -or
           -not (Test-HasProperty $row 'log_scanned') -or -not (Test-ExactBool $row.log_scanned ($run.log_scan.log_scanned -eq $true))){
            throw ('The identity verdict log scan for '+$run.id+' contradicts its run.')}}
    foreach($item in $skipped){
        # O-F4: a skipped run is executed false and passed false, with its skip reason.
        $row=$identity.runs.($item.id)
        foreach($key in @('executed','accepted','passes_contract','passes_with_echo','skipped_reason')){if(-not (Test-HasProperty $row $key)){throw ('The identity verdict for the skipped run '+$item.id+' is incomplete.')}}
        if(-not (Test-ExactBool $row.executed $false) -or -not (Test-ExactBool $row.accepted $false) -or -not (Test-ExactBool $row.passes_contract $false) -or
           -not (Test-ExactBool $row.passes_with_echo $false) -or $row.skipped_reason -cne $item.reason){throw ('The identity verdict for the skipped run '+$item.id+' must be executed false and passed false.')}}
    $gate=Get-IsolationGate $Value.status $Value.precheck $runs $checks $verdict $flaggedConfigs
    if(-not (Test-ExactBool $Value.gate.passed $gate.passed) -or (@($Value.gate.reasons) -join ',') -cne (@($gate.reasons) -join ',')){throw 'The isolation gate contradicts the retained evidence.'}
    [pscustomobject]@{decision=$(if($decision.passed){'COMPLETE'}else{'PRECHECK_REFUSED'});failure=$null;gate=$gate;isolation_verdict=$verdict;run_checks=$checks;identity=$expectIdentity;
        programdata_clear=$programDataClear;deadline_skipped=@($skipped|Where-Object {$_.reason -ceq 'DEADLINE'}|ForEach-Object {$_.id})}
}

function Get-StagingGate {
    param([string]$Status,$Slots,$SlotReasons)
    # Mirrors staging_gate (G4): every slot holds the pinned agent at both locations and lists exactly it.
    if($Status -cne 'STAGING_COMPLETE'){return [pscustomobject]@{passed=$false;reasons=@('STAGING_NOT_COMPLETE')}}
    $reasons=[Collections.Generic.List[string]]::new()
    foreach($slot in $script:stageSlots){
        if(-not $SlotReasons.Contains($slot)){$reasons.Add($slot+':SLOT_NOT_PROCESSED');continue}
        foreach($r in @($SlotReasons[$slot])){if($null -ne $r){$reasons.Add($slot+':'+$r)}}}
    [pscustomobject]@{passed=($reasons.Count -eq 0);reasons=@($reasons)}
}

function Assert-StageReceipt {
    param($Value,$Task,$Pins,[string]$Nonce,[string]$Root)
    Assert-ReceiptIdentity $Value $Pins $Nonce 'cochem-agy-agent-staging/1'
    $failure=Assert-IsolationFailureMetadata $Value
    if(-not (Test-ExactInt $Value.model_jobs_executed 0) -or -not (Test-ExactInt $Value.answers_produced 0)){throw 'Out-of-scope execution was reported: model jobs during staging.'}
    if(-not (Test-SameStrings $Value.slots_planned $script:stageSlots)){throw 'The planned staging slots differ.'}
    if($Value.status -cin @('STAGING_FAILED','STAGING_INCOMPLETE')){
        return [pscustomobject]@{decision=$(if($Value.status -ceq 'STAGING_FAILED'){'FAILED'}else{'INCOMPLETE'});failure=$failure;
            gate=(Get-StagingGate $Value.status @() @{});slot_reasons=@{}}}
    if($Value.status -cne 'STAGING_COMPLETE' -or $null -ne $failure){throw 'The staging receipt status is not a known terminal status.'}
    Assert-ReceiptCustody $Value $Task $Pins
    $agent=$Value.agent
    if($agent.name -cne $script:agentName -or $agent.source_sha256 -cne $script:agentPin -or -not (Test-ExactInt $agent.bytes $script:agentBytes) -or
       -not (Test-SameStrings $agent.destinations $script:agentRelatives)){throw 'The staged agent evidence differs from the reviewed definition.'}
    if(-not (Test-HasProperty $agent 'parent_destinations') -or -not (Test-SameStrings $agent.parent_destinations $script:agentParentRelatives) -or
       -not (Test-HasProperty $agent 'parent_acl_sddl_template') -or $agent.parent_acl_sddl_template -cne $script:parentSddlTemplate){
        throw 'The staged agent parent protection differs from the reviewed definition.'}
    Assert-StageProgramData $Value.programdata_antigravity
    $slots=@($Value.slots);if($null -eq $Value.slots){$slots=@()}
    if($slots.Count -ne 6 -or @(@($Value.slots_skipped)|Where-Object {$null -ne $_}).Count -ne 0){throw 'A complete staging receipt must cover all six slots.'}
    $expectedProbes=@(Get-ExpectedStageProbes)
    $slotReasons=[ordered]@{};$sensitive=[Collections.Generic.List[string]]::new()
    for($i=0;$i -lt 6;$i++){
        $entry=$slots[$i];$slot=$script:stageSlots[$i];$identity=$script:workerIdentities[$i]
        if($entry.slot -cne $slot -or $entry.identity -cne $identity -or $entry.profile_root -cne (Get-WorkerProfileRoot $identity) -or $entry.slot_root -cne (Get-SlotRoot $slot)){
            throw ('Staging entry '+$slot+' differs from the reviewed six-identity layout.')}
        Assert-StagedAgentRecords $entry.staged $identity $slot $true
        $probes=@($entry.probes)
        if($probes.Count -ne $expectedProbes.Count){throw ('Staging entry '+$slot+' does not carry exactly the two listing probes.')}
        for($j=0;$j -lt $probes.Count;$j++){Assert-PrecheckRecord $probes[$j] $expectedProbes[$j] $Root ($slot+'-'+$expectedProbes[$j].id)
            foreach($stream in @('stdout','stderr')){foreach($n in @($probes[$j].$stream.sensitive_patterns)){if($null -ne $n){$sensitive.Add($n)}}}}
        $reasons=[Collections.Generic.List[string]]::new()
        if(-not (Test-SameStrings $entry.agent_sha256_after_listing @($script:agentPin,$script:agentPin))){$reasons.Add('AGENT_NOT_STAGED_AT_BOTH_LOCATIONS')}
        if(@($entry.shadows_found).Count -gt 0 -and $null -ne $entry.shadows_found){$reasons.Add('AGENT_SHADOW_FOUND')}
        $listing=@(Get-ListingReasons $probes)
        foreach($r in $listing){$reasons.Add($r)}
        if(-not (Test-ExactBool $entry.listing.passed ($listing.Count -eq 0)) -or (@($entry.listing.reasons) -join ',') -cne ($listing -join ',')){
            throw ('Staging entry '+$slot+' listing decision contradicts its probes.')}
        $slotReasons[$slot]=@($reasons)}
    $found=@($sensitive|Sort-Object -Unique -CaseSensitive)
    if((@($Value.raw_sensitive_patterns_found|Sort-Object -CaseSensitive) -join ',') -cne ($found -join ',')){throw 'The raw sensitive-pattern summary contradicts the raw records.'}
    Assert-InventoryRecords $Value.profiles $null $false
    $clear=$true;foreach($p in @($Value.profiles)){foreach($key in @('hooks_present','mcp_present','plugins_present','skills_present')){if($p.flags.$key -ne $false){$clear=$false}}}
    if(-not (Test-ExactBool $Value.isolation_inventory_clear $clear)){throw 'The staging inventory summary contradicts the six profile inventories.'}
    $gate=Get-StagingGate $Value.status $slots $slotReasons
    if(-not (Test-ExactBool $Value.gate.passed $gate.passed) -or (@($Value.gate.reasons) -join ',') -cne (@($gate.reasons) -join ',')){throw 'The staging gate contradicts the retained evidence.'}
    [pscustomobject]@{decision='COMPLETE';failure=$null;gate=$gate;slot_reasons=$slotReasons}
}

function New-IsolationSummary {
    param($Receipt,$Verified,$Task,[string]$Nonce,[string]$ReceiptSha256)
    $root=$script:targetRoot;$gate=$Verified.gate;$receiptPath=Join-Path $root $script:receiptName
    $passed=((Test-ExactBool $gate.passed $true) -and $Verified.decision -ceq 'COMPLETE')
    $runs=@()
    foreach($run in @($Receipt.runs)){
        if($null -eq $run.PSObject.Properties['classification'] -or $null -eq $run.PSObject.Properties['outcome']){$runs+=[ordered]@{id=$run.id;incomplete=$true};continue}
        $s=$run.classification.stream
        $runs+=[ordered]@{id=$run.id;requested_model=$run.requested_model;extra_arguments=@($run.extra_arguments);outcome=$run.outcome;exit_code=$run.exit_code;elapsed_ms=$run.elapsed_ms;
            prompt_delivered=$run.prompt_delivered;init_model=$(if($null -ne $s.init){$s.init.model}else{$null});init_agent=$(if($null -ne $s.init){$s.init.agent}else{$null});
            init_tools_count=$(if($null -ne $s.init){$s.init.tools_count}else{$null});result_status=$(if($null -ne $s.result){$s.result.status}else{$null});
            num_turns=$(if($null -ne $s.result){$s.result.num_turns}else{$null});response_matches_expected=$(if($null -ne $s.result){$s.result.response_matches_expected}else{$null});
            error_templates=@($run.classification.error_templates);stderr_bytes=$run.stderr.bytes;stdout_bytes=$run.stdout.bytes;
            accepted=$(if($Verified.run_checks.Contains($run.id)){$Verified.run_checks[$run.id].accepted}else{$null});
            passes_contract=$(if($Verified.run_checks.Contains($run.id)){$Verified.run_checks[$run.id].passes_contract}else{$null});
            job_total_processes=$(if((Test-HasProperty $run 'job_accounting') -and $null -ne $run.job_accounting){$run.job_accounting.total_processes}else{$null});
            job_processes_within_tree=$(if($Verified.run_checks.Contains($run.id)){$Verified.run_checks[$run.id].job_processes_within_tree}else{$null});
            log_scanned=$(if((Test-HasProperty $run 'log_scan') -and $null -ne $run.log_scan){$run.log_scan.log_scanned}else{$null});
            log_fallback_found=$(if((Test-HasProperty $run 'log_scan') -and $null -ne $run.log_scan){$run.log_scan.fallback_found}else{$null})}}
    $deadlineSkipped=@($Verified.deadline_skipped)
    $isolationStop=@(@($gate.reasons)|Where-Object {$_ -cin $script:isolationReasons}).Count -gt 0
    $iv=$Receipt.identity_verdict
    $effortNull=$(if($null -ne $iv){[ordered]@{slug=$iv.effort_null.slug;run_id='R5';executed=$iv.effort_null.executed;passed=$iv.effort_null.passed;init_model=$iv.effort_null.init_model}}else{$null})
    if($Verified.decision -cin @('FAILED','INCOMPLETE')){$message='GEMINI-HELD (G3): the isolation evidence did not complete ('+$Receipt.status+$(if($null -ne $Verified.failure){', phase '+$Verified.failure.phase+', '+$Verified.failure.error_type}else{''})+'); evidence in '+$root+'. The sitting continues in Gemini-held mode (A4); nothing is retried.'}
    elseif($Verified.decision -ceq 'PRECHECK_REFUSED'){$message='GEMINI-HELD (G3): no model job ran ('+(@($gate.reasons) -join ', ')+'); evidence in '+$root+'. The sitting continues in Gemini-held mode (A4).'}
    elseif($isolationStop){$message='GEMINI-HELD (G3, Decision 4): the inference-only agent is not tool-free ('+(@($gate.reasons) -join ', ')+'); evidence in '+$root+'. The sitting continues in Gemini-held mode (A4); Decision 4 goes to the owner.'}
    elseif(-not $passed){$message='GEMINI-HELD (G3): the 3B identity / isolation gate failed ('+(@($gate.reasons) -join ', ')+'); evidence in '+$root+'. The sitting continues in Gemini-held mode (A4).'}
    else{$message='Isolation evidence verified (G3 passed): agents == [cochem-inference-only]; R1 init.tools [], agent cochem-inference-only, init.model '+$script:primaryModel+', SUCCESS in one turn, no tool/subagent steps or reroute markers, no process beyond agy''s own tree; effort-null slug '+$script:effortNullSlug+$(if($null -ne $effortNull -and $effortNull.passed -eq $true){' passed (R5)'}else{' did not pass (the builder binds '+$script:primaryModel+')'})+$(if($deadlineSkipped.Count){'; skipped by the deadline guard after R1 passed (left unbound): '+($deadlineSkipped -join ', ')}else{''})+'; '+$Receipt.model_jobs_executed+' model jobs, '+$Receipt.answers_produced+' answers. Receipt '+$receiptPath+' (sha256 '+$ReceiptSha256+') is the inference_only.capability_reference.'}
    $profiles=@(@($Receipt.profiles)|ForEach-Object {[ordered]@{slot=$_.slot;profile_present=$_.profile_present;flags=$_.flags}})
    $pd=$(if((Test-HasProperty $Receipt 'programdata_antigravity') -and $null -ne $Receipt.programdata_antigravity){$Receipt.programdata_antigravity}else{$null})
    $programData=[ordered]@{path=$script:programDataAntigravity;clear=$Verified.programdata_clear;
        before=$(if($null -ne $pd -and (Test-HasProperty $pd 'before') -and $null -ne $pd.before){$pd.before.state}else{$null});
        after=$(if($null -ne $pd -and (Test-HasProperty $pd 'after') -and $null -ne $pd.after){$pd.after.state}else{$null})}
    [ordered]@{schema='cochem-agy-isolation-evidence-result/1';mode='evidence';status=$Receipt.status;decision=$Verified.decision;attempt=$script:Attempt;slot=$script:Slot;nonce=$Nonce;
        target_root=$root;receipt_path=$receiptPath;receipt_sha256=$ReceiptSha256;gemini_gate='G3';gemini_outcome=$(if($passed){'PASSED'}else{'HELD'});exit_code=$(if($passed){0}else{10});
        capability_reference=$(if($passed){$receiptPath+'#'+$ReceiptSha256}else{$null});
        capability_reference_candidate=$(if($passed){[ordered]@{path=$receiptPath;sha256=$ReceiptSha256}}else{$null});
        task_name=$script:taskName;last_task_result=$Task.LastTaskResult;task_preserved=$true;
        gate=[ordered]@{passed=$gate.passed;reasons=@($gate.reasons)};isolation_stop=$isolationStop;failure=$Verified.failure;
        precheck=[ordered]@{passed=$Receipt.precheck.passed;reasons=@($Receipt.precheck.reasons)};
        agent=[ordered]@{name=$script:agentName;sha256=$script:agentPin;staged=@(@($Receipt.agent.staged)|ForEach-Object {$_.path});shadows_found=@($Receipt.agent.shadows_found)};
        effort_null=$effortNull;runs=$runs;runs_skipped=@($Receipt.runs_skipped);deadline_skipped_runs=$deadlineSkipped;
        programdata_antigravity=$programData;job_expected_processes_maximum=$script:jobProcessMaximum;isolation_verdict=$Receipt.isolation_verdict;
        identity=$(if($null -ne $iv){[ordered]@{slug_form_accepted=$iv.slug_form_accepted;slug_form_passes_contract=$iv.slug_form_passes_contract;
            slug_with_effort_accepted=$iv.slug_with_effort_accepted;slug_with_effort_passes_contract=$iv.slug_with_effort_passes_contract;
            slug_with_effort_init_model=$iv.slug_with_effort_init_model;family_with_effort_accepted=$iv.family_with_effort_accepted;
            family_with_effort_passes_with_echo=$iv.family_with_effort_passes_with_echo;family_with_effort_init_model=$iv.family_with_effort_init_model;
            unknown_model_rejected=$iv.unknown_model_rejected;unknown_model_exit_code=$iv.unknown_model_exit_code;
            unknown_model_error_templates=@($iv.unknown_model_error_templates);reroute_scan_clean=$iv.reroute_scan_clean}}else{$null});
        replay_root=(Join-Path $root 'replay');replay_streams=$Receipt.replay_streams;
        environment_flagged_names=@(if($null -ne $Receipt.environment_attestation){$Receipt.environment_attestation.flagged_names});
        profiles=$profiles;model_jobs_executed=$Receipt.model_jobs_executed;answers_produced=$Receipt.answers_produced;
        raw_output_location=(Join-Path $root 'raw');raw_output_access='SYSTEM and BUILTIN\Administrators only';raw_output_publication='never';
        raw_sensitive_patterns_found=@($Receipt.raw_sensitive_patterns_found);login_inputs_written=0;pipeline_started=$false;
        automatic_retry_allowed=$false;message=$message}
}

function New-StageSummary {
    param($Receipt,$Verified,$Task,[string]$Nonce,[string]$ReceiptSha256)
    $root=$script:targetRoot;$gate=$Verified.gate;$receiptPath=Join-Path $root $script:receiptName
    $passed=((Test-ExactBool $gate.passed $true) -and $Verified.decision -ceq 'COMPLETE')
    $slots=@()
    foreach($entry in @($Receipt.slots)){
        $probes=@{};foreach($p in @($entry.probes)){if($null -ne $p -and (Test-HasProperty $p 'classification')){$probes[$p.id]=@($p.classification.agents)}}
        $reasons=@(if($Verified.slot_reasons.Contains($entry.slot)){$Verified.slot_reasons[$entry.slot]}else{'SLOT_NOT_VERIFIED'})
        $slots+=[ordered]@{slot=$entry.slot;identity=$entry.identity;passed=($reasons.Count -eq 0);reasons=$reasons;
            staged=@(@($entry.staged)|ForEach-Object {$_.path});preexisting=@(@($entry.staged)|ForEach-Object {$_.preexisting});
            protected_parents=@(@($entry.staged)|Where-Object {$null -ne $_ -and (Test-HasProperty $_ 'parent_path')}|ForEach-Object {$_.parent_path});
            agents_json=@(if($probes.ContainsKey('PC3')){$probes['PC3']});agents_text=@(if($probes.ContainsKey('PC4')){$probes['PC4']})}}
    $pd=$(if((Test-HasProperty $Receipt 'programdata_antigravity') -and $null -ne $Receipt.programdata_antigravity){$Receipt.programdata_antigravity}else{$null})
    $programData=$(if($null -ne $pd){[ordered]@{path=$script:programDataAntigravity;sddl=$script:programDataSddl;
        state=$(if(Test-HasProperty $pd 'state'){$pd.state}else{$null});created=$(if(Test-HasProperty $pd 'created'){$pd.created}else{$null});
        verified=($Verified.decision -ceq 'COMPLETE')}}else{$null})
    if($Verified.decision -cin @('FAILED','INCOMPLETE')){$message='GEMINI-HELD (G4): the six-slot agent staging did not complete ('+$Receipt.status+$(if($null -ne $Verified.failure){', phase '+$Verified.failure.phase+', '+$Verified.failure.error_type}else{''})+$(if(Test-HasProperty $Receipt 'failure_slot'){', '+$Receipt.failure_slot}else{''})+$(if($null -ne $programData -and $programData.state -cne 'PROTECTED_EMPTY'){', C:\ProgramData\Antigravity '+$programData.state+' (preserved for review)'}else{''})+'); evidence in '+$root+'. The sitting continues in Gemini-held mode (A4); nothing is retried.'}
    elseif(-not $passed){$message='GEMINI-HELD (G4): not every worker slot resolves the protected agent ('+(@($gate.reasons) -join ', ')+'); evidence in '+$root+'. The sitting continues in Gemini-held mode (A4).'}
    else{$message='Agent staging verified (G4 passed): all six worker profiles hold cochem-inference-only (sha256 '+$script:agentPin+') at both locations with SYSTEM/BA full and worker read-only, both parent folders protected (worker list and traverse only), C:\ProgramData\Antigravity is the protected empty folder, and every slot lists exactly [cochem-inference-only]. Receipt '+$receiptPath+' (sha256 '+$ReceiptSha256+').'}
    [ordered]@{schema='cochem-agy-agent-staging-result/1';mode='stage';status=$Receipt.status;decision=$Verified.decision;attempt=$script:Attempt;nonce=$Nonce;
        target_root=$root;receipt_path=$receiptPath;receipt_sha256=$ReceiptSha256;gemini_gate='G4';gemini_outcome=$(if($passed){'PASSED'}else{'HELD'});exit_code=$(if($passed){0}else{10});
        task_name=$script:taskName;last_task_result=$Task.LastTaskResult;task_preserved=$true;
        gate=[ordered]@{passed=$gate.passed;reasons=@($gate.reasons)};failure=$Verified.failure;failure_slot=$(if(Test-HasProperty $Receipt 'failure_slot'){$Receipt.failure_slot}else{$null});
        agent=[ordered]@{name=$script:agentName;sha256=$script:agentPin;destinations=$script:agentRelatives;parent_destinations=$script:agentParentRelatives};
        slots=$slots;slots_skipped=@($Receipt.slots_skipped);programdata_antigravity=$programData;
        isolation_inventory_clear=$Receipt.isolation_inventory_clear;model_jobs_executed=0;
        raw_output_location=(Join-Path $root 'raw');raw_output_access='SYSTEM and BUILTIN\Administrators only';raw_output_publication='never';
        raw_sensitive_patterns_found=@($Receipt.raw_sensitive_patterns_found);login_inputs_written=0;pipeline_started=$false;automatic_retry_allowed=$false;message=$message}
}

function New-IsolationHeldRecord {
    param([string]$Phase,[string]$Reason,[string]$Nonce,[bool]$Registered,[bool]$RunRequested,$Task,[bool]$ReceiptPresent,$Verified,$IntentHash,$TaskXmlHash,$Gate)
    $lastResult=$null;$state=$null;$instances=$null
    if($null -ne $Task){try{$lastResult=[int]$Task.LastTaskResult;$state=[int]$Task.State;$instances=[int]$Task.GetInstances(0).Count}catch{$lastResult=$null}}
    $identities=$(if($script:Mode -ceq 'stage'){$script:workerIdentities}else{@($script:workerIdentity)})
    [ordered]@{schema='cochem-agy-isolation-evidence-held/1';mode=$script:Mode;attempt=$script:Attempt;slot=$(if($script:Mode -ceq 'stage'){$null}else{$script:Slot});nonce=$Nonce;
        phase=$Phase;reason=$Reason;gemini_gate=$script:geminiGate;gemini_outcome='HELD';gate=$Gate;
        task_name=$script:taskName;task_registered=$Registered;run_requested=$RunRequested;task_state=$state;task_instances=$instances;last_task_result=$lastResult;
        receipt_present=$ReceiptPresent;helper_failure=$(if($null -ne $Verified){$Verified.failure}else{$null});intent_sha256=$IntentHash;task_xml_sha256=$TaskXmlHash;
        staged_agent_destinations=@($identities|ForEach-Object {Get-AgentDestinations $_});staged_agent_preserved=$true;
        raw_output_location=(Join-Path $script:targetRoot 'raw');task_preserved=$true;root_preserved=$true;processes_killed=$false;automatic_retry_allowed=$false;
        requires_reviewed_recovery=($Phase -cne 'GATE')}
}

function Invoke-AgyIsolation {
    param($Scheduler,$Folder,$Pins,[long]$HelperLength,[long]$AgentLength)
    try{
        # Elevated: inspect the code trees once before the SYSTEM task runs the r4 interpreter against the native binary.
        $codeTrees=[ordered]@{runtime=(Assert-CodeTreeOnce $script:r4Root);toolchain=(Assert-CodeTreeOnce $script:basePythonRoot);native=(Assert-CodeTreeOnce $script:nativeRoot)}
        if((Get-TaskPresence $Folder $script:taskName) -cne 'ABSENT'){throw 'The isolation task already exists; preserve it and choose another -Attempt.'}
        if(Test-Path -LiteralPath $script:targetRoot){throw 'The isolation root already exists; preserve it and choose another -Attempt.'}
    }catch{
        $reason=$_.Exception.Message
        throw ('The agy isolation evidence is held before any change: '+$reason.TrimEnd('.')+'. Nothing was changed.')}
    # From here the attempt namespace may be consumed: every failure after the root exists leaves the held record.
    $phase='ROOT';$registered=$false;$runRequested=$false;$task=$null;$nonce=$null;$failure=$null;$summary=$null;$intentHash=$null;$taskXmlHash=$null;$receiptPresent=$false;$verified=$null
    try{
        New-PrivateDirectory $script:targetRoot
        $phase='PREPARATION'
        $destination=Join-Path $script:targetRoot $script:helperName
        Copy-VerifiedPayload ([pscustomobject]@{source=$script:helperSource;destination=$destination;sha256=$script:helperPin;length=$HelperLength})
        $held.Add((Open-VerifiedFile $destination $script:helperPin $HelperLength))
        $agentCopy=Join-Path $script:targetRoot $script:agentFileName
        Copy-VerifiedPayload ([pscustomobject]@{source=$script:agentSource;destination=$agentCopy;sha256=$script:agentPin;length=$AgentLength})
        $held.Add((Open-VerifiedFile $agentCopy $script:agentPin $AgentLength))
        $nonce=New-IsolationNonce
        $identities=$(if($script:Mode -ceq 'stage'){$script:workerIdentities}else{@($script:workerIdentity)})
        $intent=[ordered]@{schema='cochem-agy-isolation-evidence-intent/1';mode=$script:Mode;attempt=$script:Attempt;slot=$(if($script:Mode -ceq 'stage'){$null}else{$script:Slot});
            effort_null_slug=$(if($script:Mode -ceq 'stage'){$null}else{$script:effortNullSlug});nonce=$nonce;requested_utc=[DateTime]::UtcNow.ToString('o');
            task_name=$script:taskName;target_root=$script:targetRoot;helper_sha256=$script:helperPin;agent_sha256=$script:agentPin;native_sha256=$script:agyPin;r4_bindings=$Pins;
            code_tree_entries=$codeTrees;task_action=[ordered]@{path=$script:r4Python;arguments=(Get-IsolationTaskArguments $destination $nonce);working_directory=$script:targetRoot};
            task_execution_time_limit=$script:taskTimeLimit;agent_destinations=@($identities|ForEach-Object {Get-AgentDestinations $_});
            agent_acl='SYSTEM and BUILTIN\Administrators full control, the slot worker read-only';
            agent_parent_protection=@(if($script:Mode -ceq 'stage'){$script:agentParentRelatives});
            programdata_antigravity=[ordered]@{path=$script:programDataAntigravity;sddl=$script:programDataSddl;
                action=$(if($script:Mode -ceq 'stage'){'create as the protected empty folder when absent; refuse and preserve any other state'}else{'inventory only (before and after the runs): absent or the protected empty folder'})};
            precheck=@(if($script:Mode -cne 'stage'){Get-ExpectedPrecheck|ForEach-Object {[ordered]@{id=$_.id;argv=@($script:nativeExecutable)+@($_.arguments)}}});
            listing_probes=@(if($script:Mode -ceq 'stage'){Get-ExpectedStageProbes|ForEach-Object {[ordered]@{id=$_.id;argv=@($script:nativeExecutable)+@($_.arguments)}}});
            runs=@(if($script:Mode -cne 'stage'){Get-ExpectedRuns|ForEach-Object {[ordered]@{id=$_.id;argv=@($_.argv)}}});prompt_line_sha256=$script:promptLineSha256;
            model_jobs_planned_maximum=$(if($script:Mode -ceq 'stage'){0}else{$script:maxModelJobs});answers_expected_maximum=$(if($script:Mode -ceq 'stage'){0}else{4});login_inputs_planned=0;retry=$false}
        $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot $script:intentName) ($intent|ConvertTo-Json -Depth 8)
        $phase='REGISTRATION'
        $definition=New-IsolationTaskDefinition $Scheduler $destination $nonce
        $registered=$true
        $task=$Folder.RegisterTaskDefinition($script:taskName,$definition,$script:taskRegistrationFlags,'SYSTEM',$null,5,$script:taskSddl)
        Assert-IsolationTaskRegistration $task $destination $nonce
        $taskXmlHash=Write-RegistrationControl (Join-Path $script:targetRoot $script:taskXmlName) ([string]$task.Xml)
        $phase='RUN'
        $runRequested=$true
        $instance=$task.Run($null)
        $phase='WAIT'
        Wait-IsolationTaskInstance $instance $script:taskWaitSeconds
        Assert-CompletedIsolationTask $task
        $phase='RECEIPT'
        $receiptPath=Join-Path $script:targetRoot $script:receiptName
        if(-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)){throw ('the isolation task left no receipt (LastTaskResult '+$task.LastTaskResult+')')}
        $receiptPresent=$true
        $receiptControl=Read-R3Control $receiptPath '' $script:receiptMaxBytes
        $receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json
        if($script:Mode -ceq 'stage'){
            $verified=Assert-StageReceipt $receipt $task $Pins $nonce $script:targetRoot
            $summary=New-StageSummary $receipt $verified $task $nonce $receiptControl.Sha256}
        else{
            $verified=Assert-IsolationReceipt $receipt $task $Pins $nonce $script:targetRoot
            $summary=New-IsolationSummary $receipt $verified $task $nonce $receiptControl.Sha256}
        $summary.intent_sha256=$intentHash;$summary.task_xml_sha256=$taskXmlHash
        $phase='SUMMARY'
        $null=Write-RegistrationControl (Join-Path $script:targetRoot $script:summaryName) ($summary|ConvertTo-Json -Depth 10)
        if($verified.decision -cin @('FAILED','INCOMPLETE')){$phase='HELPER';throw ('the isolation helper reported '+$receipt.status)}
        if($summary.gemini_outcome -cne 'PASSED'){
            # A4: a verified gate failure is a held record, never a retry and never a failed sitting.
            $phase='GATE'
            $null=Write-RegistrationControl (Join-Path $script:targetRoot $script:heldName) ((New-IsolationHeldRecord 'GATE' ('gate '+$script:geminiGate+' failed: '+(@($summary.gate.reasons) -join ', ')) $nonce $registered $runRequested $task $receiptPresent $verified $intentHash $taskXmlHash $summary.gate)|ConvertTo-Json -Depth 8)}
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        $heldNote=''
        if(Test-Path -LiteralPath $script:targetRoot){
            try{$null=Write-RegistrationControl (Join-Path $script:targetRoot $script:heldName) ((New-IsolationHeldRecord $phase $failure $nonce $registered $runRequested $task $receiptPresent $verified $intentHash $taskXmlHash $null)|ConvertTo-Json -Depth 8)}
            catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}}
        $message=switch($phase){
            'ROOT'{$(if(Test-Path -LiteralPath $script:targetRoot){'The isolation root could not be secured: '+$failure+'. Nothing was registered or run; preserve '+$script:targetRoot+' and choose another -Attempt.'}else{'The agy isolation evidence is held before any change: '+$failure+'. Nothing was changed.'})}
            'PREPARATION'{'The agy isolation evidence is held before any task exists: '+$failure+'. Preserve '+$script:targetRoot+' and review '+$script:heldName+' before another -Attempt.'}
            'REGISTRATION'{'The agy isolation evidence is held at task registration: '+$failure+'. No Run was requested; preserve the root and the task (if registered) and review '+$script:heldName+'.'}
            'RUN'{'The agy isolation evidence is held at its single Run request: '+$failure+'. Preserve everything and review '+$script:heldName+'.'}
            'WAIT'{'The agy isolation evidence did not end cleanly: '+$failure+'. Keep the daemons disabled, confirm the task has ended before any Warden start, preserve the task and root and review '+$script:heldName+'; do not retry automatically.'}
            'HELPER'{'GEMINI-HELD ('+$script:geminiGate+'): '+$failure+'; evidence in '+$script:targetRoot+' ('+$script:summaryName+', '+$script:heldName+'). The sitting continues in Gemini-held mode (A4).'}
            default{'The agy isolation receipt is refused: '+$failure+'. Preserve the task and root and review '+$script:heldName+'; the sitting continues in Gemini-held mode (A4).'}}
        if($null -ne $summary){Write-Host ($script:resultTag+' '+($summary|ConvertTo-Json -Depth 10 -Compress))}
        throw ($message+$heldNote)
    }
    $summary
}

function Exit-IsolationProcess {param([int]$Code)exit $Code}

function Write-IsolationOutcome {
    param($Summary)
    # Exit 0: gate passed, the summary JSON is the whole stdout. Exit 10: GEMINI-HELD, one tagged summary line plus the message.
    if((Test-ExactBool $Summary.gate.passed $true) -and $Summary.decision -ceq 'COMPLETE' -and $Summary.gemini_outcome -ceq 'PASSED'){return ($Summary|ConvertTo-Json -Depth 10)}
    Write-Host ($script:resultTag+' '+($Summary|ConvertTo-Json -Depth 10 -Compress))
    Write-Host $Summary.message
    Exit-IsolationProcess 10
}

function Assert-IsolationHost {
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
}

function Get-OwnerContext {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{name=$identity.Name;admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)}
}

function Get-IsolationHelperTexts {
    param([string]$Workspace)
    $copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')
    Import-ReviewedFunctions (Join-Path $Workspace 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')
    Import-ReviewedFunctions (Join-Path $Workspace 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')
    Import-ReviewedFunctions (Join-Path $Workspace 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')
    Import-ReviewedFunctions (Join-Path $Workspace 'retarget-warden-r4.ps1') '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e' @('Test-ExactBool','Test-ExactInt','Assert-R4InstalledBindings','New-PrivateAcl','Assert-PrivateAcl','New-PrivateDirectory')
}

function Get-TaskSchedulerFolder {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    [pscustomobject]@{scheduler=$scheduler;folder=$scheduler.GetFolder('\')}
}

function Test-IsolationFile {param([string]$Path)Test-Path -LiteralPath $Path -PathType Leaf}

function Get-WorkerProfilePresence {
    foreach($name in $script:workerIdentities){
        $profileRoot=Get-WorkerProfileRoot $name
        $present=$null;try{$present=[bool](Test-Path -LiteralPath $profileRoot -PathType Container -ErrorAction Stop)}catch{$present=$null}
        [ordered]@{identity=$name;profile_root=$profileRoot;present=$present}}
}

function Get-IsolationPlanState {
    param($Owner)
    $holds=@();$runtime=$null;$pins=$null;$helperLength=$null;$agentLength=$null;$nativeVerified=$false;$daemons=@();$taskPresence=$null
    try{$runtime=Assert-R4InstalledBindings;$pins=Assert-IsolationRuntimePins $runtime}catch{$holds+=('r4 runtime is not the reviewed build: '+$_.Exception.Message)}
    try{$helperLength=(Get-Item -LiteralPath $script:helperSource).Length;$held.Add((Open-VerifiedFile $script:helperSource $script:helperPin $helperLength))}
    catch{$helperLength=$null;$holds+=('The reviewed isolation helper differs from its pin or is missing: '+$_.Exception.Message)}
    try{$agentLength=(Get-Item -LiteralPath $script:agentSource).Length
        if($agentLength -ne $script:agentBytes){throw 'length differs'}
        $held.Add((Open-VerifiedFile $script:agentSource $script:agentPin $agentLength))}
    catch{$agentLength=$null;$holds+=('The reviewed agent definition differs from its pin or is missing: '+$_.Exception.Message)}
    foreach($path in @($script:r4Python,(Join-Path $script:r4Root 'windows-layout.json'),(Join-Path $script:r4Root 'pipeline.json'),$script:nativeExecutable,$script:basePython,(Join-Path $script:r4Root '.venv\pyvenv.cfg'))){
        if(-not (Test-IsolationFile $path)){$holds+=('A required stopped installation file is absent: '+$path)}
        else{try{Assert-ProtectedPath $path}catch{$holds+=('Protected path check failed: '+$_.Exception.Message)}}}
    if(Test-IsolationFile $script:nativeExecutable){
        try{$stream=Open-VerifiedFile $script:nativeExecutable $script:agyPin (Get-Item -LiteralPath $script:nativeExecutable).Length;$stream.Dispose();$nativeVerified=$true}
        catch{$holds+=('agy.exe differs from the reviewed pin: '+$_.Exception.Message)}}
    if(Test-Path -LiteralPath $script:targetRoot){$holds+='This one-shot isolation root already exists; preserve its evidence and choose another -Attempt.'}
    $tasks=Get-TaskSchedulerFolder
    try{$taskPresence=Get-TaskPresence $tasks.folder $script:taskName;if($taskPresence -cne 'ABSENT'){$holds+='This one-shot isolation task already exists; preserve it and choose another -Attempt.'}}
    catch{$holds+=('Isolation task state: '+$_.Exception.Message)}
    try{$daemons=@(Get-SeriesDaemonTaskStates $tasks.folder)
        $active=@($daemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($daemons|Where-Object {$_.state -ceq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
        if($active.Count){$holds+=('Protected daemons must remain stopped and disabled (run stop-warden-r4 first): '+($active -join ', '))}
        if($deferred.Count){$holds+=('Daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
    }catch{$holds+=('Daemon tasks: '+$_.Exception.Message)}
    $profiles=@(Get-WorkerProfilePresence)
    $needed=$(if($script:Mode -ceq 'stage'){$profiles}else{@($profiles[0])})
    if($Owner.admin){foreach($p in $needed){if($p.present -ne $true){$holds+=('A worker profile directory is not present: '+$p.profile_root)}}}
    $stage=($script:Mode -ceq 'stage')
    $identities=$(if($stage){$script:workerIdentities}else{@($script:workerIdentity)})
    $plan=[ordered]@{schema='cochem-agy-isolation-evidence-plan/1';mode='READ_ONLY_PLAN';evidence_mode=$script:Mode;gemini_gate=$script:geminiGate;attempt=$script:Attempt;
        slot=$(if($stage){$null}else{$script:Slot});effort_null_slug=$(if($stage){$null}else{$script:effortNullSlug});owner=$Owner.name;administrator=$Owner.admin;
        runtime_root=$script:r4Root;r4_runtime_verified=($null -ne $pins);r4_bindings=$pins;helper_source=$script:helperSource;helper_sha256=$script:helperPin;helper_verified=($null -ne $helperLength);
        agent_source=$script:agentSource;agent_sha256=$script:agentPin;agent_verified=($null -ne $agentLength);agent_name=$script:agentName;
        agent_destinations=@($identities|ForEach-Object {Get-AgentDestinations $_});
        agent_access='SYSTEM and BUILTIN\Administrators full control, the slot worker read-only; sha256 re-verified before every launch';
        agent_parent_protection=@(if($stage){$script:agentParentRelatives});
        programdata_antigravity=[ordered]@{path=$script:programDataAntigravity;sddl=$script:programDataSddl;
            action=$(if($stage){'the SYSTEM task creates it as the protected empty folder when absent and refuses any other state'}else{'inventoried read-only: absent or the protected empty folder, else G3 holds'})};
        job_expected_processes_maximum=$(if($stage){$null}else{$script:jobProcessMaximum});
        native_executable=$script:nativeExecutable;native_sha256=$script:agyPin;native_verified=$nativeVerified;native_version_at_pin=$script:agyVersion;
        task_name=$script:taskName;task_presence=$taskPresence;target_root=$script:targetRoot;target_root_access='SYSTEM and BUILTIN\Administrators only';
        receipt_name=$script:receiptName;summary_name=$script:summaryName;held_name=$script:heldName;
        task_execution_time_limit=$script:taskTimeLimit;task_action=[ordered]@{path=$script:r4Python;arguments=(Get-IsolationTaskArguments (Join-Path $script:targetRoot $script:helperName) '<nonce>');working_directory=$script:targetRoot};
        precheck=@(if(-not $stage){Get-ExpectedPrecheck|ForEach-Object {[ordered]@{id=$_.id;argv=@($script:nativeExecutable)+@($_.arguments);bound_seconds=$script:probeSeconds}}});
        listing_probes=@(if($stage){Get-ExpectedStageProbes|ForEach-Object {[ordered]@{id=$_.id;argv=@($script:nativeExecutable)+@($_.arguments);bound_seconds=$script:probeSeconds}}});
        stage_slots=@(if($stage){$script:stageSlots});
        runs=@(if(-not $stage){Get-ExpectedRuns|ForEach-Object {[ordered]@{id=$_.id;requested_model=$_.model;argv=@($_.argv);bound_seconds=$script:runSeconds;output_limit_bytes=$script:runOutputBytes}}});
        production_argument_template=$script:productionArguments;prompt=$(if($stage){$null}else{'Reply with exactly: ready true'});prompt_line_sha256=$script:promptLineSha256;
        stdin=$(if($stage){'empty file'}else{'one NDJSON line on a pipe, then EOF'});model_jobs_planned_maximum=$(if($stage){0}else{$script:maxModelJobs});
        answers_expected_maximum=$(if($stage){0}else{4});worker_identity=$(if($stage){$null}else{$script:workerIdentity});worker_profiles=$profiles;
        slot_root=$(if($stage){$null}else{Get-SlotRoot 'slot1'});ram_workspace_root=$(if($stage){$null}else{$script:ramWorkspaceRoot});daemon_tasks=$daemons;holds=$holds;
        exit_codes=[ordered]@{passed=0;gemini_held=10;refused_or_held_by_error=1};
        native_commands_executed=0;native_model_jobs_executed=0;login_inputs_written=0;files_created=0;tasks_changed=0;pipeline_started=$false;automatic_retry_allowed=$false}
    [pscustomobject]@{plan=$plan;holds=$holds;pins=$pins;helper_length=$helperLength;agent_length=$agentLength;scheduler=$tasks.scheduler;folder=$tasks.folder}
}

function Invoke-AgyIsolationMain {
    param([string]$Mode,[string]$Slot,[string]$Attempt,[string]$EffortNullSlug,[bool]$ApplyRequested,[string]$Workspace)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    if($Attempt -cnotmatch '^[a-f0-9]{32}$' -or ($ApplyRequested -and $Attempt -ceq '00000000000000000000000000000000')){throw 'A lowercase 32-hex -Attempt is required; -Apply forbids the all-zero preview attempt. Nothing was changed.'}
    if($Mode -cnotin @('evidence','stage')){throw 'Only the evidence (-Slot slot1) and -StageOnly modes are reviewed. Nothing was changed.'}
    if($Mode -ceq 'evidence'){
        if($null -eq $Slot -or $Slot.ToLowerInvariant() -cne 'slot1'){throw 'Only -Slot slot1 is reviewed. Nothing was changed.'}
        $Slot='slot1'
        if($EffortNullSlug -cnotin @('gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-3.8-flash-high')){throw 'The -EffortNullSlug must be gemini-3.8-flash-low, -medium or -high. Nothing was changed.'}
    }else{
        if($Slot){throw '-StageOnly covers all six slots and takes no -Slot. Nothing was changed.'}
        $Slot='';$EffortNullSlug=''}
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    Assert-IsolationHost
    $owner=Get-OwnerContext;$script:admin=$owner.admin
    if($ApplyRequested -and (-not $owner.admin -or $owner.name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
    Set-IsolationConstants $Mode $Slot $Attempt $Workspace $EffortNullSlug
    foreach($text in @(Get-IsolationHelperTexts $Workspace)){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $state=Get-IsolationPlanState $owner
        if(-not $ApplyRequested){$state.plan|ConvertTo-Json -Depth 8;return}
        if(@($state.holds).Count){throw ('The agy isolation evidence is held. Nothing was changed: '+(@($state.holds) -join ' | '))}
        Write-IsolationOutcome (Invoke-AgyIsolation $state.scheduler $state.folder $state.pins $state.helper_length $state.agent_length)
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-AgyIsolationMain -Mode $(if($StageOnly){'stage'}else{'evidence'}) -Slot $Slot -Attempt $Attempt -EffortNullSlug $EffortNullSlug -ApplyRequested ([bool]$Apply) -Workspace $PSScriptRoot
