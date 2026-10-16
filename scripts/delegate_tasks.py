"""Local task lifecycle for MCP; provider adapters own authentication."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid

import invoke_codex as codex

ACTIVE = {'queued', 'running', 'cancelling'}
PUBLIC = ('task_id', 'provider', 'target', 'workspace', 'conversation_id', 'status',
          'phase', 'model', 'mode', 'workflow', 'allow_writes', 'content', 'error', 'created_at', 'updated_at')


def scrub(error):
    return re.sub(r'(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+', '[redacted]', str(error))[:500]


class TaskManager:
    def __init__(self, skill, state, targets=None, projects=None):
        self.skill, self.state = Path(skill).resolve(), Path(state).resolve()
        self.targets = Path(targets or self.skill/'codex-targets.json').resolve()
        self.projects = Path(projects or self.skill/'projects.json').resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.guard = threading.RLock()
        self.workers, self.records = {}, {}
        self.closed = False
        self.lease = (self.state/'server.lock').open('a+b')
        try:
            self.lease.seek(0)
            if os.name == 'nt':
                import msvcrt
                self.lease.write(b'0'); self.lease.flush(); self.lease.seek(0)
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            raise ValueError('Another MCP server owns this state directory.') from None
        for path in self.state.glob('*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if str(uuid.UUID(path.stem)) != record['task_id']:
                    continue
                self.records[path.stem] = record
                if record['status'] in ACTIVE:
                    self.update(record, status='unknown', content=None,
                                error='Previous server stopped without a confirmed outcome. Inspect the provider before continuing.')
            except (ValueError, KeyError, TypeError):
                continue

    def update(self, record, **values):
        with self.guard:
            record.update(values, updated_at=time.time())
            codex.write_json(self.state/(record['task_id']+'.json'), record)

    def view(self, record):
        with self.guard:
            return {k: record.get(k) for k in PUBLIC}

    def get(self, task_id):
        try:
            task_id = str(uuid.UUID(task_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('task_id must be a UUID returned by this server.') from None
        with self.guard:
            if task_id not in self.records:
                raise ValueError('Unknown task; this server can only access its own receipts.')
            return self.records[task_id]

    @staticmethod
    def read_config(path, key):
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding='utf-8')).get(key, {})

    def list_agents(self, check_health=False):
        result = []
        for name, target in self.read_config(self.targets, 'targets').items():
            entry = {'provider':'codex', 'target':name, 'available':None,
                     'workflows':['default','plan','review','compact']}
            if check_health:
                client = None
                try:
                    client = codex.Client(Path(target['codex_home']), target.get('codex_bin'))
                    account = codex.identity(client.rpc('account/read', {'refreshToken':False}))
                    entry['available'] = account['account_fingerprint'] == target['account_fingerprint']
                    if not entry['available']: entry['error'] = 'Account pin mismatch.'
                except Exception as error:
                    entry.update(available=False, error=scrub(error))
                finally:
                    if client: client.close()
            result.append(entry)
        for workspace in self.read_config(self.projects, 'projects'):
            entry = {'provider':'antigravity', 'workspace':workspace, 'available':None,
                     'workflows':['plan','grill-me','boost','teamwork-preview']}
            if check_health:
                try:
                    status = self.anti_call(workspace, 'doctor')
                    entry['available'] = bool(status.get('service_found') and status.get('project_id_valid'))
                except Exception as error:
                    entry.update(available=False, error=scrub(error))
            result.append(entry)
        return {'agents':result, 'health_checked':check_health,
                'note':'Health checks verify routing/authentication, not model inference or task success.'}

    def start(self, provider, workspace, prompt, target=None, model=None, mode=None,
              workflow=None, allow_writes=False, timeout_seconds=1200):
        workspace = Path(workspace).expanduser().resolve()
        if not workspace.is_dir(): raise ValueError('workspace must be an existing directory.')
        self.validate(provider, prompt, mode, workflow, timeout_seconds)
        if provider == 'codex':
            if not target or target not in self.read_config(self.targets, 'targets'):
                raise ValueError('Select a registered Codex target from list_agents.')
        else:
            if target: raise ValueError('Antigravity uses its registered workspace, not a Codex target name.')
            mappings = self.read_config(self.projects, 'projects')
            if os.path.normcase(str(workspace)).lower() not in {os.path.normcase(p).lower() for p in mappings}:
                raise ValueError('Register this Antigravity workspace first; see references/setup.md.')
        record = {'task_id':str(uuid.uuid4()), 'provider':provider, 'workspace':str(workspace),
                  'target':target, 'model':model, 'mode':mode, 'workflow':workflow,
                  'allow_writes':allow_writes, 'timeout_seconds':timeout_seconds,
                  'status':'queued', 'phase':'starting', 'content':None, 'error':None,
                  'conversation_id':None, 'created_at':time.time()}
        with self.guard:
            self.check_open()
            self.records[record['task_id']] = record
            self.update(record)
            self.launch(record, prompt, False)
            return self.view(record)

    @staticmethod
    def validate(provider, prompt, mode, workflow, timeout):
        if provider not in ('codex','antigravity'): raise ValueError('Unknown provider.')
        if not isinstance(prompt,str) or not prompt.strip(): raise ValueError('A nonempty prompt is required.')
        if not 1 <= timeout <= 1200: raise ValueError('timeout_seconds must be 1..1200.')
        if provider == 'codex' and (workflow or mode not in (None,'default','plan','review','compact')):
            raise ValueError('Codex accepts mode, not an Antigravity workflow.')
        if provider == 'antigravity' and (mode or workflow not in (None,'plan','grill-me','boost','teamwork-preview')):
            raise ValueError('Antigravity accepts workflow, not a Codex mode.')
        if provider == 'antigravity' and prompt.lstrip().startswith(('/goal','/schedule','/learn')):
            raise ValueError('Persistent goals, schedules and learning are outside these bounded MCP tasks.')

    def check_open(self):
        if self.closed: raise ValueError('MCP server is shutting down.')

    def launch(self, record, prompt, continuation):
        event = threading.Event()
        thread = threading.Thread(target=self.execute, args=(record,prompt,continuation,event), daemon=True)
        self.workers[record['task_id']] = (thread,event)
        thread.start()

    def continue_task(self, task_id, prompt, mode=None, workflow=None, timeout_seconds=1200):
        with self.guard:
            self.check_open()
            record = self.get(task_id)
            if record['status'] not in ('completed','cancelled','interrupted') or not record.get('conversation_id'):
                raise ValueError('Only a confirmed stopped task with a conversation handle can be continued.')
            self.validate(record['provider'],prompt,mode,workflow,timeout_seconds)
            if mode == 'compact' and record['provider'] != 'codex': raise ValueError('compact requires Codex.')
            self.update(record,status='queued',phase='starting',content=None,error=None,
                        mode=mode if mode is not None else record.get('mode'),
                        workflow=workflow,timeout_seconds=timeout_seconds)
            self.launch(record,prompt,True)
            return self.view(record)

    def cancel(self, task_id):
        with self.guard:
            record = self.get(task_id)
            if record['status'] in ACTIVE:
                self.workers[record['task_id']][1].set()
                self.update(record,status='cancelling')
            return self.view(record)

    def execute(self, record, prompt, continuation, event):
        try:
            with self.guard:
                if event.is_set():
                    self.update(record,status='cancelled'); return
                self.update(record,status='running')
            prompt += ('\n\nDelegation scope: '+
                       ('Edits are authorized only inside the specified workspace.' if record['allow_writes'] else
                        'Read-only task. Do not modify workspace files.')+
                       ' Return the result to the caller. Do not delegate this task back to its caller.')
            if record['provider'] == 'codex': self.run_codex(record,prompt,continuation,event)
            else: self.run_antigravity(record,prompt,continuation,event)
        except Exception as error:
            if record['provider'] == 'codex' and record.get('conversation_id'):
                receipt = self.state/'codex'/(record['conversation_id']+'.json')
                if receipt.exists():
                    state = json.loads(receipt.read_text(encoding='utf-8')).get('status')
                else: state='failed'
            else: state='unknown' if record.get('conversation_id') else 'failed'
            self.update(record,status=state if state not in ACTIVE else 'unknown',content=None,error=scrub(error))

    def run_codex(self, record, prompt, continuation, event):
        action = 'send' if continuation else 'new'
        if record.get('mode') == 'compact':
            if not continuation: raise ValueError('Compaction requires an existing task; use continue_task.')
            action,prompt = 'compact',None
        args = argparse.Namespace(action=action,target=record['target'],codex_home=None,codex_bin=None,
            targets_file=self.targets,expected_account=None,state_dir=self.state/'codex',
            conversation_id=record.get('conversation_id'),prompt=prompt,prompt_file=None,
            cwd=Path(record['workspace']),sandbox='workspace-write' if record['allow_writes'] else 'read-only',
            title='Agent Delegate MCP task',model=record.get('model'),effort=None,
            mode=None if action=='compact' else record.get('mode'),timeout=record['timeout_seconds'])
        completed = {}
        def receive(value):
            changes = {k:value[k] for k in ('conversation_id','status','content','model','mode') if k in value}
            if value.get('event') == 'completed': completed.update(changes)
            else: self.update(record,phase='submitted',**changes)
        codex.run(args,notify=receive,cancelled=event.is_set)
        self.update(record,**completed)

    def anti_call(self, workspace, action, conversation_id=None, prompt=None, model=None, workflow=None):
        pwsh = shutil.which('pwsh')
        if not pwsh: raise ValueError('PowerShell 7 is required for Antigravity.')
        command = [pwsh,'-NoProfile','-NonInteractive','-File',str(self.skill/'scripts/invoke_antigravity.ps1'),'-Action',action]
        for flag,value in (('-ConversationId',conversation_id),('-Model',model),('-Workflow',workflow)):
            if value: command += [flag,value]
        prompt_path = None
        if prompt is not None:
            prompt_path = self.state/('prompt-'+str(uuid.uuid4())+'.txt')
            prompt_path.write_text(prompt,encoding='utf-8')
            command += ['-PromptFile',str(prompt_path)]
            if action == 'send': command += ['-Structured']
        env=os.environ.copy(); env['ANTIGRAVITY_DELEGATE_CONFIG']=str(self.projects)
        env['PYTHONIOENCODING']='utf-8'
        try:
            output = subprocess.run(command,cwd=workspace,env=env,capture_output=True,text=True,
                                    encoding='utf-8',errors='replace',timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if output.returncode:
                # Provider stderr may include command arguments. Do not expose it.
                raise ValueError('Antigravity '+action+' failed; check the running app, workspace and local permissions.')
            value=json.loads(output.stdout)
            if value.get('error'): raise ValueError('Antigravity rejected '+action+'.')
            return value
        finally:
            if prompt_path: prompt_path.unlink(missing_ok=True)

    def run_antigravity(self, record, prompt, continuation, event):
        workspace=record['workspace']
        if not continuation:
            response=self.anti_call(workspace,'new',prompt='No-op handshake. No tools or files. Reply HANDSHAKE_OK and stop.',model=record.get('model'))
            self.update(record,conversation_id=response['response']['newConversation']['conversationId'])
        cid=record['conversation_id']
        deadline=time.monotonic()+record['timeout_seconds']
        while True:
            state=self.anti_call(workspace,'status',cid)
            if event.is_set(): return self.stop_antigravity(record,event)
            if state['run_status']=='CASCADE_RUN_STATUS_IDLE': break
            if time.monotonic()>=deadline: return self.stop_antigravity(record,event,timed_out=True)
            event.wait(1)
        baseline=state['step_count']
        self.anti_call(workspace,'send',cid,prompt=prompt,workflow=record.get('workflow'))
        self.update(record,phase='submitted')
        while True:
            if event.is_set(): return self.stop_antigravity(record,event)
            if time.monotonic()>=deadline: return self.stop_antigravity(record,event,timed_out=True)
            state=self.anti_call(workspace,'status',cid)
            new_response=state['latest_user_index']>=baseline and state['response_index']>state['latest_user_index']
            if state['run_status']=='CASCADE_RUN_STATUS_IDLE' and state['latest_user_index']>=baseline and state['has_error']:
                self.update(record,status='failed',content=None,error='Antigravity reported a task error.')
                return
            if state['run_status']=='CASCADE_RUN_STATUS_IDLE' and new_response:
                self.update(record,status='failed' if state['has_error'] else 'completed',
                            content=None if state['has_error'] else state['content'])
                return
            event.wait(2)

    def stop_antigravity(self, record, event, timed_out=False):
        state=self.anti_call(record['workspace'],'cancel',record['conversation_id'])
        end=time.monotonic()+15
        while state['run_status']!='CASCADE_RUN_STATUS_IDLE' and time.monotonic()<end:
            time.sleep(.5)
            state=self.anti_call(record['workspace'],'status',record['conversation_id'])
        stopped=state['run_status']=='CASCADE_RUN_STATUS_IDLE'
        self.update(record,status=('timed_out' if timed_out else 'cancelled') if stopped else 'unknown',
                    content=None,error=None if stopped else 'Cancellation was requested but not confirmed.')

    def close(self):
        with self.guard:
            self.closed=True
            active=[]
            for task_id,(thread,event) in self.workers.items():
                if thread.is_alive(): event.set(); active.append(thread)
        end=time.monotonic()+25
        for thread in active: thread.join(max(0,end-time.monotonic()))
        for record in self.records.values():
            if record['status'] in ACTIVE:
                self.update(record,status='unknown',content=None,error='Shutdown could not confirm task cancellation.')
        self.lease.close()
