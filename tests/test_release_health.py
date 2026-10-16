"""Release health must reflect public installation results, not just green CI."""

from datetime import datetime, timedelta, timezone
import pathlib
import sys
import unittest
from unittest.mock import patch

ACTION = pathlib.Path(__file__).parents[1] / '.github/actions/monitor-release'
sys.path.insert(0, str(ACTION))
from release_health import Inspector, Report
from release_alerts import reconcile

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
CONFIG = {
    'repository': 'owner/example', 'workflow': 'ci.yml',
    'registries': {'crates': 'example', 'npm': '@example/node', 'pypi': 'example'},
    'cli_assets': ['example-target.zip'], 'recovery_asset': 'release-packages.zip',
}


class FakeAPI:
    def __init__(self):
        self.writes = []
        old = (NOW - timedelta(days=3)).isoformat()
        self.responses = {
            'repos/owner/example/contents/Cargo.toml?ref=main': '[package]\nversion="1.2.3"',
            'repos/owner/example/actions/workflows/ci.yml': {'state': 'active', 'created_at': old},
            'repos/owner/example/actions/workflows/ci.yml/runs?branch=main&per_page=1': {
                'workflow_runs': [{'status': 'completed', 'conclusion': 'success',
                                   'created_at': old, 'html_url': 'https://example/run'}]},
            'repos/owner/example/actions/workflows/ci.yml/runs?branch=main&event=schedule&per_page=1': {
                'workflow_runs': [{'created_at': NOW.isoformat()}]},
            'repos/owner/example/releases/tags/v1.2.3': {
                'draft': False, 'created_at': old, 'assets': [], 'tag_name': 'v1.2.3'},
            'repos/owner/example/compare/v1.2.3...main?per_page=100&page=1': {'commits': []},
        }

    def github(self, path, **kwargs):
        if kwargs:
            self.writes.append((path, kwargs))
            return {}
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    def text(self, path):
        return self.github(path)


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.inspector = Inspector(self.api, CONFIG, NOW)
        self.registries = patch.object(self.inspector, 'check_registries')
        self.cli = patch.object(self.inspector, 'check_cli')
        self.registries.start()
        self.cli.start()
        self.addCleanup(self.registries.stop)
        self.addCleanup(self.cli.stop)

    def test_green_ci_does_not_hide_missing_registry_version(self):
        self.inspector.check_registries.side_effect = RuntimeError('npm 1.2.3 is missing')
        report = self.inspector.inspect()
        self.assertEqual(report.status, 'unhealthy')
        self.assertIn('npm 1.2.3 is missing', report.body)

    def test_healthy_requires_all_installation_checks(self):
        self.assertEqual(self.inspector.inspect().status, 'healthy')
        self.inspector.check_registries.assert_called_once()
        self.inspector.check_cli.assert_called_once()

    def test_broken_cli_download_is_unhealthy(self):
        self.inspector.check_cli.side_effect = RuntimeError('CLI download HTTP 404')
        self.assertIn('CLI download HTTP 404', self.inspector.inspect().body)

    def test_disabled_workflow_is_detected_independently(self):
        self.api.responses['repos/owner/example/actions/workflows/ci.yml']['state'] = 'disabled_manually'
        self.assertEqual(self.inspector.inspect().status, 'unhealthy')

    def test_failed_main_run_is_unhealthy_even_when_packages_exist(self):
        path = 'repos/owner/example/actions/workflows/ci.yml/runs?branch=main&per_page=1'
        self.api.responses[path]['workflow_runs'][0]['conclusion'] = 'failure'
        self.assertIn('https://example/run', self.inspector.inspect().body)

    def test_expired_credentials_fail_closed(self):
        self.api.responses['repos/owner/example/actions/workflows/ci.yml'] = RuntimeError('HTTP 401')
        report = self.inspector.inspect()
        self.assertEqual(report.status, 'unhealthy')
        self.assertIn('HTTP 401', report.body)

    def test_recent_draft_is_pending_not_healthy(self):
        self.api.responses['repos/owner/example/releases/tags/v1.2.3'].update(
            draft=True, created_at=NOW.isoformat())
        self.assertEqual(self.inspector.inspect().status, 'pending')

    def test_stale_draft_is_unhealthy(self):
        self.api.responses['repos/owner/example/releases/tags/v1.2.3']['draft'] = True
        self.assertEqual(self.inspector.inspect().status, 'unhealthy')

    def test_missing_scheduler_heartbeat_is_unhealthy(self):
        path = 'repos/owner/example/actions/workflows/ci.yml/runs?branch=main&event=schedule&per_page=1'
        self.api.responses[path]['workflow_runs'] = []
        self.assertIn('scheduled', self.inspector.inspect().body)

    def test_unreleased_fix_on_main_is_not_hidden_by_existing_packages(self):
        path = 'repos/owner/example/compare/v1.2.3...main?per_page=100&page=1'
        self.api.responses[path]['commits'] = [{'commit': {
            'message': 'fix(core): repair', 'committer': {
                'date': (NOW - timedelta(days=3)).isoformat()}}}]
        self.assertIn('unreleased', self.inspector.inspect().body)


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.path = 'repos/owner/monitor/issues?state=all&per_page=100&page=1'
        self.api.responses[self.path] = []

    def test_unhealthy_opens_one_actionable_issue(self):
        report = Report('owner/example', 'unhealthy', ['npm version missing'])
        reconcile(self.api, 'owner/monitor', report)
        self.assertEqual(len(self.api.writes), 1)
        self.assertIn('npm version missing', self.api.writes[0][1]['body']['body'])

    def existing(self, state='open'):
        self.api.responses[self.path] = [{
            'number': 7, 'state': state, 'title': 'Release health: owner/example',
            'body': '<!-- release-health:owner/example -->\nold',
        }]

    def test_pending_release_does_not_close_an_existing_alert(self):
        self.existing()
        reconcile(self.api, 'owner/monitor', Report('owner/example', 'pending', []))
        self.assertEqual(self.api.writes, [])

    def test_fully_verified_recovery_closes_existing_alert(self):
        self.existing()
        reconcile(self.api, 'owner/monitor', Report('owner/example', 'healthy', []))
        self.assertEqual(self.api.writes[0][1]['body']['state'], 'closed')

    def test_failure_reopens_the_same_issue_instead_of_creating_duplicates(self):
        self.existing('closed')
        reconcile(self.api, 'owner/monitor', Report('owner/example', 'unhealthy', ['failed']))
        self.assertEqual(len(self.api.writes), 1)
        self.assertEqual(self.api.writes[0][0], 'repos/owner/monitor/issues/7')
        self.assertEqual(self.api.writes[0][1]['body']['state'], 'open')


if __name__ == '__main__':
    unittest.main()
