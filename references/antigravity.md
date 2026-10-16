# Antigravity delegation

The Windows helper uses PowerShell 7 and the running Antigravity Agent API. For first use, follow [setup.md](setup.md#antigravity); reuse the saved workspace mapping afterward. Run commands from the intended workspace, using an absolute helper path.

## Models

| Helper name | API selector |
| --- | --- |
| `gemini-3.8-flash`, `flash` (default) | `flash` |
| `gemini-4-argon`, `argon` | Explicit verified `-ArgonApiModel` |
| `pro` | `pro` tier; version unpinned |
| `flash_lite` | `flash_lite` |

Argon availability depends on the account. Verify its selector before use; do not assume `pro` identifies Argon. API tier names do not pin a model version. This helper cannot directly select Claude or GPT-OSS for a new conversation.

## Dispatch and retrieve

Before a task may access files, create a no-op conversation and use `metadata` to verify its workspace URI. Send the real task only after a match. Structured workflow calls perform this handshake automatically.

```powershell
pwsh -File "<skill>/scripts/invoke_antigravity.ps1" -Action doctor
pwsh -File "<skill>/scripts/invoke_antigravity.ps1" -Action new -Prompt "No-op handshake. No tools or file access. Reply HANDSHAKE_OK."
pwsh -File "<skill>/scripts/invoke_antigravity.ps1" -Action metadata -ConversationId "<UUID>"
pwsh -File "<skill>/scripts/invoke_antigravity.ps1" -Action send -ConversationId "<UUID>" -Prompt "Review the specified files without editing them."
pwsh -File "<skill>/scripts/invoke_antigravity.ps1" -Action result -ConversationId "<UUID>"
```

Preserve the conversation ID for continuation. `metadata` confirms routing; it does not establish task completion. `result` selects completed visible messages after the latest explicit request; a message marked `DONE` may still report waiting for a worker. Verify the requested deliverable before declaring the workflow complete. Treat a nonempty API `error` as failure even if the process exits successfully. Limit monitoring to 20 minutes unless the user requests longer.

## Common workflows

Use `-Workflow <name>` on `new` / `send`. The helper also recognizes `/name <task>` and `[/name]\(slashCommand;name) <task>`, with a space before the task and no braces.

| Name | Choose when |
| --- | --- |
| `plan` | Produce an implementation plan before executing changes. |
| `grill-me` | Clarify requirements through an interview; expect questions. |
| `boost` | Investigate a difficult bug or algorithm with parallel verification. |
| `teamwork-preview` | Scope a sustained task with multiple roles and milestones. |

Ordinary delegation needs no workflow. Teamwork begins with scoping; a scope draft does not prove team execution has started. Persistent goals, schedules, and rule learning belong to separately requested workflows.

The helper retrieves the running app's official command definition and submits a structured command through its local RPC. Preserve the task's scope and stopping condition; verify workflow artifacts before claiming success. Ordinary `invoke_subagent` delegation is separate from the native Teamwork workflow.

Service authentication stays ephemeral. Some installations require narrowly scoped local process-inspection permission. The local API and transcript schema may change after app updates; fail explicitly if the requested route is unavailable.

References: [Antigravity slash commands](https://antigravity.google/docs/slash-commands/), [Boost](https://antigravity.google/docs/boost/).
