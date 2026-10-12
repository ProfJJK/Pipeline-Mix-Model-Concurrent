# Metadata-only console regression. Run under a pseudo-console with -Source.
# Parses the production call site; imports no deployment function or host action.
param([Parameter(Mandatory=$true)][string]$Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Source does not parse.'}
$main=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-R6LaunchMain'},$false))
if($main.Count -ne 1){throw 'Expected one launch main function.'}
$command=@($main[0].FindAll({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -ceq 'Invoke-R6LaunchSequence'},$true))
if($command.Count -ne 1){throw 'Expected one console sequence call site.'}
$site=$command[0].Parent
if($site.Parent -is [Management.Automation.Language.AssignmentStatementAst]){$site=$site.Parent}
$script:consoleExit=-1
function Invoke-R6LaunchSequence {
    param($Manifest)
    $probe='[Console]::WriteLine("inherited_console_output_redirected="+[Console]::IsOutputRedirected); if([Console]::IsOutputRedirected){exit 97}else{exit 0}'
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($probe))
    & 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -NonInteractive -EncodedCommand $encoded
    $script:consoleExit=$LASTEXITCODE
    $script:R6LaunchResult=@{status='fixture'}
}
$manifest=@{}
. ([scriptblock]::Create($site.Extent.Text))
[Console]::WriteLine('production_call_site_probe_exit='+$script:consoleExit)
if($script:consoleExit -ne 0){exit 1}
