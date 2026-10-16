[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('doctor', 'register', 'new', 'send', 'metadata', 'result', 'status', 'cancel')]
    [string]$Action,

    [ValidateSet('pro', 'flash', 'flash_lite', 'gemini-3.8-flash', 'argon', 'gemini-4-argon')]
    [string]$Model = 'gemini-3.8-flash',

    [ValidatePattern('^[a-z][a-z0-9_.-]*$')]
    [string]$ArgonApiModel,

    [ValidateSet('plan', 'grill-me', 'teamwork-preview', 'boost')]
    [string]$Workflow,

    [string]$Prompt,
    [string]$PromptFile,
    [switch]$Structured,
    [string]$Title = 'Codex delegated task',
    [string]$ConversationId,
    [string]$ProjectId,
    [string]$ProjectPath
)

$ErrorActionPreference = 'Stop'
if ($Prompt -and $PromptFile) { throw 'Use -Prompt or -PromptFile, not both.' }
if ($PromptFile) { $Prompt = [IO.File]::ReadAllText([IO.Path]::GetFullPath($PromptFile),[Text.Encoding]::UTF8) }

. (Join-Path $PSScriptRoot 'antigravity_workflows.ps1')
if ($Workflow -and $Action -notin @('new', 'send')) { throw '-Workflow is only supported for new or send.' }
if ($Action -in @('new', 'send')) {
    $workflowPrompt = Resolve-AntigravityWorkflowPrompt -Prompt $Prompt -Workflow $Workflow
    if ($workflowPrompt.Workflow) { $Workflow = $workflowPrompt.Workflow }
    $Prompt = $workflowPrompt.Prompt
}

if ($Action -eq 'new' -and $Model -in @('argon', 'gemini-4-argon') -and -not $ArgonApiModel) {
    throw 'Gemini 4 Argon requires -ArgonApiModel with a verified Agent API selector for this account. No task was sent.'
}

function Get-ProjectConfigPath {
    if ($env:ANTIGRAVITY_DELEGATE_CONFIG) {
        return [IO.Path]::GetFullPath($env:ANTIGRAVITY_DELEGATE_CONFIG)
    }

    return Join-Path (Split-Path -Parent $PSScriptRoot) 'projects.json'
}

function Get-NormalizedWorkspacePath {
    param([string]$Path = (Get-Location).Path)

    return [IO.Path]::GetFullPath($Path).TrimEnd('\').ToLowerInvariant()
}

function Test-ProjectId {
    param([string]$Value)

    if (-not $Value) {
        return $false
    }

    $guidValue = [guid]::Empty
    return [guid]::TryParse($Value, [ref]$guidValue) -and $guidValue -ne [guid]::Empty
}

function Get-CachedProjectId {
    $configPath = Get-ProjectConfigPath
    if (-not (Test-Path -LiteralPath $configPath)) {
        return $null
    }

    try {
        $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
        $workspace = Get-NormalizedWorkspacePath
        $entry = $config.projects.PSObject.Properties[$workspace].Value
        return $entry.project_id
    }
    catch {
        throw "Could not read Antigravity project mapping at ${configPath}: $($_.Exception.Message)"
    }
}

function Register-ProjectId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id,
        [string]$WorkspacePath = (Get-Location).Path
    )

    if (-not (Test-ProjectId -Value $Id)) {
        throw '-ProjectId must be a non-zero UUID for Action=register.'
    }
    if (-not (Test-Path -LiteralPath $WorkspacePath -PathType Container)) {
        throw "Project path is not an existing directory: $WorkspacePath"
    }

    $configPath = Get-ProjectConfigPath
    $workspace = Get-NormalizedWorkspacePath -Path $WorkspacePath
    if (Test-Path -LiteralPath $configPath) {
        try {
            $config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
        }
        catch {
            throw "Could not read Antigravity project mapping at ${configPath}: $($_.Exception.Message)"
        }
    }
    else {
        $config = [pscustomobject]@{
            projects = [pscustomobject]@{}
        }
    }

    if (-not $config.projects) {
        $config | Add-Member -NotePropertyName projects -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    $config.projects | Add-Member `
        -NotePropertyName $workspace `
        -NotePropertyValue ([pscustomobject]@{ project_id = $Id }) `
        -Force

    $configDirectory = Split-Path -Parent $configPath
    if (-not (Test-Path -LiteralPath $configDirectory)) {
        [void](New-Item -ItemType Directory -Path $configDirectory -Force)
    }
    $utf8NoBom = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText(
        $configPath,
        (($config | ConvertTo-Json -Depth 5) + [Environment]::NewLine),
        $utf8NoBom
    )

    [pscustomobject]@{
        registered  = $true
        workspace   = $workspace
        config_path = $configPath
    }
}

if ($Action -eq 'register') {
    if (-not $ProjectId) {
        $ProjectId = $env:ANTIGRAVITY_PROJECT_ID
    }
    if (-not $ProjectId) {
        throw 'Antigravity project UUID is required. Pass -ProjectId or set ANTIGRAVITY_PROJECT_ID.'
    }

    $workspaceToRegister = if ($ProjectPath) { $ProjectPath } else { (Get-Location).Path }
    Register-ProjectId -Id $ProjectId -WorkspacePath $workspaceToRegister |
        ConvertTo-Json -Depth 3
    exit 0
}

# A caller-supplied value wins, then an inherited Antigravity terminal value,
# then the project-local mapping for the current working directory.
if (-not $ProjectId) {
    $ProjectId = $env:ANTIGRAVITY_PROJECT_ID
}
if (-not $ProjectId) {
    $ProjectId = Get-CachedProjectId
}

function Get-AntigravityContext {
    $installHome = if ($env:ANTIGRAVITY_HOME) { $env:ANTIGRAVITY_HOME } else { Join-Path $env:USERPROFILE '.gemini\antigravity' }
    $launcher = Join-Path $installHome 'bin\agentapi.bat'
    if (-not (Test-Path -LiteralPath $launcher)) {
        throw "Antigravity Agent API launcher was not found at: $launcher. If you installed it elsewhere, please set the ANTIGRAVITY_HOME environment variable."
    }

    $address = $env:ANTIGRAVITY_LS_ADDRESS
    $csrfToken = $env:ANTIGRAVITY_CSRF_TOKEN
    $processId = $null

    if (-not $address -or -not $csrfToken) {
        try {
            $process = Get-CimInstance Win32_Process -Filter "Name='language_server.exe'" |
                Where-Object { $_.CommandLine -match '-csrf_token' } |
                Select-Object -First 1
        }
        catch {
            throw 'Cannot inspect the authenticated Antigravity process. Run from an Antigravity terminal or rerun with narrowly scoped elevated permission.'
        }

        if (-not $process) {
            throw 'No authenticated Antigravity language server was found. Start and sign in to Antigravity first.'
        }

        $processId = $process.ProcessId
        $tokenMatch = [regex]::Match(
            $process.CommandLine,
            '-csrf_token(?:=|\s+)(?:"([^"]+)"|([^ ]+))'
        )
        $csrfToken = $tokenMatch.Groups[1].Value + $tokenMatch.Groups[2].Value
        if (-not $csrfToken) {
            throw 'The authenticated Antigravity process did not expose a usable Agent API token.'
        }

        try {
            $ports = Get-NetTCPConnection -State Listen |
                Where-Object {
                    $_.OwningProcess -eq $process.ProcessId -and
                    $_.LocalAddress -in @('127.0.0.1', '::1')
                } |
                Sort-Object LocalPort
        }
        catch {
            throw 'Cannot discover the Antigravity loopback port. Rerun with narrowly scoped elevated permission.'
        }

        $agentPort = ($ports | Select-Object -Last 1).LocalPort
        if (-not $agentPort) {
            throw 'The authenticated Antigravity process has no discoverable loopback Agent API port.'
        }
        $address = "localhost:$agentPort"
    }

    [pscustomobject]@{
        Launcher  = $launcher
        Address   = $address
        CsrfToken = $csrfToken
        ProcessId = $processId
    }
}

function Get-AntigravityDataRoots {
    $candidateRoots = @()
    if ($env:ANTIGRAVITY_DATA_HOME) {
        $candidateRoots += $env:ANTIGRAVITY_DATA_HOME
    }
    if ($env:ANTIGRAVITY_HOME) {
        $candidateRoots += $env:ANTIGRAVITY_HOME
    }
    $candidateRoots += Join-Path $env:USERPROFILE '.gemini\antigravity'
    $candidateRoots += Join-Path $env:USERPROFILE '.gemini\antigravity-ide'

    return @(
        $candidateRoots |
            ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') } |
            Select-Object -Unique
    )
}

function Invoke-AgentApi {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Context
    )

    $previousAddress = $env:ANTIGRAVITY_LS_ADDRESS
    $previousToken = $env:ANTIGRAVITY_CSRF_TOKEN
    $previousProject = $env:ANTIGRAVITY_PROJECT_ID
    try {
        $env:ANTIGRAVITY_LS_ADDRESS = $Context.Address
        $env:ANTIGRAVITY_CSRF_TOKEN = $Context.CsrfToken
        $env:ANTIGRAVITY_PROJECT_ID = $ProjectId

        # `agentapi.bat` truncates a multi-line argument at the first newline.
        # Preserve prompt semantics by converting line breaks to spaces before
        # handing arguments to the batch launcher.
        $singleLineArguments = @(
            $Arguments | ForEach-Object {
                ($_ -replace "(\r\n|\n|\r)+", ' ').Trim()
            }
        )
        $raw = (& $Context.Launcher @singleLineArguments 2>&1 | Out-String).Trim()
        if (-not $raw) {
            throw 'Antigravity Agent API returned no output.'
        }

        try {
            $parsed = $raw | ConvertFrom-Json
        }
        catch {
            throw "Antigravity Agent API returned invalid JSON: $raw"
        }

        if ($parsed.error) {
            throw "Antigravity Agent API error: $($parsed.error)"
        }

        return $parsed
    }
    finally {
        $env:ANTIGRAVITY_LS_ADDRESS = $previousAddress
        $env:ANTIGRAVITY_CSRF_TOKEN = $previousToken
        $env:ANTIGRAVITY_PROJECT_ID = $previousProject
    }
}

function Get-ConversationResult {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id
    )

    $guidValue = [guid]::Empty
    if (-not [guid]::TryParse($Id, [ref]$guidValue)) {
        throw '-ConversationId must be a UUID for Action=result.'
    }

    $roots = Get-AntigravityDataRoots |
        ForEach-Object { Join-Path $_ "brain\$Id" }
    $transcript = $roots |
        ForEach-Object { Join-Path $_ '.system_generated\logs\transcript.jsonl' } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if (-not $transcript) {
        throw "No local transcript was found for conversation $Id."
    }

    $lastResponse = $null
    foreach ($line in Get-Content -LiteralPath $transcript) {
        try { $entry = $line | ConvertFrom-Json } catch { continue }
        if ($entry.source -eq 'USER_EXPLICIT') {
            $lastResponse = $null
            continue
        }
        $entryType = [string]$entry.type
        $entryStatus = [string]$entry.status
        $isVisibleType = $entryType -match '^(?i:message|response|assistant_message|assistant_response|model_response|planner_response|text)$'
        $isTerminal = $entryStatus -match '^(?i:complete|completed|done|finished|success|succeeded)$'
        if ($entry.source -eq 'MODEL' -and $entry.content -and $isVisibleType -and $isTerminal) {
            $lastResponse = [pscustomobject]@{
                Type = $entry.type
                Status = $entry.status
                Content = $entry.content
            }
        }
    }
    if (-not $lastResponse) {
        throw "Conversation $Id has no completed user-visible model response yet."
    }

    [pscustomobject]@{
        conversation_id = $Id
        type = $lastResponse.Type
        status = $lastResponse.Status
        content = $lastResponse.Content
    }
}

if ($Action -eq 'result') {
    if (-not $ConversationId) {
        throw '-ConversationId is required for Action=result.'
    }
    Get-ConversationResult -Id $ConversationId | ConvertTo-Json -Depth 5
    exit 0
}

$context = Get-AntigravityContext
if ($Action -in @('status','cancel')) {
    if (-not (Test-ProjectId -Value $ConversationId)) { throw 'A conversation UUID is required.' }
    Invoke-AntigravityTaskState -Context $context -Id $ConversationId -Cancel:($Action -eq 'cancel') | ConvertTo-Json -Depth 5
    exit 0
}

if ($Action -eq 'doctor') {
    [pscustomobject]@{
        launcher_found       = $true
        service_found        = [bool]$context.Address
        service_address      = $context.Address
        project_id_available = [bool]$ProjectId
        project_id_valid     = Test-ProjectId -Value $ProjectId
        project_id_source    = if (-not $ProjectId) { $null } elseif ($PSBoundParameters.ContainsKey('ProjectId')) { 'argument' } elseif ($env:ANTIGRAVITY_PROJECT_ID) { 'environment' } else { 'project-cache' }
        default_model        = 'gemini-3.8-flash'
        supported_models     = @('gemini-3.8-flash', 'gemini-4-argon (requires verified -ArgonApiModel)', 'flash_lite', 'pro (version unpinned)')
    } | ConvertTo-Json -Depth 3
    exit 0
}

if (-not $ProjectId) {
    throw 'Antigravity project UUID is required. Pass -ProjectId, set ANTIGRAVITY_PROJECT_ID, or use Action=register. The helper will not scan conversation history to recover it.'
}
if (-not (Test-ProjectId -Value $ProjectId)) {
    throw 'Antigravity project UUID must be a non-zero UUID.'
}

$modelAliases = @{
    'gemini-3.8-flash' = 'flash'
    'gemini-4-argon'   = $ArgonApiModel
    'argon'            = $ArgonApiModel
    'pro'              = 'pro'
    'flash'            = 'flash'
    'flash_lite'       = 'flash_lite'
}

switch ($Action) {
    'new' {
        if (-not $Prompt) {
            throw '-Prompt is required for Action=new.'
        }
        $initialPrompt = if ($Workflow) {
            'Workspace handshake only. Do not use tools, files, commands, network, or agents. Reply WORKSPACE_HANDSHAKE_OK and stop.'
        } else { $Prompt }
        $result = Invoke-AgentApi -Context $context -Arguments @(
            'new-conversation',
            "--model=$($modelAliases[$Model])",
            "--title=$Title",
            $initialPrompt
        )
        if ($Workflow) {
            $id = $result.response.newConversation.conversationId
            if (-not $id) { throw 'The workflow handshake did not return a conversation ID.' }
            $receipt = Invoke-AntigravityWorkflow -Context $context -Id $id -Workflow $Workflow -Prompt $Prompt
            $result.response.newConversation.prompt = $Prompt
            $result | Add-Member -NotePropertyName workflow -NotePropertyValue $receipt
        }
    }
    'send' {
        if (-not $ConversationId -or -not $Prompt) {
            throw '-ConversationId and -Prompt are required for Action=send.'
        }
        if ($Workflow -or $Structured) {
            $receipt = Invoke-AntigravityWorkflow -Context $context -Id $ConversationId -Workflow $Workflow -Prompt $Prompt
            $result = [pscustomobject]@{ workflow = $receipt }
            break
        }
        $result = Invoke-AgentApi -Context $context -Arguments @(
            'send-message',
            "--title=$Title",
            $ConversationId,
            $Prompt
        )
    }
    'metadata' {
        if (-not $ConversationId) {
            throw '-ConversationId is required for Action=metadata.'
        }
        $result = Invoke-AgentApi -Context $context -Arguments @(
            'get-conversation-metadata',
            $ConversationId
        )
    }
}

$result | ConvertTo-Json -Depth 20
