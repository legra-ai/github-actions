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
        self.assertEqual(config['assignee'], 'jgeluk')

    def test_monitor_is_scheduled_in_a_different_repository(self):
        workflow = (ROOT / '.github/workflows/release-health.yml').read_text()
        self.assertIn('schedule:', workflow)
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('issues: write', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertNotIn('secrets.RELEASE_WRITER', workflow)
        self.assertIn('release-health.json', workflow)
        self.assertIn('release_monitor.py monitor', workflow)

    def test_configuration_rejects_unsupported_registry_and_missing_channels(self):
        valid = {'repository': 'owner/example', 'workflow': 'ci.yml', 'assignee': 'jgeluk',
                 'registries': {'crates': 'example'}, 'cli_assets': ['example.zip'],
                 'recovery_asset': 'release-packages.zip'}
        for changes in [{'registries': {}}, {'registries': {'unknown': 'example'}},
                        {'repository': '../bad'},
                        {'cli_assets': ['../example.zip']}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                monitor.validate_config({**valid, **changes})

    def test_crate_only_configuration_needs_no_binary_or_recovery_archive(self):
        monitor.validate_config({
            'repository': 'legra-ai/tasktree', 'workflow': 'ci.yml', 'assignee': 'jgeluk',
            'registries': {'crates': 'tasktree'}, 'cli_assets': [], 'recovery_asset': None})

    def test_language_bindings_require_preserved_archive_identity(self):
        for registries in [{'npm': '@example/node'}, {'pypi': 'example'}]:
            with self.subTest(registries=registries), self.assertRaises(ValueError):
                monitor.validate_config({
                    'repository': 'owner/example', 'workflow': 'ci.yml', 'assignee': 'jgeluk',
                    'registries': registries, 'cli_assets': [], 'recovery_asset': None})


if __name__ == '__main__':
    unittest.main()


class CargoFleetTests(unittest.TestCase):
    def test_tooling_releases_are_monitored_in_a_separate_bounded_slice(self):
        configs = monitor.load_config(ROOT / '.github/release-health-cargo.json')
        names = {config['registries']['crates'] for config in configs}
        self.assertEqual(names, {'cargo-plugin-utils', 'cargo-version-info', 'cargo-fmt-toml',
                               'cargo-nightly', 'cargo-propagate-features', 'rhusky', 'release-version'})
        existing = monitor.load_config(ROOT / '.github/release-health.json')
        self.assertTrue({c['repository'] for c in existing}.isdisjoint(c['repository'] for c in configs))
        for config in configs:
            expected = 6 if config['registries']['crates'] in names - {'cargo-plugin-utils', 'rhusky', 'release-version'} else 0
            self.assertEqual(len(config['cli_assets']), expected)
            self.assertEqual(config['assignee'], 'jgeluk')
        workflow = (ROOT / '.github/workflows/release-health.yml').read_text()
        self.assertIn('.github/release-health-cargo.json', workflow)
        self.assertIn('fail-fast: false', workflow)
        self.assertIn('MONITOR_CONFIG: ${{ matrix.config }}', workflow)
