"""Delegate through the installed DeepSeek Harness SDK CLI. Python stdlib only."""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid

import invoke_codex as common


def launch_spec(cli, home):
    cli = Path(cli).expanduser().resolve()
    if not cli.is_file() or not home.is_dir():
        raise common.DelegateError('Select an existing dsh command and DSH home.')
    env = os.environ.copy()
    env['DSH_HOME'] = str(home)
    if os.name == 'nt' and cli.suffix.lower() in ('.cmd', '.bat'):
        # Use the official Desktop carrier directly, without a command shell.
        root = cli.parents[4] if len(cli.parents) > 4 else cli.parent
        binary = root/'DeepSeek Harness.exe'
        archive = root/'resources/app.asar'
        if cli != root/'resources/runtime/cli/bin/dsh.cmd' or not binary.is_file() or not archive.is_file():
            raise common.DelegateError('On Windows select Desktop resources/runtime/cli/bin/dsh.cmd or a native dsh executable.')
        env['ELECTRON_RUN_AS_NODE'] = '1'
        entry = archive/'dsh/node_modules/@deepseek-ai/dsh-desktop-host/lib/cli.js'
        return [str(binary), '--expose-internals', str(entry), 'sdk'], env
    return [str(cli), 'sdk'], env


class Client:
    def __init__(self, cli, home, cwd, notify=None):
        command, env = launch_spec(cli, home)
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.queue = queue.Queue()
        self.sequence = 0
        self.notify = notify
        self.stopped = None
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    self.queue.put(value)
        finally:
            self.queue.put(None)

    def rpc(self, method, params=None, timeout=30, cancelled=None):
        self.sequence += 1
        identity = self.sequence
        request = {'jsonrpc': '2.0', 'id': identity, 'method': method}
        if params is not None:
            request['params'] = params
        self.process.stdin.write(json.dumps(request, ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        deadline = time.monotonic()+timeout
        while True:
            if cancelled and cancelled():
                raise common.DelegateCancelled('Task cancellation requested.')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('DeepSeek Harness response deadline exceeded.')
            try:
                value = self.queue.get(timeout=min(.5, remaining))
            except queue.Empty:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError('DeepSeek Harness response deadline exceeded.')
            if cancelled and cancelled():
                raise common.DelegateCancelled('Task cancellation requested.')
            if value is None:
                raise common.DelegateError('DeepSeek Harness exited before completing the request.')
            if 'id' in value and 'method' in value:
                raise common.DelegateError('DeepSeek Harness requires an interactive client; no approval was supplied.')
            if value.get('id') == identity:
                if value.get('error'):
                    # Native errors can contain private paths, arguments or credentials.
                    raise common.DelegateError(method+' failed; check the selected home, login, model and application diagnostics.')
                return value.get('result') or {}
            if self.notify and 'method' in value:
                self.notify(value)

    def close(self):
        if self.stopped is not None:
            return self.stopped
        acknowledged = False
        try:
            self.rpc('shutdown', timeout=5)
            acknowledged = True
        except Exception:
            pass
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.stopped = acknowledged and self.process.returncode == 0
        return self.stopped


def state_path(directory, session_id):
    if not isinstance(session_id, str) or not session_id.startswith('session-'):
        raise common.DelegateError('Conversation ID must be the returned session handle.')
    return common.state_path(directory, session_id[len('session-'):])


def load_record(args):
    path = state_path(args.state_dir, args.conversation_id)
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('provider') != 'deepseek' or record.get('conversation_id') != args.conversation_id:
        raise common.DelegateError('Invalid DeepSeek Harness receipt.')
    return path, record


def public_record(record, content=True):
    result = {key: record.get(key) for key in ('provider', 'conversation_id', 'status',
        'cwd', 'model', 'provider_route', 'sandbox', 'turn_count')}
    if content:
        result['content'] = record.get('content')
    return result


def resolve_target(args):
    if args.target:
        data = json.loads(args.targets_file.read_text(encoding='utf-8'))
        target = data.get('targets', {}).get(args.target)
        if not target:
            raise common.DelegateError('Unknown DeepSeek target; register it first.')
        if args.dsh_bin or args.dsh_home or args.provider_route:
            raise common.DelegateError('Use a registered target or explicit routing options, not both.')
        args.dsh_bin = Path(target['dsh_bin'])
        args.dsh_home = Path(target['dsh_home'])
        args.provider_route = target['provider_route']
        args.model = args.model or target['model']
    args.dsh_bin = Path(args.dsh_bin or shutil.which('dsh') or '')
    args.dsh_home = Path(args.dsh_home or os.environ.get('DSH_HOME') or Path.home()/'.dsh').expanduser().resolve()
    args.dsh_bin = args.dsh_bin.expanduser().resolve()
    args.provider_route = args.provider_route or 'deepseek-account'
    if not args.model:
        raise common.DelegateError('Select an available exact --model during setup, or use a registered target.')


def run(args, notify=common.emit, cancelled=None):
    if args.action == 'discover':
        targets = json.loads(args.targets_file.read_text(encoding='utf-8')).get('targets', {}) if args.targets_file.exists() else {}
        notify({'provider': 'deepseek', 'command_on_path': shutil.which('dsh'), 'registered_targets': list(targets)})
        return
    if args.action in ('metadata', 'result'):
        _, record = load_record(args)
        if args.action == 'result' and (record.get('status') != 'completed' or not record.get('content')):
            raise common.DelegateError('No successfully completed DeepSeek result.')
        notify(public_record(record, args.action == 'result'))
        return
    registering = args.action == 'register'
    target_name = args.target
    if registering:
        if not target_name or not args.dsh_bin:
            raise common.DelegateError('register requires --target, --dsh-bin and --model.')
        args.target = None
    resolve_target(args)
    workspace = (args.cwd or Path.cwd()).resolve()
    if not workspace.is_dir():
        raise common.DelegateError('An existing explicit workspace is required.')
    record = path = lock = client = None
    started = finished = False
    captured = {'content': None, 'reason': None}

    def receive(value):
        params = value.get('params') or {}
        if not started or finished or value.get('method') != 'session.event' or params.get('sessionId') != record['conversation_id']:
            return
        event = params.get('event') or {}
        data = event.get('data') or {}
        if event.get('type') == 'assistant/message':
            text = ''.join(block.get('text', '') for block in data.get('message', {}).get('content', []) if block.get('type') == 'text')
            if text:
                captured['content'] = text
        elif event.get('type') == 'turn/end':
            captured['reason'] = (data.get('reason') or {}).get('kind')

    try:
        if args.action == 'send':
            path, previous = load_record(args)
            record = dict(previous)
            for key, value in (('dsh_bin', str(args.dsh_bin)), ('dsh_home', str(args.dsh_home)),
                               ('provider_route', args.provider_route), ('model', args.model), ('sandbox', args.sandbox)):
                if record.get(key) != value:
                    raise common.DelegateError('Continuation must preserve the recorded home, command, route, model and scope.')
            if args.cwd and str(workspace) != record['cwd']:
                raise common.DelegateError('Continuation cannot change workspace.')
            if record.get('status') not in ('completed', 'cancelled', 'timed_out'):
                raise common.DelegateError('Only a confirmed stopped conversation can be continued.')
            workspace = Path(record['cwd'])
        elif args.action == 'new':
            if not args.cwd:
                raise common.DelegateError('new requires an existing explicit --cwd.')
            session_id = 'session-'+str(uuid.uuid4())
            path = state_path(args.state_dir, session_id)
            record = {'provider': 'deepseek', 'conversation_id': session_id, 'cwd': str(workspace),
                'dsh_bin': str(args.dsh_bin), 'dsh_home': str(args.dsh_home),
                'provider_route': args.provider_route, 'model': args.model,
                'sandbox': args.sandbox, 'turn_count': 0}
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = path.with_suffix('.lock').open('x', encoding='utf-8')
            lock.write(str(os.getpid())); lock.flush()
        client = Client(args.dsh_bin, args.dsh_home, workspace, receive)
        init = {'cwd': str(workspace), 'provider': args.provider_route, 'model': args.model}
        if args.effort:
            init['reasoningEffort'] = args.effort
        if args.max_tokens is not None:
            init['maxTokens'] = args.max_tokens
        identity = client.rpc('initialize', init, cancelled=cancelled)
        if identity.get('serverInfo', {}).get('name') != 'deepseek-harness-sdk-runtime':
            raise common.DelegateError('Unexpected runtime identity.')
        if args.action == 'doctor':
            notify({'provider': 'deepseek', 'available': True, 'model': args.model,
                    'provider_route': args.provider_route, 'inference_checked': False})
            return
        if registering:
            data = json.loads(args.targets_file.read_text(encoding='utf-8')) if args.targets_file.exists() else {'targets': {}}
            target = {'dsh_bin': str(args.dsh_bin), 'dsh_home': str(args.dsh_home),
                      'provider_route': args.provider_route, 'model': args.model}
            if target_name in data.get('targets', {}) and data['targets'][target_name] != target:
                raise common.DelegateError('Target name already has different routing; review it or use a new name.')
            data.setdefault('targets', {})[target_name] = target
            common.write_json(args.targets_file, data)
            notify({'provider': 'deepseek', 'registered': True, 'target': target_name})
            return
        if args.action == 'send':
            client.rpc('session/resume', {'sessionId': record['conversation_id']}, cancelled=cancelled)
        actual = client.rpc('session/working-directory/get', {'sessionId': record['conversation_id']}, cancelled=cancelled)
        if Path(actual['cwd']).resolve() != workspace:
            raise common.DelegateError('Runtime returned a different workspace; no prompt was sent.')
        prompt = args.prompt_file.read_text(encoding='utf-8') if args.prompt_file else args.prompt
        if not isinstance(prompt, str) or not prompt.strip():
            raise common.DelegateError('A nonempty prompt or UTF-8 prompt file is required.')
        prompt += ('\n\nDelegation scope: '+('Edits are authorized only in this workspace.' if args.sandbox == 'workspace-write' else
            'Read-only task. Do not modify workspace files.')+' Return the result to the caller. Do not delegate back to the caller.')
        started = True
        record.update(status='running', content=None, error_type=None)
        common.write_json(path, record)
        notify({'event': 'dispatched', **public_record(record, False)})
        deadline = time.monotonic()+args.timeout
        client.rpc('session/prompt', {'sessionId': record['conversation_id'],
            'contentBlocks': [{'type': 'text', 'text': prompt}]}, timeout=max(.001, deadline-time.monotonic()), cancelled=cancelled)
        client.rpc('session/wait', {'sessionId': record['conversation_id']},
                   timeout=max(.001, deadline-time.monotonic()), cancelled=cancelled)
        if time.monotonic() >= deadline:
            raise TimeoutError('DeepSeek Harness response deadline exceeded.')
        if captured['reason'] != 'completed' or not captured['content']:
            raise common.DelegateError('DeepSeek ended without a completed visible answer; inspect the native application diagnostics.')
        record.update(status='completed', content=captured['content'], turn_count=record['turn_count']+1)
        common.write_json(path, record)
        finished = True
        notify({'event': 'completed', **public_record(record)})
    except BaseException as error:
        if started and not finished:
            stopped = client.close() if client else False
            status = ('cancelled' if isinstance(error, common.DelegateCancelled) else 'timed_out' if isinstance(error, TimeoutError) else 'failed')
            record.update(status=status if stopped else 'unknown', content=None, interruption_confirmed=stopped,
                          error_type=type(error).__name__)
            common.write_json(path, record)
        raise
    finally:
        if client:
            client.close()
        if lock:
            lock.close()
            path.with_suffix('.lock').unlink(missing_ok=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('action', choices=('discover', 'doctor', 'register', 'new', 'send', 'metadata', 'result'))
    result.add_argument('--target')
    result.add_argument('--targets-file', type=Path, default=Path(__file__).resolve().parents[1]/'deepseek-targets.json')
    result.add_argument('--dsh-bin', type=Path)
    result.add_argument('--dsh-home', type=Path)
    result.add_argument('--provider-route', choices=('deepseek-account', 'deepseek-official'))
    result.add_argument('--model')
    result.add_argument('--effort')
    result.add_argument('--max-tokens', type=int)
    result.add_argument('--cwd', type=Path)
    result.add_argument('--prompt')
    result.add_argument('--prompt-file', type=Path)
    result.add_argument('--conversation-id')
    result.add_argument('--state-dir', type=Path, default=Path.cwd()/'.agent-delegate/deepseek')
    result.add_argument('--sandbox', choices=('read-only', 'workspace-write'), default='read-only')
    result.add_argument('--timeout', type=int, default=1200)
    return result


def main():
    args = parser().parse_args()
    try:
        if not 1 <= args.timeout <= 1200 or (args.max_tokens is not None and args.max_tokens <= 0):
            raise common.DelegateError('Timeout must be 1..1200 and max-tokens must be positive.')
        if args.prompt and args.prompt_file:
            raise common.DelegateError('Use prompt or prompt-file, not both.')
        run(args)
    except (Exception, KeyboardInterrupt) as error:
        common.emit({'provider': 'deepseek', 'error_type': type(error).__name__,
                     'error': 'Delegation failed; inspect the private receipt and native application configuration.'})
        raise SystemExit(1)


if __name__ == '__main__':
    main()
