---
name: agent-delegate
description: Delegate bounded tasks to Antigravity, a separate Codex profile, or DeepSeek Harness when requested, or when independent review, parallel work, or target capabilities justify delegation. Resume conversations and verify results.
license: MIT
---

# Agent Delegate

Decide whether delegation helps, select an appropriate target, and verify its result.

## Delegation decision

- Handle simple or tightly coupled work locally. Delegate self-contained work when independent verification, parallel progress, or a known target capability outweighs startup and coordination cost.
- Honor explicit provider, account, model, and delegation preferences. Otherwise, choose among registered targets using known capabilities, workspace access, and current availability; use provider checks instead of inferring capability from a model name.
- Stay within the user's authorized scope and budget. If no suitable target is available, continue locally when feasible; report the limitation when delegation is required.
- Keep coordination with the caller. Include caller/target context in the task brief; do not route work back along its delegation chain. Duplicate work only for deliberate independent checks, and retry failed delegation only when new evidence warrants it.

## Select the provider

- **Antigravity / Gemini:** [antigravity.md](references/antigravity.md).
- **Codex profile:** [codex.md](references/codex.md). Runs a separate app-server under the selected profile, without attaching to its desktop window.
- **DeepSeek Harness:** [deepseek.md](references/deepseek.md). Uses the installed SDK CLI and native login, with an owned runtime for each task.
- **First use:** register the target with [setup.md](references/setup.md), then reuse its mapping.
- **MCP available:** use its five task tools with [mcp.md](references/mcp.md); otherwise use the helper scripts below.

## Workflow

1. Define the authorized workspace, deliverable, permitted actions, and stopping condition.
2. Verify the target's identity and workspace using the provider's checks. Preserve the selected provider, account, and model.
3. Default to read-only work. For authorized edits, use disjoint files or an isolated worktree.
4. Save the conversation ID and receipt location. Continue with `send`; wait within the requested limit and require confirmed completion.
5. Retrieve the visible final answer, verify relevant calculations or changes, and report the result and material limitations.

Entry point: `scripts/invoke_agent.ps1`, or the provider helper directly.

Keep mappings and receipts local; leave authentication to the provider application.
