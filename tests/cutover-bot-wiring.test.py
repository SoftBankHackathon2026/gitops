"""Render the GitOps graph and check the runner/bot/queue contract (no cluster)."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(name):
    output = subprocess.check_output(
        ['kubectl', 'kustomize', str(ROOT / 'apps' / name)], text=True)
    return {(item['kind'], item['metadata']['name']): item
            for item in yaml.safe_load_all(output) if item}


def container_env(deployment):
    container = deployment['spec']['template']['spec']['containers'][0]
    return {item['name']: item for item in container['env']}


class CutoverBotWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = render('live-db-cutover')
        cls.bot = render('traffic-bot')
        cls.ingress = render('durable-ingress')
        cls.configs = cls.runner[('ConfigMap', 'live-db-cutover-config')]['data']

    def test_each_direction_routes_to_the_expected_database(self):
        ingress_env = container_env(self.ingress[('Deployment', 'durable-ingress')])
        routes = yaml.safe_load(ingress_env['INGRESS_TARGETS']['value'])
        for filename, text in self.configs.items():
            if not filename.endswith('.yaml'):
                continue
            with self.subTest(config=filename):
                cfg = yaml.safe_load(text)
                self.assertNotIn('worker', cfg)
                self.assertTrue(cfg['job']['job_id'].startswith('bot_'))
                self.assertNotIn('onprem', cfg['ingress']['targets'])
                for target in (cfg['job']['source'], cfg['job']['target']):
                    route = cfg['ingress']['targets'][target]
                    check = cfg['ingress']['app_checks'][target]
                    self.assertEqual(routes[route]['url'], check['url'])
                    self.assertEqual(cfg['targets'][target]['dbname'], check['database'])
                    environments = {'onprem_return': 'onprem', 'aws': 'local', 'rehearsal': 'rehearsal'}
                    self.assertEqual(check['environment'], environments[target])

    def test_runner_and_bot_share_required_control_secret(self):
        runner_env = container_env(self.runner[('Deployment', 'live-db-cutover')])
        bot_env = container_env(self.bot[('Deployment', 'traffic-bot')])
        expected = {'name': 'demo-traffic-agent', 'key': 'bot_control_token'}
        for env in (runner_env, bot_env):
            self.assertEqual(env['BOT_CONTROL_TOKEN']['valueFrom']['secretKeyRef'], expected)
        self.assertEqual(bot_env['BOT_GENERATION']['value'], 'stopped')
        self.assertFalse(runner_env['INGRESS_CONTROL_TOKEN']['valueFrom']['secretKeyRef'].get('optional'))
        selector = self.bot[('Service', 'traffic-bot-control')]['spec']['selector']
        labels = self.bot[('Deployment', 'traffic-bot')]['spec']['template']['metadata']['labels']
        self.assertEqual(selector['app'], 'traffic-bot')
        self.assertTrue(all(labels.get(key) == value for key, value in selector.items()))

    def test_bot_endpoint_matches_the_deployed_ingress(self):
        endpoint = self.bot[('ConfigMap', 'traffic-bot-target')]['data']['base-url'] + '/api/requests'
        for filename, text in self.configs.items():
            if filename.endswith('.yaml'):
                cfg = yaml.safe_load(text)
                self.assertEqual(cfg['bot']['request_endpoint'], endpoint)
                self.assertEqual(cfg['bot']['control_url'], 'http://traffic-bot-control:9091')
                self.assertEqual(cfg['bot']['token_env'], 'BOT_CONTROL_TOKEN')

    def test_platform_generated_jobs_preserve_bot_and_ingress(self):
        spec = importlib.util.spec_from_file_location('reporter', ROOT / 'apps/live-db-cutover/fleet_reporter.py')
        reporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reporter)
        cfg = yaml.safe_load(self.configs['config.yaml'])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            base = directory / 'base.yaml'
            base.write_text(yaml.safe_dump(cfg))
            for source, target in [('onprem_return', 'aws'), ('aws', 'onprem_return'),
                                   ('onprem_return', 'rehearsal')]:
                claimed = {'job_id': f'test_{source}_{target}',
                           'data_source': source, 'data_target': target}
                generated = yaml.safe_load(reporter.job_config(str(base), claimed, directory / 'jobs').read_text())
                self.assertEqual(generated['bot'], cfg['bot'])
                self.assertEqual(generated['ingress'], cfg['ingress'])
                self.assertEqual(generated['job']['source'], source)
                self.assertEqual(generated['job']['target'], target)


if __name__ == '__main__':
    unittest.main()
