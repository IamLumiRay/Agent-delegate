"""Optional local stdio MCP entry point for Agent Delegate."""
import argparse
from pathlib import Path
from typing import Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from delegate_tasks import TaskManager


def create_server(manager):
    server=FastMCP('agent-delegate',instructions=(
        'Delegate bounded independent work when it benefits the user. Honor explicit target, model and edit permissions. '
        'Use registered targets, poll task IDs, verify returned results, and avoid delegation cycles. '
        'A completed turn is not proof that a broader workflow achieved its goal.'),log_level='WARNING')

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True),structured_output=True)
    async def list_agents(check_health: bool=False) -> dict[str, Any]:
        """List registered Codex, DeepSeek and Claude targets plus Antigravity workspaces. Health checks use native authentication."""
        return await anyio.to_thread.run_sync(lambda:manager.list_agents(check_health))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False),structured_output=True)
    async def delegate_task(provider: Literal['codex','antigravity','deepseek','claude'], workspace: str, prompt: str,
        target: str|None=None, model: str|None=None,
        mode: Literal['default','plan','review']|None=None,
        workflow: Literal['plan','grill-me','boost','teamwork-preview']|None=None,
        allow_writes: bool=False, timeout_seconds: int=1200) -> dict[str, Any]:
        """Start an authorized bounded task and return a task ID. Codex, DeepSeek and Claude require registered targets; Antigravity uses its workspace mapping. Set allow_writes only for authorized edits. Model defaults stay with the selected provider."""
        return manager.start(provider,workspace,prompt,target,model,mode,workflow,allow_writes,timeout_seconds)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True),structured_output=True)
    async def get_task(task_id: str) -> dict[str, Any]:
        """Get this server's task status and visible final result. queued/running/cancelling are pending; unknown needs provider inspection. Verify the deliverable even when completed."""
        return manager.view(manager.get(task_id))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False),structured_output=True)
    async def continue_task(task_id: str, prompt: str,
        mode: Literal['default','plan','review','compact']|None=None,
        workflow: Literal['plan','grill-me','boost','teamwork-preview']|None=None,
        timeout_seconds: int=1200) -> dict[str, Any]:
        """Continue a confirmed stopped task in the same provider/account/workspace and permission scope. Use Codex mode=compact to reduce history; prompt then describes the intent but is not sent as a user turn."""
        return manager.continue_task(task_id,prompt,mode,workflow,timeout_seconds)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False),structured_output=True)
    async def cancel_task(task_id: str) -> dict[str, Any]:
        """Request cancellation of this server's task only. Poll until cancelled or another terminal state; cancelling is not a stop confirmation."""
        return manager.cancel(task_id)

    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',required=True,type=Path,help='Private persistent task directory; one server per directory.')
    parser.add_argument('--codex-targets-file',type=Path)
    parser.add_argument('--projects-file',type=Path)
    parser.add_argument('--deepseek-targets-file',type=Path)
    parser.add_argument('--claude-targets-file',type=Path)
    args=parser.parse_args()
    manager=TaskManager(Path(__file__).resolve().parents[1],args.state_dir,args.codex_targets_file,args.projects_file,args.deepseek_targets_file,args.claude_targets_file)
    try:
        create_server(manager).run(transport='stdio')
    finally:
        manager.close()


if __name__=='__main__':
    main()
