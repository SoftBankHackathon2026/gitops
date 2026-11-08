"""Prevent immutable StatefulSet edits and WaitForFirstConsumer sync deadlocks."""
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def render(path):
    return list(yaml.safe_load_all(subprocess.check_output(
        ['kubectl', 'kustomize', str(ROOT / path)], text=True)))


class RedisStorageTests(unittest.TestCase):
    def test_existing_claim_is_adopted_without_changing_statefulset_template(self):
        base = render('apps/service-migration-aws')
        self.assertFalse(any(d['kind'] == 'PersistentVolumeClaim' for d in base))
        original = next(d for d in base if d['kind'] == 'StatefulSet')
        for path in ('apps/service-migration-aws-active', 'apps/service-migration-repeat-demo'):
            with self.subTest(path=path):
                docs = render(path)
                redis = next(d for d in docs if d['kind'] == 'StatefulSet')
                claim = next(d for d in docs if d['kind'] == 'PersistentVolumeClaim')
                template = redis['spec']['volumeClaimTemplates'][0]
                self.assertEqual(redis['spec']['volumeClaimTemplates'],
                                 original['spec']['volumeClaimTemplates'])
                self.assertEqual(redis['spec']['replicas'], 1)
                self.assertEqual(claim['metadata']['name'],
                                 f"{template['metadata']['name']}-{redis['metadata']['name']}-0")
                self.assertEqual(claim['spec']['accessModes'], template['spec']['accessModes'])
                self.assertEqual(claim['spec']['resources'], template['spec']['resources'])
                self.assertEqual(claim['spec']['storageClassName'], 'oneaction-monitoring-gp3')
                annotations = claim['metadata']['annotations']
                self.assertEqual(annotations.get('argocd.argoproj.io/sync-wave', '0'),
                                 redis['metadata'].get('annotations', {}).get(
                                     'argocd.argoproj.io/sync-wave', '0'))
                self.assertEqual(set(annotations['argocd.argoproj.io/sync-options'].split(',')),
                                 {'Prune=false', 'Delete=false'})


if __name__ == '__main__':
    unittest.main()
