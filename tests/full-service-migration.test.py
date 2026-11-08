"""Render the full-service migration graph; never access a cluster or secrets."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(path):
    output = subprocess.check_output(['kubectl', 'kustomize', str(ROOT / path)], text=True)
    return {(doc['kind'], doc['metadata']['name']): doc
            for doc in yaml.safe_load_all(output) if doc}


def env(doc):
    return {item['name']: item for item in
            doc['spec']['template']['spec']['containers'][0]['env']}


def secret(values, name):
    ref = values[name]['valueFrom']['secretKeyRef']
    assert not ref.get('optional', False), name
    return ref


class FullServiceMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = render('apps/service-migration-aws')
        cls.active = render('apps/service-migration-aws-active')
        cls.source = render('apps/durable-ingress-full-aws')
        cls.runner = render('apps/live-db-cutover-full-aws')
        cls.cfg = yaml.safe_load(cls.runner[('ConfigMap', 'live-db-cutover-config')]['data']['config.full-aws.yaml'])

    def test_staged_defaults_do_not_start_services_or_change_current_jobs(self):
        self.assertEqual(self.base[('Deployment', 'service-receipt')]['spec']['replicas'], 0)
        self.assertEqual(self.base[('StatefulSet', 'service-redis')]['spec']['replicas'], 0)
        self.assertFalse(any(kind == 'Ingress' for kind, _ in self.base))
        apps = render('argocd')
        self.assertEqual(apps[('Application', 'service-migration-aws')]['spec']['source']['path'], 'apps/service-migration-aws')
        old = render('apps/live-db-cutover')
        self.assertEqual(env(old[('Deployment', 'live-db-cutover')])['MIGRATION_CONFIG']['value'], '/etc/live-cutover/config.yaml')
        self.assertNotIn('full_migration', yaml.safe_load(old[('ConfigMap', 'live-db-cutover-config')]['data']['config.yaml']))

    def test_full_activation_deploys_the_same_app_artifact_on_eks(self):
        graph = render('argocd-full-service')
        self.assertEqual(graph[('Application', 'sample-app-aws')]['spec']['sources'][0]['path'], 'apps/sample-app/runtime/full-aws')
        self.assertEqual(graph[('Application', 'service-migration-aws')]['spec']['source']['path'], 'apps/service-migration-aws-active')
        rendered_app = render('apps/sample-app/runtime/full-aws')
        app = rendered_app[('Rollout', 'sample-app')]
        image = app['spec']['template']['spec']['containers'][0]['image']
        for resource, name in [(self.active, 'service-receipt'), (self.source, 'durable-ingress')]:
            self.assertEqual(resource[('Deployment', name)]['spec']['template']['spec']['containers'][0]['image'], image)
        version = self.cfg['full_migration']['destination_app_version']
        self.assertEqual(image, 'docker.io/kty1021/sample-app:' + version)
        self.assertEqual(app['spec']['template']['metadata']['labels']['ghost.dev/migration-version'], version)
        selector = rendered_app[('Service', 'sample-app')]['spec']['selector']
        self.assertEqual(selector['ghost.dev/migration-version'], version)
        old_app = render('apps/sample-app/runtime/aws')[('Rollout', 'sample-app')]
        old_labels = old_app['spec']['template']['metadata']['labels']
        self.assertFalse(all(old_labels.get(key) == value for key, value in selector.items()))
        values = env(app)
        self.assertEqual(values['DEPLOY_ENV']['value'], 'aws')
        self.assertEqual(secret(values, 'DATABASE_URL'), {'name': 'sample-app-db', 'key': 'database-url'})
        self.assertEqual(values['PGSSLMODE']['value'], 'verify-full')
        self.assertEqual(values['REQUEST_API_AUTH']['value'], 'required')

    def test_platform_jobs_map_the_approved_environment_and_single_app(self):
        spec = importlib.util.spec_from_file_location('full_reporter', ROOT / 'apps/live-db-cutover/fleet_reporter.py')
        reporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reporter)
        self.assertEqual(self.cfg['platform_data_targets'], {'onprem': 'onprem_return', 'aws': 'aws'})
        self.assertEqual(self.cfg['platform_apps'], ['sample-app-onprem', 'sample-app', 'hackathon/Deployment/sample-app', 'hackathon/Rollout/sample-app'])
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            base = directory / 'base.yaml'
            base.write_text(yaml.safe_dump(self.cfg))
            claimed = {'job_id': 'full_platform_001', 'source_env': 'onprem', 'target_env': 'aws',
                       'data_source': 'onprem', 'data_target': 'aws', 'apps': ['sample-app']}
            for alias in self.cfg['platform_apps']:
                with self.subTest(alias=alias):
                    selected = dict(claimed, apps=[alias])
                    created = yaml.safe_load(reporter.job_config(str(base), selected, directory / 'jobs').read_text())
                    self.assertEqual((created['job']['source'], created['job']['target']), ('onprem_return', 'aws'))
                    self.assertEqual(created['full_migration'], self.cfg['full_migration'])
            for invalid in [dict(claimed, apps=[]), dict(claimed, apps=['sample-app-onprem', 'ai-agent']),
                            dict(claimed, apps=['other/Deployment/sample-app']),
                            dict(claimed, source_env='aws', target_env='onprem', data_source='aws', data_target='onprem')]:
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        reporter.job_config(str(base), invalid, directory / 'jobs')

    def test_active_destination_is_cloud_only_and_standby(self):
        deployment = self.active[('Deployment', 'service-receipt')]
        values = env(deployment)
        self.assertEqual(deployment['spec']['replicas'], 1)
        self.assertEqual(values['INGRESS_STANDBY']['value'], 'true')
        self.assertEqual(values['INGRESS_INITIAL_TARGET']['value'], 'aws_eks')
        targets = json.loads(values['INGRESS_TARGETS']['value'])
        self.assertEqual(list(targets), ['aws_eks'])
        check = self.cfg['ingress']['app_checks']['aws']
        self.assertEqual(targets['aws_eks']['url'], check['url'])
        self.assertEqual(check['environment'], 'aws')
        self.assertEqual(check['database'], self.cfg['targets']['aws']['dbname'])
        self.assertEqual(targets['aws_eks']['token_env'], check['token_env'])
        self.assertNotIn('onprem', targets['aws_eks']['url'])

    def test_separate_api_control_auth_and_forward_target_match(self):
        values = env(self.active[('Deployment', 'service-receipt')])
        runner = env(self.runner[('Deployment', 'live-db-cutover')])
        source = env(self.source[('Deployment', 'durable-ingress')])
        full = self.cfg['full_migration']
        self.assertEqual(secret(values, 'INGRESS_CONTROL_TOKEN'), secret(runner, full['destination_token_env']))
        self.assertEqual(secret(values, 'INGRESS_API_TOKEN'), secret(runner, full['destination_api_token_env']))
        self.assertNotEqual(secret(values, 'INGRESS_CONTROL_TOKEN')['key'], secret(values, 'INGRESS_API_TOKEN')['key'])
        forwards = json.loads(source['INGRESS_FORWARD_TARGETS']['value'])
        target = forwards[full['forward_target']]
        self.assertEqual(target['url'] + '/control', full['destination_control_url'])
        self.assertEqual(secret(source, target['token_env']), secret(values, 'INGRESS_API_TOKEN'))
        self.assertFalse(secret(source, 'INGRESS_CONTROL_TOKEN').get('optional'))
        self.assertEqual(values['INGRESS_EXPOSE_CONTROL']['value'], 'true')

    def test_old_images_fail_closed_instead_of_ignoring_standby_or_forwarding(self):
        for graph, name in [(self.active, 'service-receipt'), (self.source, 'durable-ingress')]:
            container = graph[('Deployment', name)]['spec']['template']['spec']['containers'][0]
            self.assertEqual(container['command'], ['node', '-e'])
            self.assertIn('HANDOFF_PROTOCOL_VERSION !== 1', container['args'][0])
            self.assertIn('HANDOFF_IMAGE_REQUIRED', container['args'][0])

    def test_https_ingress_does_not_publish_redis_or_raw_control(self):
        public = self.active[('Ingress', 'service-receipt')]
        annotations = public['metadata']['annotations']
        self.assertEqual(annotations['alb.ingress.kubernetes.io/ssl-redirect'], '443')
        self.assertIn('certificate-arn', ' '.join(annotations))
        for rule in public['spec']['rules']:
            self.assertEqual(rule['host'], 'service-migration.hackerthon.yubin.dev')
            for path in rule['http']['paths']:
                self.assertEqual(path['backend']['service'], {'name': 'service-receipt', 'port': {'number': 80}})
        for (kind, name), doc in self.active.items():
            if kind == 'Service':
                self.assertEqual(doc['spec'].get('type', 'ClusterIP'), 'ClusterIP', name)
                self.assertNotIn(9092, [port['port'] for port in doc['spec']['ports']])
        redis_policy = self.active[('NetworkPolicy', 'service-redis')]['spec']['ingress']
        self.assertEqual(redis_policy[0]['from'], [{'podSelector': {'matchLabels': {'app': 'service-receipt'}}}])

    def test_redis_durable_storage_and_public_route_are_explicit(self):
        redis = self.active[('StatefulSet', 'service-redis')]
        self.assertEqual(redis['spec']['replicas'], 1)
        self.assertEqual(redis['spec']['volumeClaimTemplates'][0]['spec']['accessModes'], ['ReadWriteOnce'])
        args = redis['spec']['template']['spec']['containers'][0]['args']
        for option, value in [('--appendonly', 'yes'), ('--appendfsync', 'always'), ('--maxmemory-policy', 'noeviction')]:
            self.assertEqual(args[args.index(option) + 1], value)
        self.assertEqual(self.cfg['ingress']['targets']['aws'], 'aws_eks')
        self.assertNotIn('traffic', self.cfg)
        self.assertEqual(self.cfg['full_migration']['destination_receipt_url'] + '/control', self.cfg['full_migration']['destination_control_url'])
        self.assertEqual(env(self.runner[('Deployment', 'live-db-cutover')])['MIGRATION_CONFIG']['value'], '/etc/live-cutover/config.full-aws.yaml')


if __name__ == '__main__':
    unittest.main()
