# Optional local MCP

The stdio server exposes the same adapters as the standalone skill. It starts as a local process; no HTTP listener, Docker deployment, or separate orchestration service is needed.

## Install and connect

Use Python 3.10+ and install the optional SDK into your chosen Python environment:

```powershell
python -m pip install -r "<skill>/requirements-mcp.txt"
```

Register targets once with [setup.md](setup.md). The MCP tools reuse `codex-targets.json`, `deepseek-targets.json`, `claude-targets.json` and `projects.json` beside `SKILL.md`. They do not change login accounts or register targets implicitly.

For a client using `mcpServers` JSON configuration, replace the placeholders with absolute paths:

```json
{
  "mcpServers": {
    "agent-delegate": {
      "command": "<absolute-python-executable>",
      "args": [
        "-B", "<skill>/scripts/mcp_server.py",
        "--state-dir", "<private-task-directory>"
      ]
    }
  }
}
```

For Codex CLI:

```powershell
codex mcp add agent-delegate -- "<absolute-python-executable>" -B "<skill>/scripts/mcp_server.py" --state-dir "<private-task-directory>"
```

Optional server arguments `--codex-targets-file`, `--deepseek-targets-file`, `--claude-targets-file` and `--projects-file` reuse mappings outside the installed directory. Use a private state directory; each directory has one server owner. Keep that directory stable to retrieve past results after a restart. Prefer storage outside Git repositories; otherwise configure the containing repository's [state ignore rules](setup.md#local-state-and-git).

Claude inference needs the same local network environment as a working direct CLI call. If the MCP client filters process environment variables, configure only the required local values in that client; do not publish them or store them in target registries.

## Tools

| Tool | Purpose |
| --- | --- |
| `list_agents` | List registered targets/workspaces; `check_health=true` verifies local routing and account checks. |
| `delegate_task` | Submit a task and return its ID immediately. Select `provider`, absolute `workspace`, and `prompt`; Codex, DeepSeek and Claude also need `target`. |
| `get_task` | Read a task's state and visible result. |
| `continue_task` | Continue the same conversation, preserving account, workspace, model and permissions. |
| `cancel_task` | Request cancellation of a task created by this server. Poll for confirmation. |

Codex supports `mode=default|plan|review`, plus `mode=compact` on continuation. Antigravity supports `workflow=plan|grill-me|boost|teamwork-preview`. DeepSeek and Claude support ordinary tasks and continuation, without `mode` or `workflow`. Omit `model` to preserve the registered/provider default. Antigravity Argon selection still requires a verified selector through the standalone helper; this MCP entry does not guess one.

`timeout_seconds` is 1–1200. `allow_writes` defaults to false; set it only for authorized edits. Codex enforces its sandbox. Antigravity and DeepSeek receive the task scope and use their application's existing permissions; a read-only instruction is not an OS sandbox. Provider approval or interview questions must be handled by the caller/user, not fabricated by this server.

## Task lifecycle

Claude runs with native restricted file tools: read-only by default, with Edit/Write added only when `allow_writes=true`. Shell execution, subagents and external MCP tools are excluded.

Submit, poll at reasonable intervals, inspect the deliverable, and continue only when useful. `queued`, `running`, and `cancelling` are pending states. A `completed` provider turn still requires checking whether the requested work was achieved, especially for Teamwork scoping or an interview question.

Cancellation targets only the task's Codex turn, Antigravity conversation tree, or owned DeepSeek SDK runtime. `cancelling` is an acknowledgement; `cancelled` requires a confirmed stop. Normal client disconnect requests cancellation of active work. A client may forcibly terminate its server before cleanup finishes; Antigravity runs in an external app and can then remain active. Unfinished receipts become `unknown` on restart; inspect the provider before starting overlapping work. Completed results remain readable. Claude cancellation/timeout stops only its owned print process; forced termination is recorded as `unknown` without a native completion acknowledgement. MCP adds no background daemon.

References: [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp), [skills and MCP](https://developers.openai.com/plugins/concepts/skills).
