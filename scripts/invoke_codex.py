"""Delegate via a separately authenticated local Codex home, using stdio JSON-RPC.

Only user-visible completed messages are retained. This does not attach to the
private stdio connection owned by an existing desktop window. Python stdlib only.
"""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid


class DelegateError(RuntimeError):
    pass


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def identity(account):
    info = account.get('account') or {}
    if info.get('type') != 'chatgpt' or not info.get('email'):
        raise DelegateError('A signed-in ChatGPT account with identifiable account/read output is required.')
    value = '|'.join(str(info.get(k, '')) for k in ('type', 'email', 'accountId', 'userId'))
    return {'account_type': info['type'], 'plan': info.get('planType'),
            'account_fingerprint': hashlib.sha256(value.encode()).hexdigest()[:16]}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class Client:
    def __init__(self, home, binary=None):
        executable = binary or shutil.which('codex')
        if not executable:
            raise DelegateError('Codex CLI is not installed or not on PATH.')
        if not home.is_dir():
            raise DelegateError('The selected Codex home must already exist.')
        env = os.environ.copy()
        env['CODEX_HOME'] = str(home)
        # The selected home owns authentication, not credentials inherited from A.
        for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL'):
            env.pop(key, None)
        self.process = subprocess.Popen(
            [str(executable), 'app-server', '--listen', 'stdio://'],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self.queue = queue.Queue()
        self.pending = deque()
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.rpc('initialize', {'clientInfo': {'name': 'agent_delegate', 'version': '1.0.0'},
                                   'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized', 'params': {}})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.queue.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.queue.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False)+'\n')
        self.process.stdin.flush()

    def _receive(self, deadline):
        try:
            message = self.queue.get(timeout=max(.001, deadline-time.monotonic()))
        except queue.Empty:
            raise TimeoutError('Codex response deadline exceeded.') from None
        if message is None:
            raise DelegateError('Codex app-server exited before completing the request.')
        if 'id' in message and 'method' in message:
            # This helper cannot consent on the user's behalf or fabricate input.
            self.send({'id': message['id'], 'error': {'code': -32601,
                       'message': 'agent-delegate cannot answer interactive requests'}})
            raise DelegateError('Codex needs interactive input: '+message['method'])
        return message

    def rpc(self, method, params, timeout=30):
        self.sequence += 1
        request_id = self.sequence
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic()+timeout
        while True:
            message = self._receive(deadline)
            if message.get('id') == request_id:
                if 'error' in message:
                    error = message['error']
                    detail = str(error.get('message', ''))[:500]
                    detail = re.sub(r'(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+', '[redacted]', detail)
                    raise DelegateError(f"{method} failed ({error.get('code')}): {detail}")
                return message.get('result') or {}
            self.pending.append(message)

    def event(self, deadline):
        return self.pending.popleft() if self.pending else self._receive(deadline)

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


def state_path(directory, conversation_id):
    # Canonical UUID prevents arbitrary file access through an untrusted handle.
    try:
        canonical = str(uuid.UUID(conversation_id))
    except (ValueError, TypeError, AttributeError):
        raise DelegateError('Conversation ID must be a UUID.') from None
    return directory / (canonical+'.json')


def load_record(args):
    path = state_path(args.state_dir, args.conversation_id)
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('conversation_id') != path.stem or record.get('provider') != 'codex':
        raise DelegateError('Invalid delegation receipt.')
    return path, record


def public_record(record, content=True):
    value = {k: record.get(k) for k in ('provider', 'conversation_id', 'session_id', 'status',
             'codex_home', 'account_fingerprint', 'cwd', 'sandbox', 'model', 'model_provider',
             'desktop_process_attached', 'turn_id', 'turn_count', 'mode', 'operation')}
    if content:
        value['content'] = record.get('content')
    return value


def resolve_target(args):
    if args.target:
        config = json.loads(args.targets_file.read_text(encoding='utf-8'))
        target = config['targets'].get(args.target)
        if not target:
            raise DelegateError('Unknown target; use discover or supply an explicit Codex home.')
        if args.codex_home:
            raise DelegateError('Use --target or --codex-home, not both.')
        args.codex_home = Path(target['codex_home'])
        if args.expected_account and args.expected_account != target['account_fingerprint']:
            raise DelegateError('Explicit account pin disagrees with the target registry.')
        args.expected_account = target['account_fingerprint']
        if not args.codex_bin and target.get('codex_bin'):
            args.codex_bin = Path(target['codex_bin'])
    if not args.codex_home:
        raise DelegateError('Select --target or --codex-home; the helper never silently uses A.')
    args.codex_home = args.codex_home.expanduser().resolve()


def register_target(args):
    if not args.target or not args.codex_home or not args.expected_account:
        raise DelegateError('register requires --target, --codex-home and the fingerprint from doctor as --expected-account.')
    home = args.codex_home.expanduser().resolve()
    client = Client(home, args.codex_bin)
    try:
        account = identity(client.rpc('account/read', {'refreshToken': False}))
        if account['account_fingerprint'] != args.expected_account:
            raise DelegateError('Target account changed; no target was registered.')
    finally:
        client.close()
    config = json.loads(args.targets_file.read_text(encoding='utf-8')) if args.targets_file.exists() else {'targets': {}}
    targets = config.setdefault('targets', {})
    existing = targets.get(args.target)
    if existing and (Path(existing['codex_home']).expanduser().resolve() != home or
                     existing['account_fingerprint'] != account['account_fingerprint']):
        raise DelegateError('Target name already has a different home or account pin. Review the mapping or use a new target name.')
    entry = {'codex_home': str(home), 'account_fingerprint': account['account_fingerprint']}
    if args.codex_bin:
        entry['codex_bin'] = str(args.codex_bin.expanduser().resolve())
    elif existing and existing.get('codex_bin'):
        entry['codex_bin'] = existing['codex_bin']
    targets[args.target] = entry
    write_json(args.targets_file, config)
    emit({'provider': 'codex', 'registered': True, 'target': args.target,
          'codex_home': str(home), 'account_fingerprint': account['account_fingerprint'],
          'config_path': str(args.targets_file)})


def task_mode(prompt, explicit):
    match = re.match(r'^/(plan|review)(?:\s+|$)', prompt or '')
    if match:
        if explicit and explicit != match[1]:
            raise DelegateError('The mode option and prompt command disagree; no task was sent.')
        return prompt[match.end():], match[1]
    return prompt, explicit


def run(args):
    if args.action == 'discover':
        registry = Path.home()/'.cockpit_tools/codex_instances.json'
        data = json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {}
        registered = json.loads(args.targets_file.read_text(encoding='utf-8')) if args.targets_file.exists() else {}
        emit({'provider': 'codex', 'instances': [
            {k: item.get(k) for k in ('id', 'name', 'userDataDir', 'launchMode', 'lastPid')}
            for item in data.get('instances', [])],
              'registered_targets': [{'name': name, 'codex_home': target['codex_home']}
                                     for name, target in registered.get('targets', {}).items()]})
        return
    if args.action == 'register':
        register_target(args)
        return
    if args.action in ('metadata', 'result'):
        _, record = load_record(args)
        if args.action == 'result' and record['status'] != 'completed':
            raise DelegateError('No successfully completed result; status='+record['status'])
        emit(public_record(record, args.action == 'result'))
        return
    resolve_target(args)
    if args.action != 'doctor' and not args.expected_account:
        raise DelegateError('Run doctor, then pin its fingerprint with --expected-account or a target registry.')
    client = Client(args.codex_home, args.codex_bin)
    path = record = lock = None
    try:
        account = identity(client.rpc('account/read', {'refreshToken': False}))
        if args.expected_account and account['account_fingerprint'] != args.expected_account:
            raise DelegateError('Target account changed; no task was sent. Run doctor and confirm the intended account.')
        if args.action == 'doctor':
            models = client.rpc('model/list', {})
            emit({'provider': 'codex', 'mode': 'isolated-home-stdio', 'codex_home': str(args.codex_home),
                  **account, 'default_models': [m['id'] for m in models.get('data', []) if m.get('isDefault')],
                  'desktop_process_attached': False})
            return
        compact = args.action == 'compact'
        prompt = args.prompt_file.read_text(encoding='utf-8') if args.prompt_file else args.prompt
        prompt, requested_mode = task_mode(prompt, getattr(args, 'mode', None))
        if compact and (prompt or requested_mode):
            raise DelegateError('compact takes a conversation handle, not a prompt or mode.')
        if not compact and (not prompt or not prompt.strip()):
            raise DelegateError('A nonempty --prompt or UTF-8 --prompt-file is required.')
        if args.action == 'new':
            if not args.cwd or not args.cwd.is_dir():
                raise DelegateError('new requires an existing explicit --cwd.')
            workspace = args.cwd.resolve()
            start_params = {'cwd': str(workspace), 'approvalPolicy': 'never', 'sandbox': args.sandbox}
            if args.model:
                start_params['model'] = args.model
            response = client.rpc('thread/start', start_params)
            thread = response['thread']
            thread_id = thread['id']
            if Path(thread['cwd']).resolve() != workspace:
                raise DelegateError('Codex returned a different workspace; no prompt was sent.')
            session_id = thread.get('sessionId') or thread_id
            if session_id != thread_id or thread.get('forkedFromId'):
                raise DelegateError('Expected an independent root conversation; no prompt was sent.')
            path = state_path(args.state_dir, thread_id)
            record = {'provider': 'codex', 'conversation_id': thread_id, 'session_id': session_id,
                      'codex_home': str(args.codex_home), **account, 'cwd': str(workspace),
                      'sandbox': args.sandbox, 'model': response.get('model'),
                      'model_provider': response.get('modelProvider'), 'turn_count': 0,
                      'reasoning_effort': response.get('reasoningEffort'), 'mode': 'default',
                      'desktop_process_attached': False, 'title': args.title}
        else:
            path, record = load_record(args)
            if Path(record['codex_home']).resolve() != args.codex_home or record['account_fingerprint'] != account['account_fingerprint']:
                raise DelegateError('Receipt belongs to a different Codex home or account; no task was sent.')
            if args.cwd and args.cwd.resolve() != Path(record['cwd']).resolve():
                raise DelegateError('Continuation cannot silently change workspace.')
            if args.model and args.model != record['model']:
                raise DelegateError('This continuation helper preserves the recorded model. Start a new task for an explicit model change.')
            if args.sandbox != record['sandbox']:
                raise DelegateError('Continuation must explicitly keep the recorded sandbox mode.')
            if record.get('status') == 'running':
                raise DelegateError('Conversation is already running; wait for its owning helper.')
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix('.lock')
        lock = lock_path.open('x', encoding='utf-8')
        lock.write(str(os.getpid()))
        lock.flush()
        if args.action in ('send', 'compact'):
            thread_id = record['conversation_id']
            client.rpc('thread/resume', {'threadId': thread_id, 'excludeTurns': True,
                       'cwd': record['cwd'], 'approvalPolicy': 'never',
                       'sandbox': record['sandbox']})
        mode = requested_mode or record.get('mode', 'default')
        record.update(status='running', content=None, worker_pid=os.getpid(),
                      operation='compact' if compact else mode)
        if not compact:
            record['mode'] = mode
            if args.effort:
                record['reasoning_effort'] = args.effort
        write_json(path, record)
        if compact:
            client.rpc('thread/compact/start', {'threadId': thread_id})
            turn_id = None
        elif mode == 'review':
            response = client.rpc('review/start', {'threadId': thread_id, 'delivery': 'inline',
                                  'target': {'type': 'custom', 'instructions': prompt}})
            if response.get('reviewThreadId') != thread_id:
                raise DelegateError('Review changed conversation unexpectedly.')
            turn_id = response['turn']['id']
        else:
            params = {'threadId': thread_id, 'input': [{'type': 'text', 'text': prompt}], 'effort': args.effort}
            if requested_mode or mode == 'plan':
                modes = client.rpc('collaborationMode/list', {}).get('data', [])
                if not any(item.get('mode') == mode for item in modes):
                    raise DelegateError('Requested collaboration mode is unavailable; no substitute was sent.')
                params['collaborationMode'] = {'mode': mode, 'settings': {
                    'model': record['model'], 'reasoning_effort': args.effort or record.get('reasoning_effort'),
                    'developer_instructions': None}}
            response = client.rpc('turn/start', params)
            turn_id = response['turn']['id']
        record['turn_id'] = turn_id
        write_json(path, record)
        emit({'event': 'dispatched', **public_record(record, False)})
        deadline = time.monotonic()+args.timeout
        visible = []
        compacted = False
        while True:
            message = client.event(deadline)
            params = message.get('params') or {}
            if params.get('threadId') != thread_id:
                continue
            if compact and message.get('method') == 'turn/started' and not turn_id:
                turn_id = params['turn']['id']
                record['turn_id'] = turn_id
            if message.get('method') == 'item/completed' and params.get('turnId') == turn_id:
                item = params.get('item') or {}
                if item.get('type') == 'agentMessage' and item.get('text'):
                    visible.append((item.get('phase'), item['text']))
                elif item.get('type') == 'plan' and item.get('text'):
                    visible.append(('final_answer', item['text']))
                elif item.get('type') == 'exitedReviewMode' and item.get('review'):
                    visible.append(('final_answer', item['review']))
                elif item.get('type') == 'contextCompaction':
                    compacted = True
            if message.get('method') == 'turn/completed':
                turn = params.get('turn') or {}
                if turn.get('id') != turn_id:
                    continue
                record['status'] = turn.get('status', 'failed')
                record['turn_count'] += 1
                final = [text for phase, text in visible if phase == 'final_answer']
                record['content'] = ('Conversation context compacted.' if compact and compacted else
                                     (final or [text for _, text in visible] or [None])[-1])
                write_json(path, record)
                if record['status'] != 'completed':
                    raise DelegateError('Codex turn ended with status='+record['status'])
                if not record['content']:
                    record['status'] = 'failed'
                    raise DelegateError('Codex completed without a user-visible final response.')
                # Initial inference can overwrite a name set before turn/start.
                # Naming is presentation metadata and must not invalidate a result.
                if record.get('title'):
                    try:
                        client.rpc('thread/name/set', {'threadId': thread_id, 'name': record['title']})
                    except DelegateError:
                        record['title_verified'] = False
                    else:
                        record['title_verified'] = True
                    write_json(path, record)
                emit({'event': 'completed', **public_record(record)})
                return
    except BaseException as error:
        if record and path and lock:
            if record.get('status') == 'running':
                try:
                    client.rpc('turn/interrupt', {'threadId': record['conversation_id'], 'turnId': record['turn_id']}, timeout=5)
                except Exception:
                    pass
                record['status'] = 'timed_out' if isinstance(error, TimeoutError) else 'failed'
            record['content'] = None
            record['error_type'] = type(error).__name__
            write_json(path, record)
        raise
    finally:
        client.close()
        if lock:
            lock.close()
            lock_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['discover', 'doctor', 'register', 'new', 'send', 'compact', 'metadata', 'result'])
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--codex-bin', type=Path)
    parser.add_argument('--target')
    parser.add_argument('--targets-file', type=Path, default=Path(__file__).resolve().parents[1]/'codex-targets.json')
    parser.add_argument('--expected-account')
    parser.add_argument('--state-dir', type=Path, default=Path.cwd()/'.agent-delegate/codex')
    parser.add_argument('--conversation-id')
    prompts = parser.add_mutually_exclusive_group()
    prompts.add_argument('--prompt')
    prompts.add_argument('--prompt-file', type=Path)
    parser.add_argument('--cwd', type=Path)
    parser.add_argument('--title', default='Agent delegated task')
    parser.add_argument('--model', help='Set only when the user explicitly requests a model; otherwise use B\'s configuration.')
    parser.add_argument('--mode', choices=['default', 'plan', 'review'], help='Native task mode; preserved on continuation.')
    parser.add_argument('--sandbox', choices=['read-only', 'workspace-write'], default='read-only')
    parser.add_argument('--effort', choices=['low', 'medium', 'high', 'xhigh', 'max', 'ultra'], default=None)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1200:
        parser.error('--timeout must be 1..1200 seconds; do not monitor indefinitely.')
    try:
        run(args)
    except (Exception, KeyboardInterrupt) as error:
        emit({'event': 'error', 'error_type': type(error).__name__, 'error': str(error)})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
