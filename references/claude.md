# Claude Code delegation

## Runtime and authentication

Use the installed Claude CLI with its existing login. No Claude desktop window, API-key extraction or Python SDK is needed. Register the selected CLI and configuration directory with [setup.md](setup.md#claude-code). Authentication stays native; the helper checks the CLI's available nonsecret auth metadata before dispatch and on continuation. The fingerprint does not hash credentials and cannot detect changes absent from that metadata.

The CLI must support `--safe-mode`, `--restricted`, `--permission-prompts` and structured print output; `doctor` checks these features. On Windows the official npm wrapper resolves to its native `claude.exe`. Other Windows command wrappers are not executed through a shell.

## Run and continue

Configure [state ignore rules](setup.md#local-state-and-git) first. Resolve `<skill>` to its installed directory.

```powershell
python -B "<skill>/scripts/invoke_claude.py" new --target claude-main --cwd "<workspace>" --state-dir "<workspace>/.agent-delegate/claude" --prompt "Review these files without editing them."
python -B "<skill>/scripts/invoke_claude.py" send --target claude-main --conversation-id "<UUID>" --state-dir "<workspace>/.agent-delegate/claude" --prompt "Verify the specific concern in your previous answer."
python -B "<skill>/scripts/invoke_claude.py" result --conversation-id "<UUID>" --state-dir "<workspace>/.agent-delegate/claude"
```

The shared PowerShell entry uses `-Provider claude -Target claude-main`, with `-Workspace`, `-StateDir`, `-PromptFile`, `-PythonPath` and `-TimeoutSeconds`. `-ClaudeCli` and `-ClaudeHome` select explicit routing during setup. `--model` selects a model for a new task; continuation uses the recorded exact resolved model. Optional `--effort` retains the CLI's supported effort values.

Receipts retain final visible text and routing/status metadata. Thinking, tool payloads, raw errors and transcripts are not copied. Success requires the expected session/workspace, a confirmed model, a successful native result, a zero exit code, no permission denials and a nonempty answer. Verify the actual deliverable.

If the CLI needs proxy or TLS/runtime environment settings, the MCP client must retain the necessary local settings for its server process. An SDK test client may omit them even when native login checks pass. Keep those values local; never put them in the release or target registry.

## Tools and lifecycle

- Default tools: Read, Glob and Grep. Authorized `--sandbox workspace-write` adds Edit and Write. Native restricted mode confines built-in file tools to working directories; this is not an additional OS sandbox.
- Safe mode disables customizations while preserving authentication. Restricted mode, explicit tool lists and empty strict MCP configuration exclude shell execution, subagents and external MCP tools. Native administrator policy still applies. The helper does not bypass permissions or fabricate approval.
- Ordinary tasks and exact UUID continuation are supported. Other providers' modes and workflows are rejected. Never use latest-session selection, name matching, forks or unrelated transcripts as a substitute for the saved ID.
- Each call owns one print process. Timeout/cancellation stops that process; without a native completion acknowledgement, its receipt is `unknown`. Inspect the provider before retrying overlapping work. Only completed receipts can be continued by this helper. Locks prevent concurrent helper turns.

References: [CLI reference](https://code.claude.com/docs/en/cli-reference), [programmatic use](https://code.claude.com/docs/en/headless).
