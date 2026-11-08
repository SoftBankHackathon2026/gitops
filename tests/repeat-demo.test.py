"""Opt-in repeat demo graph and process-lifecycle contracts (no cluster access)."""
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def render(path):
    return list(yaml.safe_load_all(subprocess.check_output(
        ['kubectl', 'kustomize', str(ROOT / path)], text=True)))


class RepeatDemoTests(unittest.TestCase):
    def test_base_onprem_graph_retains_all_original_applications(self):
        originals = []
        for path in (ROOT / 'argocd/onprem').glob('*.yaml'):
            if path.name != 'kustomization.yaml':
                originals.extend(yaml.safe_load_all(path.read_text()))
        self.assertEqual(sorted(originals, key=lambda d: d['metadata']['name']),
                         sorted(render('argocd/onprem'), key=lambda d: d['metadata']['name']))

    def test_supervisor_is_opt_in_and_no_management_service(self):
        for prefix, name, role in [('traffic-bot', 'traffic-bot', 'bot'),
                                  ('durable-ingress', 'durable-ingress', 'source'),
                                  ('service-migration', 'service-receipt', 'destination')]:
            docs = render(f'apps/{prefix}-repeat-demo')
            pod = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == name)
            container = pod['spec']['template']['spec']['containers'][0]
            self.assertEqual(container['command'], ['node', 'packages/demo-supervisor.js', 'serve'])
            self.assertFalse(container.get('args'))
            env = {e['name']: e.get('value') for e in container['env']}
            self.assertEqual(env['DEMO_ROLE'], role)
            self.assertEqual(env['DEMO_RESET_ENABLED'], 'true')
            self.assertIn('exec', container['livenessProbe'])
            self.assertNotIn('httpGet', container['livenessProbe'])
            self.assertIn('httpGet', container['readinessProbe'])
            for service in (d for d in docs if d['kind'] == 'Service'):
                self.assertNotIn(9093, [p['port'] for p in service['spec']['ports']])
        self.assertNotIn('DEMO_RESET_ENABLED', subprocess.check_output(
            ['kubectl', 'kustomize', str(ROOT / 'apps/durable-ingress')], text=True))

    def test_graphs_select_repeat_overlays_and_runner_gate(self):
        docs = render('argocd-repeat-demo-onprem') + render('argocd-repeat-demo-aws')
        for name, expected in [('traffic-bot', 'traffic-bot'), ('durable-ingress', 'durable-ingress'),
                               ('live-db-cutover', 'live-db-cutover'), ('service-migration-aws', 'service-migration')]:
            app = next(d for d in docs if d['metadata']['name'] == name)
            self.assertEqual(app['spec']['source']['path'], f'apps/{expected}-repeat-demo')
        runner = render('apps/live-db-cutover-repeat-demo')
        code = next(d['data']['fleet_reporter.py'] for d in runner
                    if d['kind'] == 'ConfigMap' and 'fleet_reporter.py' in d.get('data', {}))
        self.assertIn('from migration.demo_reset import command_lease', code)
        self.assertIn('return reject_during_demo_reset(args, token, all_jobs=True)', code)


if __name__ == '__main__':
    unittest.main()
