"""Major releases require a human review for the exact workflow source and version."""

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).parents[1] / '.github/actions/prepare-cargo-release/release.py'
spec = importlib.util.spec_from_file_location('major_release', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class MajorApprovalTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'GITHUB_REPOSITORY': 'legra-ai/example',
            'GITHUB_RUN_ID': '123',
            'GITHUB_SHA': 'a' * 40,
            'RELEASE_APPROVAL_TOKEN': 'read-only-review-token',
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def review(self, **overrides):
        review = {
            'state': 'approved',
            'user': {'login': 'jgeluk', 'type': 'User'},
            'environments': [{'name': 'major-release'}],
            'comment': f'Approve major release 2.0.0 from {"a" * 40}',
        }
        review.update(overrides)
        return review

    def test_missing_review_blocks_the_major_before_version_write(self):
        with patch.object(release, 'gh_api', return_value='[]'), \
                patch.object(release, 'write_release_commit') as write, \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.complete_plan('a' * 40, '1.2.3', '2.0.0', '1.2.3')
        write.assert_not_called()

    def test_manual_and_initial_major_versions_also_require_approval(self):
        for current, latest in [('2.0.0', '1.2.3'), ('1.0.0', None)]:
            with self.subTest(current=current), patch.object(release, 'gh_api', return_value='[]'), \
                    self.assertRaisesRegex(ValueError, 'explicit approval'):
                release.complete_plan('a' * 40, current, current, latest)

    def test_stable_major_promotion_needs_its_own_explicit_approval(self):
        with patch.object(release, 'gh_api', return_value='[]'), \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.complete_plan('a' * 40, '2.0.0', '2.0.0', '2.0.0-rc.1')

    def test_minor_prerelease_promotion_does_not_require_major_approval(self):
        with patch.object(release, 'gh_api') as api, patch.object(release, 'output'):
            release.complete_plan('a' * 40, '1.3.0', '1.3.0', '1.3.0-rc.1')
        api.assert_not_called()

    def test_read_only_plan_exposes_the_gate_without_writing_or_approving(self):
        with patch.dict(os.environ, RELEASE_PLAN_ONLY='true'), \
                patch.object(release, 'gh_api') as api, \
                patch.object(release, 'write_release_commit') as write, \
                patch.object(release, 'output') as output:
            release.complete_plan('a' * 40, '1.2.3', '2.0.0', '1.2.3')
        output.assert_called_once_with(revision='a' * 40, release='true',
                                       version='2.0.0', major_approval_required='true')
        api.assert_not_called()
        write.assert_not_called()

    def test_only_exact_owner_review_in_this_run_can_authorize_a_major(self):
        invalid = [
            self.review(state='rejected'),
            self.review(user={'login': 'dependabot[bot]', 'type': 'Bot'}),
            self.review(user={'login': 'another-user', 'type': 'User'}),
            self.review(environments=[{'name': 'production'}]),
            self.review(comment=f'Approve major release 2.0.0 from {"b" * 40}'),
            self.review(comment=f'Approve major release 3.0.0 from {"a" * 40}'),
            self.review(comment='Ship it'),
        ]
        for review in invalid:
            with self.subTest(review=review), \
                    patch.object(release, 'gh_api', return_value=json.dumps([review])), \
                    self.assertRaisesRegex(ValueError, 'explicit approval'):
                release.require_major_approval('2.0.0')
        with patch.object(release, 'gh_api', return_value=json.dumps([self.review()])) as api:
            release.require_major_approval('2.0.0')
        self.assertEqual(api.call_args.args, ('repos/legra-ai/example/actions/runs/123/approvals',))
        self.assertEqual(api.call_args.kwargs['env']['GH_TOKEN'], 'read-only-review-token')

    def test_patch_and_minor_releases_do_not_require_review(self):
        for version in ['1.2.4', '1.3.0']:
            with self.subTest(version=version), patch.object(release, 'gh_api') as api, \
                    patch.object(release, 'write_release_commit', return_value='prepared'), \
                    patch.object(release, 'output'):
                release.complete_plan('a' * 40, '1.2.3', version, '1.2.3')
            api.assert_not_called()

    def test_resume_of_pending_major_is_not_an_approval_bypass(self):
        with patch.object(release, 'gh_api', return_value='[]'), \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.complete_plan('tagged', '2.0.0', '2.0.0', '1.2.3')

    def test_rejected_review_cannot_reuse_an_earlier_approval(self):
        reviews = [self.review(), self.review(state='rejected')]
        with patch.object(release, 'gh_api', return_value=json.dumps(reviews)), \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.require_major_approval('2.0.0')

    def test_exact_approval_allows_the_planned_version_write(self):
        with patch.object(release, 'gh_api', return_value=json.dumps([self.review()])), \
                patch.object(release, 'write_release_commit', return_value='prepared') as write, \
                patch.object(release, 'output') as output:
            release.complete_plan('a' * 40, '1.2.3', '2.0.0', '1.2.3')
        write.assert_called_once_with('a' * 40, '2.0.0')
        output.assert_called_once_with(revision='prepared', release='true', version='2.0.0')

    def test_review_lookup_failure_is_fatal(self):
        with patch.object(release, 'gh_api', side_effect=RuntimeError('403')), \
                self.assertRaisesRegex(RuntimeError, '403'):
            release.require_major_approval('2.0.0')


if __name__ == '__main__':
    unittest.main()
