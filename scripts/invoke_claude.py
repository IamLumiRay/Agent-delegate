"""Bounded Claude Code print-mode delegation using its native authentication."""
import argparse
import hashlib
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

REQUIRED = ('--safe-mode', '--restricted', '--permission-prompts', '--strict-mcp-config')


def native_binary(value=None):
    value = value or shutil.which('claude')
    if not value:
        raise common.DelegateError('Select an installed Claude CLI with --claude-bin.')
    path = Path(value).expanduser().resolve()
    if os.name == 'nt' and path.suffix.lower() in ('.cmd', '.ps1'):
        path = path.parent/'node_modules/@anthropic-ai/claude-code/bin/claude.exe'
    if not path.is_file():
        raise common.DelegateError('Select a native Claude executable or its official npm wrapper.')
    return path


def environment(home):
    env = os.environ.copy()
    if home:
        env['CLAUDE_CONFIG_DIR'] = str(home)
    env['CLAUDE_CODE_DISABLE_BACKGROUND_TASKS'] = '1'
    return env


def check_ready(binary, home=None):
    env = environment(home)
    status = subprocess.run([str(binary), 'auth', 'status'], env=env, capture_output=True,
        text=True, encoding='utf-8', timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        info = json.loads(status.stdout)
    except ValueError:
        raise common.DelegateError('Claude authentication status could not be verified.') from None
    if status.returncode or info.get('loggedIn') is not True or not info.get('configDirectory'):
        raise common.DelegateError('Sign in using the selected Claude CLI before delegation.')
    help_result = subprocess.run([str(binary), '--help'], env=env, capture_output=True,
        text=True, encoding='utf-8', timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if help_result.returncode or any(flag not in help_result.stdout for flag in REQUIRED):
        raise common.DelegateError('This Claude CLI lacks the required safe/restricted print-mode options.')
    metadata = {key: info.get(key) for key in ('authMethod', 'apiProvider', 'email', 'orgId', 'organizationId')}
    pin = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:16]
    return {'claude_bin': str(binary), 'claude_home': str(Path(info['configDirectory']).resolve()),
            'identity_fingerprint': pin}


class PrintClient:
    def __init__(self):
        self.process = None

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)

    def run(self, command, env, workspace, prompt, timeout, cancelled, observe):
        self.process = subprocess.Popen(command, env=env, cwd=workspace, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        events = queue.Queue()

        def read():
            try:
                for line in self.process.stdout:
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(value, dict):
                        continue
                    if value.get('type') == 'system' and value.get('subtype') == 'init':
                        events.put({key: value.get(key) for key in ('type', 'session_id', 'cwd', 'model')})
                    elif value.get('type') == 'result':
                        events.put({'type': 'result', 'session_id': value.get('session_id'),
                            'subtype': value.get('subtype'), 'is_error': value.get('is_error'),
                            'permission_denials': len(value.get('permission_denials') or []),
                            'content': value.get('result') if value.get('is_error') is False else None})
            finally:
                events.put(None)

        threading.Thread(target=read, daemon=True).start()
        self.process.stdin.write(prompt)
        self.process.stdin.close()
        deadline = time.monotonic()+timeout
        result = None
        while True:
            if cancelled and cancelled():
                raise common.DelegateCancelled('Claude cancellation requested.')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Claude response deadline exceeded.')
            try:
                event = events.get(timeout=min(.25, remaining))
            except queue.Empty:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError('Claude response deadline exceeded.')
            if event is None:
                break
            observe(event)
            if event['type'] == 'result':
                result = event
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Claude response deadline exceeded.')
        try:
            code = self.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise TimeoutError('Claude response deadline exceeded.') from None
        if code or not result or result.get('subtype') != 'success' or result.get('is_error') is not False or result.get('permission_denials'):
            raise common.DelegateError('Claude did not complete successfully; check native login, permissions and diagnostics.')
        if not isinstance(result.get('content'), str) or not result['content'].strip():
            raise common.DelegateError('Claude completed without a visible answer.')
        return result


def load_record(args):
    path = common.state_path(args.state_dir, args.conversation_id)
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('provider') != 'claude' or record.get('conversation_id') != path.stem:
        raise common.DelegateError('Invalid Claude delegation receipt.')
    return path, record


def public_record(record, content=True):
    value = {key: record.get(key) for key in ('provider', 'conversation_id', 'status', 'cwd', 'model', 'sandbox', 'turn_count')}
    if content:
        value['content'] = record.get('content')
    return value


def run(args, notify=common.emit, cancelled=None):
    if args.action == 'discover':
        data = json.loads(args.targets_file.read_text(encoding='utf-8')) if args.targets_file.exists() else {}
        notify({'provider': 'claude', 'command_on_path': shutil.which('claude'), 'registered_targets': list(data.get('targets', {}))})
        return
    if args.action in ('metadata', 'result'):
        _, record = load_record(args)
        if args.action == 'result' and (record.get('status') != 'completed' or not record.get('content')):
            raise common.DelegateError('No successfully completed Claude result.')
        notify(public_record(record, args.action == 'result'))
        return
    target = None
    registering = args.action == 'register'
    explicit_model = args.model
    if args.target and not registering:
        target = json.loads(args.targets_file.read_text(encoding='utf-8')).get('targets', {}).get(args.target)
        if not target:
            raise common.DelegateError('Unknown Claude target; register it first.')
        if args.claude_bin or args.claude_home:
            raise common.DelegateError('Use a registered target or explicit runtime options, not both.')
        args.claude_bin = Path(target['claude_bin'])
        args.claude_home = Path(target['home_override']) if target.get('home_override') else None
        args.model = args.model or target.get('model')
    binary = native_binary(args.claude_bin)
    home = args.claude_home.expanduser().resolve() if args.claude_home else None
    home_override = str(home) if home else os.environ.get('CLAUDE_CONFIG_DIR')
    path = record = lock = client = None
    owned = completed = seen_init = False
    try:
        if args.action == 'send':
            path, old = load_record(args)
            record = dict(old)
            if record.get('status') != 'completed':
                raise common.DelegateError('Only a completed Claude conversation can be continued by this helper.')
            if record['sandbox'] != args.sandbox or (args.cwd and args.cwd.resolve() != Path(record['cwd'])):
                raise common.DelegateError('Continuation must preserve workspace and scope.')
            if explicit_model and explicit_model != record['model']:
                raise common.DelegateError('Continuation must preserve the recorded exact model.')
            args.model = record['model']
        ready = check_ready(binary, home)
        if target and any(ready[key] != target[key] for key in ('claude_bin', 'claude_home', 'identity_fingerprint')):
            raise common.DelegateError('Claude target authentication or routing changed; no task was sent.')
        if args.action == 'doctor':
            notify({'provider': 'claude', 'available': True, 'inference_checked': False, **ready})
            return
        if registering:
            if not args.target:
                raise common.DelegateError('register requires a target name.')
            config = json.loads(args.targets_file.read_text(encoding='utf-8')) if args.targets_file.exists() else {'targets': {}}
            entry = {**ready, 'home_override': home_override, 'model': args.model}
            existing = config.setdefault('targets', {}).get(args.target)
            if existing and existing != entry:
                raise common.DelegateError('Target already has different routing; review it or use another name.')
            config['targets'][args.target] = entry
            common.write_json(args.targets_file, config)
            notify({'provider': 'claude', 'registered': True, 'target': args.target})
            return
        prompt = args.prompt_file.read_text(encoding='utf-8') if args.prompt_file else args.prompt
        if not isinstance(prompt, str) or not prompt.strip():
            raise common.DelegateError('A nonempty prompt or UTF-8 prompt file is required.')
        if record:
            if any(record[key] != ready[key] for key in ready) or record.get('home_override') != home_override:
                raise common.DelegateError('Continuation must preserve the recorded CLI home and authentication.')
            workspace = Path(record['cwd'])
        else:
            if not args.cwd or not args.cwd.is_dir():
                raise common.DelegateError('new requires an existing explicit --cwd.')
            workspace = args.cwd.resolve()
            session = str(uuid.uuid4())
            path = common.state_path(args.state_dir, session)
            record = {'provider': 'claude', 'conversation_id': session, 'cwd': str(workspace),
                **ready, 'home_override': home_override, 'model': args.model, 'sandbox': args.sandbox, 'turn_count': 0}
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix('.lock').open('x', encoding='utf-8')
        lock.write(str(os.getpid())); lock.flush()
        tools = 'Read,Glob,Grep' + (',Edit,Write' if args.sandbox == 'workspace-write' else '')
        command = [str(binary), '-p', '--output-format', 'stream-json', '--verbose',
            '--safe-mode', '--restricted', '--permission-mode', 'dontAsk', '--permission-prompts', 'none',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', tools, '--allowedTools', tools,
            '--resume' if args.action == 'send' else '--session-id', record['conversation_id']]
        if args.model:
            command += ['--model', args.model]
        if args.effort:
            command += ['--effort', args.effort]
        prompt += '\n\nReturn the result to the caller. Do not delegate this task further.'

        def observe(event):
            nonlocal seen_init
            if event.get('session_id') != record['conversation_id']:
                raise common.DelegateError('Claude returned another session; task stopped.')
            if event['type'] == 'system':
                if not event.get('cwd') or Path(event['cwd']).resolve() != workspace or not event.get('model'):
                    raise common.DelegateError('Claude returned unexpected workspace or model metadata.')
                if args.action == 'send' and event['model'] != record['model']:
                    raise common.DelegateError('Claude changed the continued model unexpectedly.')
                record['model'] = event['model']
                seen_init = True

        if cancelled and cancelled():
            raise common.DelegateCancelled('Claude cancellation requested.')
        owned = True
        record.update(status='running', content=None)
        common.write_json(path, record)
        notify({'event': 'dispatched', **public_record(record, False)})
        client = PrintClient()
        result = client.run(command, environment(home), workspace, prompt, args.timeout, cancelled, observe)
        if not seen_init or not record.get('model'):
            raise common.DelegateError('Claude did not confirm the selected model.')
        record.update(status='completed', content=result['content'], turn_count=record['turn_count']+1)
        common.write_json(path, record)
        completed = True
        notify({'event': 'completed', **public_record(record)})
    except BaseException as error:
        if owned and not completed:
            if client:
                client.stop()
            uncertain = isinstance(error, (TimeoutError, common.DelegateCancelled, KeyboardInterrupt))
            record.update(status='unknown' if uncertain else 'failed', content=None, error_type=type(error).__name__)
            common.write_json(path, record)
        raise
    finally:
        if client:
            client.stop()
        if lock:
            lock.close()
            path.with_suffix('.lock').unlink(missing_ok=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('action', choices=('discover', 'doctor', 'register', 'new', 'send', 'metadata', 'result'))
    result.add_argument('--target')
    result.add_argument('--targets-file', type=Path, default=Path(__file__).resolve().parents[1]/'claude-targets.json')
    result.add_argument('--claude-bin', type=Path)
    result.add_argument('--claude-home', type=Path)
    result.add_argument('--cwd', type=Path)
    result.add_argument('--model')
    result.add_argument('--effort', choices=('low', 'medium', 'high', 'xhigh', 'max'))
    result.add_argument('--prompt')
    result.add_argument('--prompt-file', type=Path)
    result.add_argument('--conversation-id')
    result.add_argument('--state-dir', type=Path, default=Path.cwd()/'.agent-delegate/claude')
    result.add_argument('--sandbox', choices=('read-only', 'workspace-write'), default='read-only')
    result.add_argument('--timeout', type=int, default=1200)
    return result


def main():
    args = parser().parse_args()
    try:
        if not 1 <= args.timeout <= 1200 or (args.prompt and args.prompt_file):
            raise common.DelegateError('Use one prompt source and a timeout of 1..1200 seconds.')
        run(args)
    except (Exception, KeyboardInterrupt) as error:
        common.emit({'provider': 'claude', 'error_type': type(error).__name__,
                     'error': 'Delegation failed; inspect the private receipt and native CLI configuration.'})
        raise SystemExit(1)


if __name__ == '__main__':
    main()
