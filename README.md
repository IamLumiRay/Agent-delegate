# Agent Delegate

**Let your agent call another agent through a skill.**

Delegate work to Antigravity or a separately signed-in Codex profile using the local tools you already have. Install the skill, register a target once, and ask in natural language. No microservices, Docker deployment, or separate orchestration gateway are required.

The calling agent can send a task, continue the same conversation, retrieve the answer, and verify the result. Local target mappings are reused across tasks.

## Quick start

1. Download and extract `agent-delegate.zip`, or copy this repository's contents into a directory named `agent-delegate`.
2. Place that directory in `~/.agents/skills/` for user installation, or `.agents/skills/` inside a repository. Use your client's supported skill directory if it differs.
3. Ask your agent to perform the [one-time target setup](references/setup.md), then delegate a task:

```text
$agent-delegate Set up Antigravity for this workspace using the setup guide.
$agent-delegate Ask Antigravity to review these files without editing them, then verify its findings.
$agent-delegate Ask Codex target codex-b to plan this change.
```

For a follow-up, ask the calling agent to continue the same task; it reuses the saved conversation ID and receipt.

## What needs to be running?

| Target | Before delegation | How it connects |
| --- | --- | --- |
| Antigravity | Keep Antigravity running, signed in, with the intended workspace open. | Uses the app's existing local Agent API. |
| Codex | Install Codex CLI and prepare a separately signed-in Codex home. The target desktop window can stay closed. | Starts its own `codex app-server` process under that profile and closes it after the call. |

Each target needs a one-time local registration. Codex tasks run in independent conversations under the selected profile; this does not control an existing desktop chat. See [Codex app-server documentation](https://learn.chatgpt.com/docs/app-server) for the underlying protocol.

## Supported workflows

Ordinary delegation needs no special command. For a specific workflow:

- **Antigravity:** Plan, Grill-me, Boost, and Teamwork scoping. See [Antigravity usage](references/antigravity.md).
- **Codex:** Plan, Review, Compact, and conversation continuation. See [Codex usage](references/codex.md).

The helper translates supported commands to provider operations. Teamwork starts with scoping; verify its later execution separately.

## Requirements and limits

- A local agent client that can load skills and run helper scripts.
- PowerShell 7 for the shared entry point and Antigravity adapter. The Antigravity adapter currently requires Windows.
- Python 3.10+ and Codex CLI with `app-server` for Codex delegation. No third-party Python packages are required.
- Tasks default to read-only scope. Authorize edits explicitly; use an interactive client when provider approval or user input is needed.

Target mappings (`projects.json`, `codex-targets.json`) and task receipts (`.agent-delegate/`) stay local and are ignored by Git. Authentication remains with the provider. App/API changes may require adapter updates.

Vendor applications and binaries are not bundled. This project is independent of OpenAI and Google.

## License

[MIT](LICENSE).
