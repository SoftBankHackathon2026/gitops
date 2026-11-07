"""Loopback adapter: migration.cloud app contract -> authenticated durable ingress.

Only the migration process sharing this Pod can call this server. No database
writes or queue deletion. Errors deliberately exclude backend bodies/secrets.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ControlError(Exception):
    pass


class Adapter:
    def __init__(self, control_url, token, targets, request=None):
        if not token or not targets:
            raise ControlError('CONFIG_REQUIRED')
        for target in targets.values():
            if not target.get('environment') or not target.get('database'):
                raise ControlError('TARGET_IDENTITY_REQUIRED')
            u = urllib.parse.urlsplit(target['url'])
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ControlError('TARGET_HTTPS_REQUIRED')
        self.control_url, self.token, self.targets = control_url.rstrip('/'), token, targets
        self.request = request or self.http
        self.lock = threading.Lock()

    @staticmethod
    def http(method, url, body=None, token=None, timeout=15):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        # Redirects must not forward credentials or silently select another app.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
                data = response.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ControlError('INVALID_RESPONSE')
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ControlError('INVALID_RESPONSE')
                return result
        except Exception:
            raise ControlError('UPSTREAM_UNAVAILABLE') from None

    def call(self, method, path, body=None, timeout=130):
        return self.request(method, self.control_url + path, body, self.token, timeout)

    def status(self):
        s = self.call('GET', '/status')
        if (s.get('mode') not in ('running', 'paused') or s.get('target') not in self.targets
                or type(s.get('in_flight')) is not int or s['in_flight'] < 0
                or not isinstance(s.get('epoch'), str) or not s['epoch'].isdigit()):
            raise ControlError('INVALID_INGRESS_STATE')
        return {'state': s['mode'].upper(), 'target': s['target'],
                'in_flight': s['in_flight'], 'epoch': s['epoch'],
                'known_targets': sorted(self.targets)}

    @staticmethod
    def paused(s):
        if s['state'] != 'PAUSED' or s['in_flight'] != 0:
            raise ControlError('PAUSE_REQUIRED')

    def health(self):
        s = self.status()
        target = self.targets[s['target']]
        token = os.environ.get(target.get('token_env', ''))
        if target.get('token_env') and not token:
            raise ControlError('TARGET_TOKEN_REQUIRED')
        ready = self.request('GET', target['url'].rstrip('/') + '/readyz', None, token, 10)
        info = self.request('GET', target['url'].rstrip('/') + '/api/info', None, token, 10)
        if (ready.get('status') != 'ok' or info.get('environment') != target['environment']
                or info.get('database', {}).get('name') != target['database']
                or info.get('writes_paused') is not False):
            raise ControlError('TARGET_NOT_READY')
        return {'healthy': True, 'target': s['target']}

    def handle(self, method, path, body):
        if method == 'GET' and path == '/status':
            return self.status()
        if method == 'GET' and path == '/healthz':
            return self.health()
        if method != 'POST' or path not in ('/pause', '/drain', '/target', '/resume'):
            raise ControlError('UNKNOWN_OPERATION')
        if not self.lock.acquire(blocking=False):
            raise ControlError('CONTROL_BUSY')
        try:
            if path == '/pause':
                result = self.call('POST', '/pause', {})
                if result.get('settled') is not True:
                    raise ControlError('NOT_SETTLED')
                s = self.status(); self.paused(s)
                return {**s, 'settled': True}
            if path == '/drain':
                timeout = body.get('timeout', 120)
                if type(timeout) not in (int, float) or not 0 <= timeout <= 120:
                    raise ControlError('INVALID_TIMEOUT')
                end = time.monotonic() + timeout
                while True:
                    s = self.status()
                    if s['state'] != 'PAUSED':
                        raise ControlError('PAUSE_REQUIRED')
                    if s['in_flight'] == 0:
                        return {**s, 'settled': True}
                    if time.monotonic() >= end:
                        return {**s, 'settled': False}
                    time.sleep(.05)
            s = self.status()
            if path == '/target':
                self.paused(s)
                target = body.get('target')
                if target not in self.targets:
                    raise ControlError('UNKNOWN_TARGET')
                if target != s['target']:
                    self.call('POST', '/target', {'target': target, 'expected_epoch': s['epoch']})
                result = self.status(); self.paused(result)
                if result['target'] != target:
                    raise ControlError('TARGET_MISMATCH')
                return result
            # Only resume a healthy expected app; this performs GETs, never probe writes.
            self.health()
            self.call('POST', '/resume', {'expected_epoch': s['epoch']})
            result = self.status()
            if result['state'] != 'RUNNING' or result['target'] != s['target']:
                raise ControlError('RESUME_MISMATCH')
            return result
        finally:
            self.lock.release()


def handler(adapter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def serve(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= 4096:
                    raise ControlError('INVALID_BODY')
                body = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(body, dict):
                    raise ControlError('INVALID_BODY')
                result = adapter.handle(self.command, self.path, body)
                code = 200
            except ControlError as e:
                code, result = 409, {'error': str(e)}
            except Exception:
                code, result = 503, {'error': 'CONTROL_FAILED'}
            data = json.dumps(result).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

        do_GET = do_POST = serve
    return Handler


def validate_alignment(targets, config):
    # The app health check must refer to the DB that the master actually migrates.
    names = {config['job']['source'], config['job']['target']}
    if not names.issubset(targets):
        raise ControlError('APP_TARGETS_MISSING')
    for name in names:
        expected = config['targets'][name]['dbname']
        if expected.startswith('REPLACE_') or targets[name]['database'] != expected:
            raise ControlError('APP_DATABASE_MISMATCH')
    if targets[config['job']['source']]['url'] == targets[config['job']['target']]['url']:
        raise ControlError('APP_ENDPOINTS_IDENTICAL')


def main():
    targets = json.loads(os.environ['CLOUD_APP_TARGETS'])
    import yaml
    with open('/etc/cloud-migration/config.yaml') as stream:
        validate_alignment(targets, yaml.safe_load(stream))
    adapter = Adapter(os.environ['INGRESS_CONTROL_URL'], os.environ['INGRESS_CONTROL_TOKEN'], targets)
    server = ThreadingHTTPServer(('127.0.0.1', 8081), handler(adapter))
    if sys.argv[1:] == ['initialize']:
        # Explicit, suspended bootstrap Job only; never resume a saved migration.
        if Path('/var/lib/worker/cutover.sqlite3').exists():
            raise ControlError('MIGRATION_STATE_EXISTS')
        s = adapter.status()
        if s['target'] != os.environ['CLOUD_INITIAL_TARGET'] or s['epoch'] != '0':
            raise ControlError('NOT_FRESH_SOURCE')
        adapter.handle('POST', '/resume', {})
        return
    if len(sys.argv) == 1:
        server.serve_forever()
    else:
        if '--approve' in sys.argv and not os.environ.get('CLOUD_APPROVAL_ID'):
            raise ControlError('APPROVAL_ID_REQUIRED')
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = subprocess.run([sys.executable, '-m', 'migration.cloud',
                '--config', '/etc/cloud-migration/config.yaml', '--state-dir', '/var/lib/worker', *sys.argv[1:]])
            # READY/approval required is a successful copy Job, not an automatic retry.
            sys.exit(0 if result.returncode == 3 else result.returncode)
        finally:
            server.shutdown()

if __name__ == '__main__':
    main()
