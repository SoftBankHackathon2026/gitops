import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location('adapter', pathlib.Path(__file__).parents[1] / 'control/adapter.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.s = dict(mode='running', target='aws', in_flight=0, epoch='0')
        self.calls = []
        self.ready = True
        self.targets = {t: dict(url=f'https://{t}.example.com', environment=t, database=t) for t in ['aws','gcp']}
        self.adapter = m.Adapter('http://control', 'test-token', self.targets, self.request)

    def request(self, method, url, body=None, token=None, timeout=None):
        self.calls.append((method,url,body))
        if url.endswith('/readyz'): return {'status':'ok' if self.ready else 'fail'}
        if url.endswith('/api/info'):
            t = 'gcp' if 'gcp.' in url else 'aws'
            return {'environment':t, 'database':{'name':t}, 'writes_paused':False}
        if url.endswith('/pause'): self.s['mode']='paused'; return {**self.s,'settled':True}
        if url.endswith('/target'):
            assert body['expected_epoch']==self.s['epoch']
            self.s['target']=body['target']; self.s['epoch']=str(int(self.s['epoch'])+1)
        if url.endswith('/resume'):
            assert body['expected_epoch']==self.s['epoch'];self.s['mode']='running'
        return dict(self.s)

    def test_pause_drain_switch_resume_contract(self):
        self.assertEqual(self.adapter.handle('GET','/status',{})['known_targets'], ['aws','gcp'])
        self.adapter.handle('POST','/pause',{})
        self.assertTrue(self.adapter.handle('POST','/drain',{})['settled'])
        self.adapter.handle('POST','/target',{'target':'gcp'})
        self.assertEqual(self.s['mode'],'paused')
        self.adapter.handle('POST','/resume',{})
        self.assertEqual(self.adapter.handle('GET','/healthz',{}),{'healthy':True,'target':'gcp'})
        self.assertFalse(any('/api/requests' in u for _,u,_ in self.calls))

    def test_drain_does_not_need_queue_empty(self):
        self.s.update(mode='paused',backlog=100)
        self.assertTrue(self.adapter.handle('POST','/drain',{'timeout':0})['settled'])

    def test_target_requires_pause_and_no_inflight(self):
        with self.assertRaisesRegex(m.ControlError,'PAUSE_REQUIRED'):
            self.adapter.handle('POST','/target',{'target':'gcp'})
        self.s.update(mode='paused',in_flight=1)
        with self.assertRaisesRegex(m.ControlError,'PAUSE_REQUIRED'):
            self.adapter.handle('POST','/target',{'target':'gcp'})

    def test_same_target_retry_does_not_increment_epoch(self):
        self.s.update(mode='paused',target='gcp',epoch='7')
        self.adapter.handle('POST','/target',{'target':'gcp'})
        self.assertEqual(self.s['epoch'],'7')

    def test_unknown_target_and_bad_status_fail_closed(self):
        self.s['mode']='paused'
        with self.assertRaisesRegex(m.ControlError,'UNKNOWN_TARGET'):
            self.adapter.handle('POST','/target',{'target':'elsewhere'})
        self.s['mode']='maybe'
        with self.assertRaisesRegex(m.ControlError,'INVALID_INGRESS_STATE'):
            self.adapter.status()

    def test_health_failure_prevents_resume(self):
        self.s['mode']='paused';self.ready=False
        with self.assertRaisesRegex(m.ControlError,'TARGET_NOT_READY'):
            self.adapter.handle('POST','/resume',{})
        self.assertEqual(self.s['mode'],'paused')

    def test_drain_timeout_keeps_paused(self):
        self.s.update(mode='paused',in_flight=1)
        self.assertFalse(self.adapter.handle('POST','/drain',{'timeout':0})['settled'])

    def test_credentials_require_https(self):
        self.targets['gcp']['url']='http://gcp.example.com'
        with self.assertRaisesRegex(m.ControlError,'TARGET_HTTPS_REQUIRED'):
            m.Adapter('http://control','test-token',self.targets)

    def test_busy_control_rejected(self):
        self.adapter.lock.acquire()
        try:
            with self.assertRaisesRegex(m.ControlError,'CONTROL_BUSY'):
                self.adapter.handle('POST','/pause',{})
        finally:self.adapter.lock.release()

if __name__=='__main__': unittest.main()
