# Agent Delegate

**Let your agent call another agent through a skill.**

Delegate work to Antigravity, a separately signed-in Codex profile, DeepSeek Harness, or Claude Code using the local tools you already have. Install the skill, register a target once, and ask in natural language. No microservices, Docker deployment, or separate orchestration gateway are required.

The calling agent can decide whether delegation helps, send a task, continue the same conversation, retrieve the answer, and verify the result. When no target is specified, it can choose a suitable registered target within your instructions. Local target mappings are reused across tasks.

## Quick start

1. On GitHub, select **Code → Download ZIP** and extract the archive, or clone this repository. Rename the resulting directory to `agent-delegate`.
2. Place that directory in `~/.agents/skills/` for user installation, or `.agents/skills/` inside a repository. Use your client's supported skill directory if it differs.
3. Ask your agent to perform the [one-time target setup](references/setup.md), then delegate a task:

```text
$agent-delegate Set up Antigravity for this workspace using the setup guide.
$agent-delegate Ask Antigravity to review these files without editing them, then verify its findings.
$agent-delegate Ask Codex target codex-b to plan this change.
$agent-delegate Ask DeepSeek Harness target deepseek-main to independently check this result.
$agent-delegate Ask Claude target claude-main to independently review these files.
$agent-delegate Decide whether this task would benefit from an independent review; if so, choose a suitable registered target and verify its findings.
```

For a follow-up, ask the calling agent to continue the same task; it reuses the saved conversation ID and receipt.

## Optional MCP

For clients supporting MCP, the same adapters are available through five structured tools: `list_agents`, `delegate_task`, `get_task`, `continue_task`, and `cancel_task`. Install the optional MCP SDK and add one local stdio entry; see [MCP setup](references/mcp.md). Tasks return an ID immediately for progress checks and continuation.

The skill remains usable on its own. MCP provides the tool interface; the calling agent decides when delegation is useful and verifies the outcome.

## What needs to be running?

| Target | Before delegation | How it connects |
| --- | --- | --- |
| Antigravity | Keep Antigravity running, signed in, with the intended workspace open. | Uses the app's existing local Agent API. |
| Codex | Install Codex CLI and prepare a separately signed-in Codex home. The target desktop window can stay closed. | Starts its own `codex app-server` process under that profile and closes it after the call. |
| DeepSeek Harness | Install its SDK CLI and sign in through the selected Harness home. Its desktop window can stay closed. | Starts an owned `dsh sdk` process using native authentication. |
| Claude Code | Install and sign in to Claude CLI. No desktop window is required. | Starts an owned restricted `claude -p` process and resumes by exact session ID. |

Each target needs a one-time local registration. Codex tasks run in independent conversations under the selected profile; this does not control an existing desktop chat. See [Codex app-server documentation](https://learn.chatgpt.com/docs/app-server) for the underlying protocol.

## Supported workflows

Ordinary delegation needs no special command. For a specific workflow:

- **Antigravity:** Plan, Grill-me, Boost, and Teamwork scoping. See [Antigravity usage](references/antigravity.md).
- **Codex:** Plan, Review, Compact, and conversation continuation. See [Codex usage](references/codex.md).
- **DeepSeek Harness:** Ordinary tasks and conversation continuation. See [DeepSeek usage](references/deepseek.md).
- **Claude Code:** File review, explicitly authorized file edits and conversation continuation. See [Claude usage](references/claude.md).

The helper translates supported commands to provider operations. Teamwork starts with scoping; verify its later execution separately.

## Requirements and limits

- A local agent client that can load skills and run helper scripts.
- PowerShell 7 for the shared entry point and Antigravity adapter. The Antigravity adapter currently requires Windows.
- Python 3.10+ and Codex CLI with `app-server` for Codex delegation. No third-party Python packages are required.
- Python 3.10+ and DeepSeek Harness with its SDK CLI for DeepSeek delegation. No third-party Python packages or separate service are required.
- Python 3.10+ and a signed-in Claude CLI supporting safe mode, restricted mode and noninteractive permission denial for Claude delegation.
- The optional MCP entry requires the official Python MCP SDK in `requirements-mcp.txt`.
- Tasks default to read-only scope. Authorize edits explicitly; use an interactive client when provider approval or user input is needed.

Authentication remains with the provider. Keep target mappings (`projects.json`, `codex-targets.json`, `deepseek-targets.json`, `claude-targets.json`) and task receipts (`.agent-delegate/`) local. Configure [ignore rules in each repository that stores them](references/setup.md#local-state-and-git); the skill's own `.gitignore` does not cover state elsewhere in the workspace. App/API changes may require adapter updates.

Vendor applications and binaries are not bundled. This project is independent of OpenAI and Google.

## License

[MIT](LICENSE).
