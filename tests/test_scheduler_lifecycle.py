"""用私有临时目录验证真实客户端的注册、停止屏障及持久回执。"""
import importlib.util
import json
import pathlib
import tempfile
import unittest

# 各应用将此测试放在 tests/，仅载入客户端模块，不加载任何模型。
ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = [ROOT/'vvoice/scheduler_lifecycle.py', ROOT/'app/services/scheduler_lifecycle.py']
PATH = next(path for path in CANDIDATES if path.exists())
spec = importlib.util.spec_from_file_location('lifecycle_under_test', PATH)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {'app_id':'application', 'url':'http://scheduler/scheduler/api/v1',
            'token':'a'*64, 'models':{'model':'approved'}, 'gateway_executors':{'model':'gateway'}, 'lifecycle_protocol_version':1}
        self.commands, self.acks, self.registrations, self.cancelled = [], [], [], []
        self.snapshot = [{'permit_id':'permit'}]
        self.file = pathlib.Path(self.directory.name)/'receipt.json'
        self.client = self.make_client()

    def make_client(self):
        client = module.Lifecycle(lambda:self.config, self.file)
        def request(config, method, path, body=None):
            if path == '/integrations' and method == 'GET': return {'items':[]}
            if path == '/integrations':
                self.registrations.append(body);return {'revision':1}
            if path == '/integrations/heartbeat': return {'stop_requests':self.commands, 'executions':self.snapshot, 'complete_execution_snapshot':True}
            self.acks.append(body);return {'state':'released'}
        client.request = request
        return client

    def attach(self):
        self.client.attach(self.config,'permit','execution','private-proof',lambda:self.cancelled.append(True))
        self.client.claimed('permit','execution')
        self.commands = [{'permit_id':'permit','execution_id':'execution','nonce':'challenge'}]

    def test_registers_approved_direct_and_gateway_executors_only(self):
        self.client.tick();self.client.tick()
        self.assertEqual(len(self.registrations),1)
        self.assertEqual(self.registrations[0]['executors'],['approved','gateway'])
        self.assertNotIn('resources',self.registrations[0])
        self.assertNotIn('token',json.dumps(self.registrations))

    def test_stop_does_not_ack_until_native_exit_and_unload(self):
        self.attach();self.client.tick()
        self.assertTrue(self.cancelled);self.assertEqual(self.acks,[])
        self.client.finished('permit',False);self.client.tick();self.assertEqual(self.acks,[])
        self.client.finished('permit',True);self.client.tick()
        self.assertTrue(self.acks[0]['native_exit_barrier']);self.assertTrue(self.acks[0]['model_unloaded'])
        self.assertEqual(self.acks[0]['nonce'],'challenge');self.assertFalse(self.client.records)

    def test_wrong_execution_does_not_cancel_or_release(self):
        self.attach();self.commands[0]['execution_id']='other'
        self.client.tick();self.assertEqual(self.cancelled,[]);self.assertEqual(self.acks,[])

    def test_confirmed_receipt_survives_application_restart(self):
        self.attach();self.client.finished('permit',True)
        restored=self.make_client();restored.tick()
        self.assertEqual(self.acks[0]['execution_token'],'private-proof')
        self.assertEqual(self.file.stat().st_mode & 0o777,0o600)
        self.assertNotIn(self.config['token'],self.file.read_text())

    def test_unknown_active_execution_after_restart_never_fakes_stop(self):
        self.attach();restored=self.make_client();restored.tick();self.assertEqual(self.acks,[])

    def test_claim_response_loss_reconciles_only_after_confirmed_exit(self):
        self.client.attach(self.config,'permit','execution','private-proof',lambda:None)
        self.commands=[{'permit_id':'permit','execution_id':'execution','nonce':'challenge'}]
        self.client.tick();self.assertEqual(self.acks,[])
        self.client.finished('permit',True);self.client.tick();self.assertEqual(self.acks[0]['execution_id'],'execution')

    def test_complete_snapshot_only_cleans_confirmed_released_receipts(self):
        self.attach();self.commands=[];self.snapshot=[];self.client.tick();self.assertIn('permit',self.client.records)
        self.client.finished('permit',True);self.client.tick();self.assertNotIn('permit',self.client.records)

    def test_legacy_binding_does_not_enable_new_protocol(self):
        self.config.pop('lifecycle_protocol_version');self.client.tick();self.assertEqual(self.registrations,[])

if __name__=='__main__':unittest.main()
