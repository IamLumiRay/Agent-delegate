[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('codex','antigravity')][string]$Provider,
    [Parameter(Mandatory)][ValidateSet('discover','doctor','register','new','send','compact','metadata','result')][string]$Action,
    [string]$Target, [string]$CodexHome, [string]$ExpectedAccount,
    [string]$Prompt, [string]$PromptFile, [string]$ConversationId,
    [string]$Workspace, [string]$StateDir, [string]$Title,
    [ValidateSet('read-only','workspace-write')][string]$Sandbox = 'read-only',
    [string]$Model, [string]$Effort,
    [ValidateSet('default','plan','review')][string]$Mode,
    [ValidateRange(1,1200)][int]$TimeoutSeconds = 1200,
    [string]$ProjectId, [string]$ArgonApiModel, [string]$PythonPath,
    [ValidateSet('plan','grill-me','teamwork-preview','boost')][string]$Workflow
)
$ErrorActionPreference = 'Stop'

if ($Prompt -and $PromptFile) { throw 'Use -Prompt or -PromptFile, not both.' }
if ($Provider -eq 'codex') {
    if ($ProjectId -or $ArgonApiModel -or $Workflow) {
        throw '-ProjectId, -ArgonApiModel and -Workflow belong to the Antigravity backend.'
    }
    $python = if ($PythonPath) { $PythonPath } elseif ($env:AGENT_DELEGATE_PYTHON) { $env:AGENT_DELEGATE_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
    $arguments = @((Join-Path $PSScriptRoot 'invoke_codex.py'), $Action)
    $values = @{
        '--target'=$Target; '--codex-home'=$CodexHome; '--expected-account'=$ExpectedAccount;
        '--prompt'=$Prompt; '--prompt-file'=$PromptFile; '--conversation-id'=$ConversationId;
        '--cwd'=$Workspace; '--state-dir'=$StateDir; '--title'=$Title; '--model'=$Model; '--effort'=$Effort; '--mode'=$Mode
    }
    foreach ($key in $values.Keys) {
        if ($values[$key]) { $arguments += @($key, $values[$key]) }
    }
    $arguments += @('--sandbox', $Sandbox, '--timeout', [string]$TimeoutSeconds)
    & $python @arguments
    exit $LASTEXITCODE
}

if ($Action -in @('discover','compact') -or $Target -or $CodexHome -or $ExpectedAccount -or $StateDir -or $Mode -or
    $Effort -or $PythonPath -or $PSBoundParameters.ContainsKey('Sandbox') -or
    $PSBoundParameters.ContainsKey('TimeoutSeconds')) {
    throw 'Codex discovery, target, runtime, permission and timeout options are not accepted by the Antigravity backend.'
}
$parameters = @{ Action=$Action }
if ($PromptFile) { $Prompt = [IO.File]::ReadAllText([IO.Path]::GetFullPath($PromptFile), [Text.Encoding]::UTF8) }
foreach ($name in @('Prompt','ConversationId','Title','Model','ProjectId','ArgonApiModel','Workflow')) {
    $value = Get-Variable -Name $name -ValueOnly
    if ($value) { $parameters[$name] = $value }
}
if ($Workspace) {
    if ($Action -eq 'register') { $parameters.ProjectPath=$Workspace }
    else { throw 'Antigravity workspace is verified through its project mapping and metadata handshake, not -Workspace.' }
}
& (Join-Path $PSScriptRoot 'invoke_antigravity.ps1') @parameters
