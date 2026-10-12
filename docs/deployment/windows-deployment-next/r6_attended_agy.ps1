#Requires -Version 5.1
<# Reuse the reviewed attended Agy bridge, with an absolute owner-input cutoff.
   The bridge cancellation protocol and terminal cleanup remain unchanged.
   This helper must only be called after an explicit logged-out status. #>
[CmdletBinding()]
param([string]$Slot,[string]$DeadlineUtc,[string]$WrapperSha256,[switch]$Apply)

function Invoke-R6AttendedAgy {
    param([string]$Slot,[string]$DeadlineText,[string]$WrapperHash,[bool]$ApplyRequested,[string]$Directory)
    if($Slot -cnotmatch '^slot[1-6]$' -or $WrapperHash -cnotmatch '^[a-f0-9]{64}$'){throw 'Invalid attended login binding.'}
    $deadline=[DateTime]::ParseExact($DeadlineText,'o',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
    if($deadline -le [DateTime]::UtcNow.AddSeconds(30) -or $deadline -gt [DateTime]::UtcNow.AddMinutes(20)){throw 'The attended login window is closed or invalid.'}
    $path=Join-Path $Directory 'login_pipeline_worker_interactive_agy_r4_v1.ps1'
    $stream=[IO.File]::Open($path,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($hash -cne $WrapperHash){throw 'The reviewed Agy wrapper changed.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'The reviewed Agy wrapper does not parse.'}
        foreach($node in $ast.EndBlock.Statements){if($node -is [Management.Automation.Language.FunctionDefinitionAst]){. ([scriptblock]::Create($node.Extent.Text))}}
        # Replace only the console-loop deadline argument. Native task/bridge
        # timeouts and cancellation/cleanup use their original reviewed code.
        $originalLoop=${function:Invoke-AgyLoginConsoleLoop}
        function Invoke-AgyLoginConsoleLoop {
            param($Instance,[string]$Root,[string]$Nonce,[DateTime]$DeadlineUtc)
            $bounded=if($deadline -lt $DeadlineUtc){$deadline}else{$DeadlineUtc}
            & $originalLoop $Instance $Root $Nonce $bounded
        }
        Resolve-AgyLoginExitCode @(Invoke-AgyLoginMain -Slot $Slot -LoginMode 'print' -CaptureAttempt '' -ApplyRequested $ApplyRequested -InteractiveRequested $true -ScriptRoot $Directory)
    }finally{$stream.Dispose()}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
exit (Invoke-R6AttendedAgy $Slot $DeadlineUtc $WrapperSha256 ([bool]$Apply) $PSScriptRoot)
