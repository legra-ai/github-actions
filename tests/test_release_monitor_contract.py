"""The independent scheduler must actually inspect the declared install channels."""

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]
ACTION = ROOT / '.github/actions/monitor-release'
sys.path.insert(0, str(ACTION))
SPEC = importlib.util.spec_from_file_location('release_monitor', ACTION / 'release_monitor.py')
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class ContractTests(unittest.TestCase):
    def test_dotenvage_declares_every_published_channel(self):
        configs = monitor.load_config(ROOT / '.github/release-health.json')
        config = next(item for item in configs if item['repository'] == 'legra-ai/dotenvage')
        self.assertEqual(config['registries'], {
            'crates': 'dotenvage', 'npm': '@dotenvage/node', 'pypi': 'dotenvage'})
        self.assertEqual(len(config['cli_assets']), 6)
        self.assertEqual(config['recovery_asset'], 'release-packages.zip')

    def test_monitor_is_scheduled_in_a_different_repository(self):
        workflow = (ROOT / '.github/workflows/release-health.yml').read_text()
        self.assertIn('schedule:', workflow)
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('issues: write', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertNotIn('secrets.RELEASE_WRITER', workflow)
        self.assertIn('release_monitor.py monitor .github/release-health.json', workflow)

    def test_configuration_rejects_unsupported_registry_and_missing_channels(self):
        valid = {'repository': 'owner/example', 'workflow': 'ci.yml',
                 'registries': {'crates': 'example'}, 'cli_assets': ['example.zip'],
                 'recovery_asset': 'release-packages.zip'}
        for changes in [{'registries': {}}, {'registries': {'unknown': 'example'}},
                        {'cli_assets': []}, {'repository': '../bad'},
                        {'cli_assets': ['../example.zip']}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                monitor.validate_config({**valid, **changes})


if __name__ == '__main__':
    unittest.main()
