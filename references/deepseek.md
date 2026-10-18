# DeepSeek Harness delegation

## Setup and authentication

Use the installed `dsh sdk` command. Desktop's bundled command works with its window closed; it does not attach to an existing desktop conversation. No separate runtime, service, or Python SDK is needed.

Register a command, existing DSH home, native provider route and available model with [setup.md](setup.md#deepseek-harness). `deepseek-account` reuses the application's login. `deepseek-official` needs native API-key configuration and never substitutes for the account route. Do not retrieve or copy credentials. The headless profile disables stored account authentication, so this adapter uses the SDK profile.

On Windows, select Desktop's `resources/runtime/cli/bin/dsh.cmd`; the helper uses its Electron carrier directly without a command shell. Native `dsh` executables and executable POSIX launchers are also accepted. npm `.cmd` wrappers are not supported by this adapter.

## Run and continue

Configure the [workspace's state ignore rules](setup.md#local-state-and-git) first. Resolve `<skill>` to the installed directory.

```powershell
python -B "<skill>/scripts/invoke_deepseek.py" new --target deepseek-main --cwd "<workspace>" --state-dir "<workspace>/.agent-delegate/deepseek" --prompt "Check this result independently without editing files."
python -B "<skill>/scripts/invoke_deepseek.py" send --target deepseek-main --conversation-id "<session handle>" --state-dir "<workspace>/.agent-delegate/deepseek" --prompt "Check the specific concern in your previous answer."
python -B "<skill>/scripts/invoke_deepseek.py" result --conversation-id "<session handle>" --state-dir "<workspace>/.agent-delegate/deepseek"
```

The shared entry uses `-Provider deepseek -Target deepseek-main`; `-Workspace`, `-StateDir`, `-PromptFile`, `-Model`, `-Effort`, `-PythonPath` and `-TimeoutSeconds` have the same meanings. Other providers' modes and workflows are rejected. `--max-tokens` optionally caps native SDK output; omission preserves provider defaults.

Receipts retain only visible text and terminal status. Success requires the owned session to finish, a completed terminal event and a nonempty visible answer. Prompt admission or idle notifications alone are insufficient. Verify the deliverable.

## Scope and lifecycle

- Continue with the recorded command, home, provider route, workspace, model and scope. Locks prevent concurrent helper turns. Native account management owns login identity; the SDK exposes no account fingerprint for an independent account pin.
- Tasks default to read-only instructions. `--sandbox workspace-write` authorizes edits in the task brief; these flags do not create an OS sandbox. Harness retains its application permissions. Use a suitable workspace and verify changes.
- Each call owns one SDK runtime. Timeout or cancellation requests its shutdown and checks its exit. Forced termination without confirmed cleanup is recorded as `unknown`. The adapter never stops the desktop application or another task's runtime.
- Supported operations are ordinary tasks and exact-session continuation. No native per-turn cancellation or cross-provider slash-command translation is claimed.

References: [Desktop CLI](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md#terminal-command), [SDK protocol](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md).
