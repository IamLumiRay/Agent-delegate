function Resolve-AntigravityWorkflowPrompt {
    param([string]$Prompt, [string]$Workflow)

    $pattern = '^(?:/(?<name>plan|grill-me|teamwork-preview|boost)|\[/(?<name>plan|grill-me|teamwork-preview|boost)\]\\?\(slashCommand;\k<name>\))(?=\s|$)\s*'
    $prefix = [regex]::Match($Prompt, $pattern)
    if ($prefix.Success) {
        $command = $prefix.Groups['name'].Value
        if ($Workflow -and $Workflow -ne $command) {
            throw 'The workflow option and prompt command disagree. No task was sent.'
        }
        $Workflow = $command
        $Prompt = $Prompt.Substring($prefix.Length)
    }
    if ($Workflow -and [string]::IsNullOrWhiteSpace($Prompt)) {
        throw 'A workflow requires a task body. No task was sent.'
    }
    [pscustomobject]@{ Workflow = $Workflow; Prompt = $Prompt }
}

function New-AntigravityWorkflowItems {
    param([Parameter(Mandatory)]$Command, [Parameter(Mandatory)][string]$Prompt)

    @(
        @{ item = @{ slashCommand = @{ info = $Command.info; argumentValues = @{} } } },
        @{ text = ' ' + $Prompt }
    )
}

function Get-AntigravityWebOrigin {
    param([Parameter(Mandatory)]$Context)

    $serviceProcessId = $Context.ProcessId
    if (-not $serviceProcessId) {
        $service = Get-CimInstance Win32_Process -Filter "Name='language_server.exe'" |
            Where-Object {
                $match = [regex]::Match($_.CommandLine, '-csrf_token(?:=|\s+)(?:"([^"]+)"|([^ ]+))')
                ($match.Groups[1].Value + $match.Groups[2].Value) -ceq $Context.CsrfToken
            } | Select-Object -First 1
        $serviceProcessId = $service.ProcessId
    }
    if (-not $serviceProcessId) { throw 'Cannot identify the authenticated Antigravity app process.' }

    $ports = @(Get-NetTCPConnection -State Listen |
        Where-Object {
            $_.OwningProcess -eq $serviceProcessId -and $_.LocalAddress -in @('127.0.0.1', '::1')
        } | Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
    foreach ($port in $ports) {
        $origin = "https://127.0.0.1:$port"
        try {
            $page = Invoke-WebRequest -Uri "$origin/" -SkipCertificateCheck -MaximumRedirection 0 -TimeoutSec 3 -ErrorAction Stop
            if ($page.StatusCode -eq 200 -and $page.Content -match '/main\.js') { return $origin }
        }
        catch {}
    }
    throw 'The authenticated Antigravity app has no discoverable HTTPS frontend. No workflow was sent.'
}

function Invoke-AntigravityWorkflow {
    param(
        [Parameter(Mandatory)]$Context,
        [Parameter(Mandatory)][string]$Id,
        [string]$Workflow,
        [Parameter(Mandatory)][string]$Prompt
    )

    $response = Invoke-AgentApi -Context $Context -Arguments @('get-conversation-metadata', $Id)
    $metadata = $response.response.conversationMetadata.metadata
    $expectedUri = [Uri]::new((Get-Location).Path.TrimEnd('\') + '\').AbsoluteUri.TrimEnd('/')
    $workspaces = @($metadata.workspaces.workspaceFolderAbsoluteUri)
    if (-not ($workspaces | Where-Object { $_.TrimEnd('/') -ieq $expectedUri })) {
        throw 'Antigravity workflow workspace does not match the current directory. No workflow was sent.'
    }
    $config = $metadata.staticConfig.cascadeConfig
    if (-not $config.plannerConfig.planModel) { throw 'The conversation has no verified model configuration.' }

    $origin = Get-AntigravityWebOrigin -Context $Context
    $rpcBase = "$origin/exa.language_server_pb.LanguageServerService/"
    $headers = @{ 'x-codeium-csrf-token' = $Context.CsrfToken; 'Connect-Protocol-Version' = '1' }
    if ($Workflow) {
    $catalogBody = @{
        cascadeId = $Id; cascadeConfig = $config
        workspaceUris = $workspaces; projectId = $metadata.projectId
    } | ConvertTo-Json -Depth 30 -Compress
    $catalog = Invoke-RestMethod -Uri ($rpcBase + 'GetSlashCommands') -Method Post -Headers $headers `
        -ContentType 'application/json' -Body $catalogBody -SkipCertificateCheck -MaximumRedirection 0 -TimeoutSec 15
    if ($catalog.error) { throw 'Antigravity returned an error instead of a workflow catalog.' }
    $commands = @($catalog.commands | Where-Object { $_.info.name -eq $Workflow })
    if ($commands.Count -ne 1 -or $commands[0].info.type -notin @('SLASH_COMMAND_TYPE_SYSTEM', 1)) {
        throw "The requested workflow '$Workflow' is unavailable. No substitute was sent."
    }
    $items = @(New-AntigravityWorkflowItems -Command $commands[0] -Prompt $Prompt)
    } else { $items = @(@{text=$Prompt}) }
    $body = @{
        cascadeId = $Id; cascadeConfig = $config
        items = $items
    } | ConvertTo-Json -Depth 30 -Compress
    $sendResponse = Invoke-RestMethod -Uri ($rpcBase + 'SendUserCascadeMessage') -Method Post -Headers $headers `
        -ContentType 'application/json' -Body $body -SkipCertificateCheck -MaximumRedirection 0 -TimeoutSec 30
    if ($sendResponse.error) { throw 'Antigravity rejected the structured workflow message.' }
    [pscustomobject]@{
        command = $Workflow; conversation_id = $Id; transport = 'structured-app-rpc'
        submitted = $true; workspace_verified = $true
    }
}

function Invoke-AntigravityTaskState {
    param($Context, [string]$Id, [switch]$Cancel)
    $metadata = (Invoke-AgentApi -Context $Context -Arguments @('get-conversation-metadata',$Id)).response.conversationMetadata.metadata
    $expected = [Uri]::new((Get-Location).Path.TrimEnd('\')+'\').AbsoluteUri.TrimEnd('/')
    if (-not (@($metadata.workspaces.workspaceFolderAbsoluteUri) | Where-Object {$_.TrimEnd('/') -ieq $expected})) {
        throw 'Conversation workspace mismatch; no status action was performed.'
    }
    $origin = Get-AntigravityWebOrigin -Context $Context
    $rpc = "$origin/exa.language_server_pb.LanguageServerService/"
    $headers = @{'x-codeium-csrf-token'=$Context.CsrfToken;'Connect-Protocol-Version'='1'}
    $body = @{cascadeId=$Id}|ConvertTo-Json -Compress
    if ($Cancel) {
        $cancelBody = @{conversationId=$Id}|ConvertTo-Json -Compress
        $response = Invoke-RestMethod -Uri ($rpc+'ForceStopCascadeTree') -Headers $headers -Method Post -Body $cancelBody -ContentType 'application/json' -SkipCertificateCheck -MaximumRedirection 0 -TimeoutSec 15
        if ($response.error) { throw 'Antigravity rejected task cancellation.' }
    }
    $r = Invoke-RestMethod -Uri ($rpc+'GetCascadeTrajectory') -Headers $headers -Method Post -Body $body -ContentType 'application/json' -SkipCertificateCheck -MaximumRedirection 0 -TimeoutSec 15
    if ($r.error -or -not $r.status) { throw 'Antigravity did not return a verifiable runtime status.' }
    $steps = @($r.trajectory.steps)
    while ($steps.Count -lt $r.numTotalSteps) {
        $pageBody = @{cascadeId=$Id;stepOffset=$steps.Count}|ConvertTo-Json -Compress
        $page = Invoke-RestMethod -Uri ($rpc+'GetCascadeTrajectorySteps') -Headers $headers -Method Post -Body $pageBody -ContentType 'application/json' -SkipCertificateCheck -MaximumRedirection 0 -TimeoutSec 15
        if (-not $page.steps) { throw 'Incomplete trajectory; cannot verify the latest response.' }
        $steps += @($page.steps)
    }
    $content=$null; $responseIndex=-1; $userIndex=-1; $hasError=$false
    for ($i=0; $i -lt $steps.Count; $i++) {
        $step=$steps[$i]
        if ($step.type -eq 'CORTEX_STEP_TYPE_USER_INPUT') { $userIndex=$i; $content=$null; $responseIndex=-1; $hasError=$false }
        if ($step.type -eq 'CORTEX_STEP_TYPE_PLANNER_RESPONSE' -and $step.status -eq 'CORTEX_STEP_STATUS_DONE' -and $step.plannerResponse.response) {
            $content=$step.plannerResponse.response; $responseIndex=$i
        }
        if ($step.type -eq 'CORTEX_STEP_TYPE_ERROR_MESSAGE' -or $step.status -eq 'CORTEX_STEP_STATUS_ERROR') { $hasError=$true }
    }
    [pscustomobject]@{conversation_id=$Id;run_status=$r.status;step_count=$steps.Count;latest_user_index=$userIndex;response_index=$responseIndex;content=$content;has_error=$hasError;cancel_requested=[bool]$Cancel;workspace_verified=$true}
}
