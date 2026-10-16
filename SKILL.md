---
name: agent-delegate
description: Delegate bounded tasks to Antigravity/Gemini or a separately authenticated Codex profile, resume its conversation, and verify the result. Use for external agent delegation or Codex A calling Codex B.
license: MIT
---

# Agent Delegate

Delegate to the requested provider and account; verify the returned result.

## Select the provider

- **Antigravity / Gemini:** [antigravity.md](references/antigravity.md).
- **Codex profile:** [codex.md](references/codex.md). Runs a separate app-server under the selected profile, without attaching to its desktop window.
- **First use:** register the target with [setup.md](references/setup.md), then reuse its mapping.

## Workflow

1. Define the authorized workspace, deliverable, permitted actions, and stopping condition.
2. Verify the target's identity and workspace using the provider's checks. Preserve the selected provider, account, and model.
3. Default to read-only work. For authorized edits, use disjoint files or an isolated worktree.
4. Save the conversation ID and receipt location. Continue with `send`; wait within the requested limit and require confirmed completion.
5. Retrieve the visible final answer, verify relevant calculations or changes, and report the result and material limitations.

Entry point: `scripts/invoke_agent.ps1`, or the provider helper directly.

Keep mappings and receipts local; leave authentication to the provider application.
