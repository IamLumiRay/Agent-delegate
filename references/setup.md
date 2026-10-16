# First-run target setup

Perform this setup only for an unregistered target. Target configuration identifies the app/profile and workspace; a conversation ID identifies one task. Save the target once, then save each task's returned conversation ID for continuation.

Resolve `<skill>` to this skill's installed directory and choose the intended provider. Read routing metadata only; do not search credential stores or unrelated conversations.

Configure [local state and Git](#local-state-and-git) before storing mappings or task receipts.

## Antigravity

1. Start Antigravity, sign in, and open the intended workspace.
2. Run `doctor` from that workspace. The default launcher is under the current user's `.gemini/antigravity/bin`.
3. Obtain the project UUID from `ANTIGRAVITY_PROJECT_ID` in an Antigravity terminal or user-visible project metadata. If neither is available, request that one value from the user; do not recover it by scanning brain data or conversation history.
4. Register the UUID for the workspace:

```powershell
pwsh -File "<skill>/scripts/invoke_antigravity.ps1" -Action register -ProjectId "<project UUID>" -ProjectPath "<workspace>"
```

Registration writes only a local workspace-to-project mapping to ignored `projects.json`. Future calls read it automatically. Re-run `doctor`, then perform the no-op workspace handshake described in [antigravity.md](antigravity.md).

For a nondefault installation, record the nonsecret paths in the user's local environment settings:

| Variable | Purpose |
| --- | --- |
| `ANTIGRAVITY_HOME` | Directory containing `bin/agentapi.bat` |
| `ANTIGRAVITY_DATA_HOME` | Data root containing `brain` |
| `ANTIGRAVITY_DELEGATE_CONFIG` | Optional full path to the local project mapping |

Do not cache a service port or CSRF token; the helper discovers them at runtime. If multiple instances exist, confirm the workspace handshake rather than relying on process order.

## Codex

Use an existing, independently signed-in Codex home. Do not copy authentication from the caller or silently use its default home.

1. Run `discover`. It lists saved targets and optional Cockpit instance-routing metadata. If no intended target appears, use the existing home path supplied by the user; no Cockpit installation is required.
2. Run `doctor` for that home and retain the returned account fingerprint. If a different account is required, compare it with the caller's fingerprint.
3. Register the chosen home and the verified fingerprint:

```powershell
python "<skill>/scripts/invoke_codex.py" discover
python "<skill>/scripts/invoke_codex.py" doctor --codex-home "<B home>"
python "<skill>/scripts/invoke_codex.py" register --target codex-b --codex-home "<B home>" --expected-account "<fingerprint from doctor>"
```

Registration writes only the home path, account fingerprint, and optional explicit `--codex-bin` path to ignored `codex-targets.json`. It verifies the account again and refuses to replace a different existing pin. Future calls use `--target codex-b` without rediscovery.

Use `--targets-file` if the target registry must live outside the installed skill. Run `doctor --target codex-b` to recheck a saved target. If the intended account changes, review the local mapping or register a new name; do not silently update its pin.

For an inference check, start a read-only, no-tools nonce task, then resume its conversation from a fresh helper process and verify the returned nonce. Login/model-list success alone does not verify inference.

## Preserve task handles

- **Antigravity:** save the returned `conversationId`, workspace, and provider in an ignored local task record. Continue it with `send -ConversationId` and verify its metadata.
- **Codex:** keep the receipt directory and conversation ID. Receipts already retain the target home, fingerprint, workspace, and current turn status.

Keep these records under a private `.agent-delegate/` directory or another ignored location. Reuse a registered target across tasks; reuse a conversation only when continuing that task. Recheck changed routing or identity instead of rescanning all chats.

The release includes empty `*.example.json` templates. Real mappings, fingerprints, receipts, and conversation IDs stay local.

## Local state and Git

The skill's `.gitignore` applies only inside its installed directory. For receipts stored at `<workspace>/.agent-delegate/`, add this rule to the workspace repository's `.gitignore` or its local `.git/info/exclude` before the first task:

```gitignore
/.agent-delegate/
```

For a custom state directory or mappings outside the skill, exclude their actual paths in each containing repository, or keep them outside Git repositories. This also applies to MCP's `--state-dir`.

Verify a receipt's relative path with `git -C "<workspace>" check-ignore --no-index -- "<receipt-relative-path>"`; it must print that path. Ignore rules do not protect already tracked files: `git -C "<workspace>" ls-files -- ".agent-delegate/"` must be empty. Check the corresponding paths when using custom storage.
