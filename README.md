# Agent Delegate

A local agent skill for delegating bounded tasks to Antigravity/Gemini or an independently authenticated Codex profile, continuing the same conversation, and checking the result.

## Capabilities

| Provider | Connection | Reusable local configuration |
| --- | --- | --- |
| Antigravity | Running Agent API; structured Plan, Grill-me, Boost, and Teamwork workflows | Workspace-to-project mapping |
| Codex | Separate `codex app-server`; native Plan, Review, Compact, and continuation | Named target with home path and account fingerprint |

Codex delegation uses the selected profile's account and creates an independent conversation. It does not attach to an existing desktop window. The Antigravity adapter currently requires Windows; its internal local API may change after app updates.

## Requirements

- A client supporting local agent skills.
- PowerShell 7 for the shared entry point and Antigravity adapter.
- Antigravity installed, running, and signed in for that provider.
- Python 3.10+ and Codex CLI with `app-server` for the Codex adapter. The Python helpers require no third-party packages.

## Install

Download and extract `agent-delegate.zip`, or copy this repository's contents into a directory named `agent-delegate`. Place that directory in `~/.agents/skills/` for user installation, or `.agents/skills/` inside a repository. A client with a different supported skill directory can use that location instead. See the [official skill documentation](https://learn.chatgpt.com/docs/build-skills).

Invoke the installed skill:

```text
$agent-delegate Use Antigravity to review these files without editing them, then verify the findings.
$agent-delegate Ask Codex target codex-b to investigate this issue in the specified workspace.
```

## Set up once, reuse afterward

Ask the calling agent to follow [references/setup.md](references/setup.md). It locates the selected target, verifies its identity/workspace, and registers nonsecret routing data locally. Future tasks reuse the mapping. Each task returns a conversation ID; preserve it and its receipt for follow-ups.

- `projects.json`: local Antigravity workspace routing.
- `codex-targets.json`: local Codex target names, home paths, and hashed account pins.
- `.agent-delegate/`: private task handles and runtime receipts.

These files are ignored and excluded from releases. Start from the empty example JSON files if a custom config location is needed; never put real configuration into the examples.

## Usage references

- [Antigravity models, dispatch, and common workflows](references/antigravity.md)
- [Codex execution, common commands, and continuation](references/codex.md)
- [First-run discovery and registration](references/setup.md)

The shared entry point is `scripts/invoke_agent.ps1`. The provider helpers can also be called directly. Tasks default to read-only scope; give explicit edit permissions and separate files/workspaces for write tasks.

Vendor applications and binaries are not bundled. This project is independent of OpenAI and Google.

## License

[MIT](LICENSE).
