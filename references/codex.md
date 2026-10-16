# Codex profile delegation

## Target and execution

The helper uses Python's standard library and the installed `codex app-server --listen stdio://`. It launches under an explicitly selected, existing Codex home and checks its ChatGPT account through `account/read`. Inherited OpenAI API-key/base-URL overrides are removed from the child environment.

Use [setup.md](setup.md#codex) once to register a target. Later calls use `--target`; an account-pin mismatch stops before dispatch. Starting a separate app-server does not establish control of an existing desktop window or guarantee sidebar refresh.

## Run and continue

Resolve `<skill>` to this skill's installed directory. Use an available Python 3.10+ interpreter; no Python packages are required.

```powershell
python "<skill>/scripts/invoke_codex.py" new --target codex-b --cwd "<workspace>" --state-dir "<workspace>/.agent-delegate/codex" --prompt "Review the specified files without editing them."
python "<skill>/scripts/invoke_codex.py" send --target codex-b --conversation-id "<UUID>" --state-dir "<workspace>/.agent-delegate/codex" --prompt "Verify the specific issue in your previous answer."
python "<skill>/scripts/invoke_codex.py" result --conversation-id "<UUID>" --state-dir "<workspace>/.agent-delegate/codex"
```

The shared PowerShell helper supports the same flow with `-Provider codex`, `-Target`, `-Workspace`, `-StateDir`, and optionally `-PythonPath`. Use `--prompt-file` / `-PromptFile` for a UTF-8 task file.

`new` and `send` wait for the submitted turn and emit a receipt. For a longer task, keep the shell process in a managed background session and poll it. `metadata` reads the saved receipt; `result` requires the latest turn to have completed successfully. Receipts exclude reasoning and raw protocol events.

## Common commands

Codex slash commands are client actions. The helper translates these operations to native app-server calls:

| Intent | Helper invocation | API |
| --- | --- | --- |
| `/plan` | `new` / `send --mode plan --prompt "<task>"` | `turn/start` with Plan collaboration mode |
| `/review` | `new` / `send --mode review --prompt "<review scope>"` | `review/start`, custom target, inline delivery |
| `/compact` | `compact --conversation-id "<UUID>"` | `thread/compact/start`; wait for compaction and turn completion |
| `/resume` | `send --conversation-id "<UUID>" --prompt "<follow-up>"` | `thread/resume`, then the requested operation |

Repeat the same target and receipt directory. Modes persist across `send`; use `--mode default` to return to ordinary execution. `/plan <task>` and `/review <scope>` prompt prefixes are also translated. The shared PowerShell entry uses `-Mode plan|review|default` and `-Action compact`.

Use Plan for a reviewable proposal, Review for defect finding, and Compact when a long conversation needs context reduction. Plan text and native review output are retained as visible results. Compaction success requires a `contextCompaction` item and a completed turn. Native mode discovery uses the app-server experimental API; unavailable methods fail without silently forwarding slash text.

## Permissions and lifecycle

- Default sandbox: `read-only`. Authorized edits require `--sandbox workspace-write`; repeat that mode on continuation. Model and effort are omitted by default so the target retains its configuration.
- Interactive approval/input requests fail rather than receive fabricated consent. Use an interactive client when the task requires interaction.
- `--timeout` is 1–1200 seconds. On timeout the helper interrupts its own turn and closes its own app-server.
- Continue with the same account, home, workspace, model, and receipt directory. Conversation locks prevent concurrent helper turns; check a stale lock's owner before removing it.

References: [OpenAI app-server documentation](https://learn.chatgpt.com/docs/app-server).
