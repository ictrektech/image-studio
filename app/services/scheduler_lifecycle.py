"""应用内生命周期客户端；凭据和原生停止证据始终留在服务端。"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import httpx


class LifecycleError(RuntimeError):
    pass


class Lifecycle:
    def __init__(self, load_config, journal):
        self.load_config, self.journal = load_config, Path(journal)
        self.lock = threading.RLock()
        self.io = threading.RLock()
        self.records, self.callbacks = {}, {}
        self.key, self.revision = None, None
        self.halt = threading.Event()
        self.thread = None
        try:
            info = self.journal.lstat()
            if not self.journal.is_file() or self.journal.is_symlink() or info.st_mode & 0o077 or info.st_size > 4194304:
                raise LifecycleError('Private lifecycle journal required')
            self.records = json.loads(self.journal.read_text())
            if not isinstance(self.records, dict):
                raise LifecycleError('Invalid lifecycle journal')
        except FileNotFoundError:
            pass

    def request(self, config, method, path, body=None):
        try:
            response = httpx.request(method, config['url'].rstrip('/') + path,
                headers={'Authorization': 'Bearer ' + config['token']}, json=body,
                timeout=8, follow_redirects=False)
            value = response.json()
            if not response.is_success or value.get('code') != 'OK':
                raise LifecycleError('Lifecycle operation rejected')
            return value['data']
        except (httpx.HTTPError, ValueError, KeyError):
            raise LifecycleError('Lifecycle service unavailable') from None

    def save(self):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_name(self.journal.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            with open(temporary, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
                json.dump(self.records, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.journal)
        finally:
            temporary.unlink(missing_ok=True)

    def ensure(self, config):
        ids = sorted(set(config.get('models', {}).values()) | set(config.get('gateway_executors', {}).values()))
        if not ids:
            raise LifecycleError('Approved executors required')
        key = hashlib.sha256(json.dumps([config['url'], config['token'], ids]).encode()).hexdigest()
        with self.io:
            if self.key == key and self.revision is not None:
                return
            current = self.request(config, 'GET', '/integrations')['items']
            revision = next((row['revision'] for row in current if row['app_id'] == config['app_id']), 0)
            reply = self.request(config, 'POST', '/integrations', {'protocol_version': 1,
                'revision': revision, 'executors': ids, 'stop_protocol': 'permit-native-exit-v1'})
            self.key, self.revision = key, reply['revision']

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.halt.clear()
            self.thread = threading.Thread(target=self.run, name='application-lifecycle', daemon=True)
            self.thread.start()

    def run(self):
        delay = 1
        while not self.halt.wait(delay):
            try:
                reply = self.tick()
                delay = max(1, min(10, int(reply.get('heartbeat_after_seconds', 5))))
            except Exception:
                # 不把底层响应、URL 或凭据写进日志；未知停止继续保留预约。
                self.key = self.revision = None
                delay = 2

    def attach(self, config, permit, execution, proof, cancel):
        with self.lock:
            self.records[permit] = {'execution_id': None, 'expected_id': execution,
                'execution_token': proof, 'stopped': False}
            self.callbacks[permit] = cancel
            self.save()

    def claimed(self, permit, execution):
        with self.lock:
            record = self.records[permit]
            if record['expected_id'] != execution:
                raise LifecycleError('Execution mismatch')
            record['execution_id'] = execution
            self.save()

    def finished(self, permit, stopped):
        with self.lock:
            record = self.records.get(permit)
            if not record:
                return
            record['stopped'] = stopped is True
            self.callbacks.pop(permit, None)
            self.save()

    def released(self, permit):
        with self.lock:
            self.records.pop(permit, None)
            self.callbacks.pop(permit, None)
            self.save()

    def tick(self):
        config = self.load_config()
        if config.get('lifecycle_protocol_version') != 1:
            return {'heartbeat_after_seconds': 2}
        self.ensure(config)
        with self.io:
            reply = self.request(config, 'POST', '/integrations/heartbeat', {'revision': self.revision})
        for command in reply.get('stop_requests', []):
            permit = command['permit_id']
            with self.lock:
                record = dict(self.records.get(permit) or {})
                callback = self.callbacks.get(permit)
            if record and record.get('execution_id') is None and record.get('expected_id') == command.get('execution_id') and record.get('stopped') is True:
                record['execution_id'] = command['execution_id']
            if not record or record.get('execution_id') != command.get('execution_id'):
                continue
            if callback:
                callback()
            if record.get('stopped') is not True:
                continue
            self.request(config, 'POST', '/permits/' + permit + '/stopped', {
                'nonce': command['nonce'], 'execution_id': record['execution_id'],
                'execution_token': record['execution_token'], 'native_exit_barrier': True,
                'model_unloaded': True, 'evidence': 'application confirmed native exit and weight unloading'})
            self.released(permit)
        # 仅删除已确认原生退出、且控制器完整快照中已经释放的回执。
        if reply.get('complete_execution_snapshot') is True:
            outstanding = {row['permit_id'] for row in reply.get('executions', [])}
            with self.lock:
                for permit, record in list(self.records.items()):
                    if record.get('stopped') is True and permit not in outstanding:
                        self.records.pop(permit)
                self.save()
        return reply

    def close(self):
        self.halt.set()
        if self.thread:
            self.thread.join(timeout=10)
