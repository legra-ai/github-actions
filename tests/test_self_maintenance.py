"""The policy repository must use its own tested dependency merge contract."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SelfMaintenanceTests(unittest.TestCase):
    def test_only_successful_complete_tests_can_authorize_the_app_merger(self):
        workflow = (ROOT / '.github/workflows/dependabot-merge.yml').read_text()
        self.assertIn('workflows: [Release action tests]', workflow)
        self.assertIn('types: [completed]', workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn('repositories: ${{ github.event.repository.name }}', workflow)
        self.assertRegex(workflow, r'actions/create-github-app-token@[0-9a-f]{40} # v3')
        self.assertIn('uses: ./.github/actions/merge-tested-dependabot', workflow)
        self.assertRegex(workflow, r'actions/checkout@[0-9a-f]{40} # v7')
        self.assertIn('ref: ${{ job.workflow_sha }}', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertNotIn('github.event.workflow_run.head_sha', workflow)
        self.assertNotIn('github.event.workflow_run.head_branch', workflow)
        self.assertIn('secrets.RELEASE_MERGER_APP_ID', workflow)
        self.assertIn('secrets.RELEASE_MERGER_APP_KEY', workflow)
        self.assertNotIn('secrets.RELEASE_WRITER', workflow)
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            self.assertNotIn('--auto --rebase', path.read_text())
            self.assertNotIn('gh pr review --approve', path.read_text())

    def test_merge_manifest_has_only_the_reviewed_repository_permissions(self):
        manifest = json.loads((ROOT / '.github/apps/dependency-merger-manifest.json').read_text())
        self.assertEqual(manifest['default_permissions'],
                         {'contents': 'write', 'pull_requests': 'write', 'administration': 'read'})
        self.assertFalse(manifest['public'])
        self.assertFalse(manifest['hook_attributes']['active'])
        self.assertEqual(manifest['default_events'], [])

    def test_dependency_updates_and_title_enforcement_are_daily_and_trusted(self):
        config = (ROOT / '.github/dependabot.yml').read_text()
        self.assertIn('interval: daily', config)
        self.assertIn('security-updates:', config)
        self.assertIn('prefix: "ci(deps)"', config)
        self.assertNotIn('include: "scope"', config)
        title = (ROOT / '.github/workflows/conventional-commits.yml').read_text()
        self.assertIn('pull_request_target:', title)
        self.assertIn('edited', title)
        self.assertRegex(title, r'conventional-commit@[0-9a-f]{40}')
        self.assertNotIn('actions/checkout', title)


if __name__ == '__main__':
    unittest.main()
