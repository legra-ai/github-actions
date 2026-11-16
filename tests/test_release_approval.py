"""Minor and major releases require a human review for the exact level, version and source."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).parents[1] / '.github/actions/prepare-cargo-release/release.py'
spec = importlib.util.spec_from_file_location('release_approval', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class BumpLevelTests(unittest.TestCase):
    def test_levels_compare_against_the_published_baseline(self):
        for version, latest, level in [
            (None, '1.2.3', 'none'),
            ('1.2.4', '1.2.3', 'patch'),
            ('1.3.0', '1.2.3', 'minor'),
            ('2.0.0', '1.2.3', 'major'),
            ('1.0.0', None, 'major'),
            ('0.1.0', None, 'minor'),
            ('0.0.1', None, 'patch'),
            ('0.5.0', '0.4.9', 'minor'),
            ('2.0.0', '2.0.0-rc.1', 'major'),
            ('1.3.0', '1.3.0-rc.1', 'minor'),
            ('1.3.1', '1.3.1-rc.1', 'patch'),
            ('1.3.0-rc.2', '1.3.0-rc.1', 'patch'),
            ('1.3.0-alpha.1', '1.2.3', 'minor'),
            ('2.0.0-alpha.1', '1.2.3', 'major'),
        ]:
            with self.subTest(version=version, latest=latest):
                self.assertEqual(release.bump_level(version, latest), level)


class ReleaseApprovalTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            'GITHUB_REPOSITORY': 'legra-ai/example',
            'GITHUB_RUN_ID': '123',
            'GITHUB_SHA': 'a' * 40,
            'RELEASE_APPROVAL_TOKEN': 'read-only-review-token',
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def review(self, level='major', version='2.0.0', **overrides):
        review = {
            'state': 'approved',
            'user': {'login': 'jgeluk', 'type': 'User'},
            'environments': [{'name': 'release-approval'}],
            'comment': f'Approve {level} release {version} from {"a" * 40}',
        }
        review.update(overrides)
        return review

    def test_missing_review_blocks_minor_and_major_before_version_write(self):
        for version in ['1.3.0', '2.0.0']:
            with self.subTest(version=version), patch.object(release, 'gh_api', return_value='[]'), \
                    patch.object(release, 'write_release_commit') as write, \
                    self.assertRaisesRegex(ValueError, 'explicit approval'):
                release.complete_plan('a' * 40, '1.2.3', version, '1.2.3')
            write.assert_not_called()

    def test_manual_and_initial_releases_also_require_approval(self):
        for current, latest in [('2.0.0', '1.2.3'), ('1.3.0', '1.2.3'), ('1.0.0', None), ('0.1.0', None)]:
            with self.subTest(current=current), patch.object(release, 'gh_api', return_value='[]'), \
                    self.assertRaisesRegex(ValueError, 'explicit approval'):
                release.complete_plan('a' * 40, current, current, latest)

    def test_stable_promotions_need_their_own_explicit_approval(self):
        for version in ['2.0.0', '1.3.0']:
            with self.subTest(version=version), patch.object(release, 'gh_api', return_value='[]'), \
                    self.assertRaisesRegex(ValueError, 'explicit approval'):
                release.complete_plan('a' * 40, version, version, f'{version}-rc.1')

    def test_read_only_plan_exposes_the_level_and_gate_without_writing_or_approving(self):
        for version, level, required in [('2.0.0', 'major', 'true'), ('1.3.0', 'minor', 'true'),
                                         ('1.2.4', 'patch', 'false')]:
            with self.subTest(version=version), patch.dict(os.environ, RELEASE_PLAN_ONLY='true'), \
                    patch.object(release, 'gh_api') as api, \
                    patch.object(release, 'write_release_commit') as write, \
                    patch.object(release, 'output') as output:
                release.complete_plan('a' * 40, '1.2.3', version, '1.2.3')
            output.assert_called_once_with(revision='a' * 40, release='true', version=version,
                                           bump_level=level, approval_required=required)
            api.assert_not_called()
            write.assert_not_called()

    def test_read_only_plan_without_a_release_needs_no_approval(self):
        with patch.dict(os.environ, RELEASE_PLAN_ONLY='true'), patch.object(release, 'output') as output:
            release.complete_plan('a' * 40, '1.2.3', None, '1.2.3')
        output.assert_called_once_with(revision='a' * 40, release='false', version='1.2.3',
                                       bump_level='none', approval_required='false')

    def test_only_exact_owner_review_in_this_run_can_authorize_a_release(self):
        for level, version, other_level in [('major', '2.0.0', 'minor'), ('minor', '1.3.0', 'major')]:
            invalid = [
                self.review(level, version, state='rejected'),
                self.review(level, version, user={'login': 'dependabot[bot]', 'type': 'Bot'}),
                self.review(level, version, user={'login': 'another-user', 'type': 'User'}),
                self.review(level, version, environments=[{'name': 'production'}]),
                self.review(level, version, environments=[{'name': 'major-release'}]),
                self.review(level, version, comment=f'Approve {level} release {version} from {"b" * 40}'),
                self.review(level, version, comment=f'Approve {level} release 3.0.0 from {"a" * 40}'),
                self.review(other_level, version),
                self.review(level, version, comment='Ship it'),
            ]
            for review in invalid:
                with self.subTest(review=review), \
                        patch.object(release, 'gh_api', return_value=json.dumps([review])), \
                        self.assertRaisesRegex(ValueError, 'explicit approval'):
                    release.require_release_approval(level, version)
            with patch.object(release, 'gh_api',
                              return_value=json.dumps([self.review(level, version)])) as api:
                release.require_release_approval(level, version)
            self.assertEqual(api.call_args.args, ('repos/legra-ai/example/actions/runs/123/approvals',))
            self.assertEqual(api.call_args.kwargs['env']['GH_TOKEN'], 'read-only-review-token')

    def test_patch_releases_are_fully_automatic(self):
        for current, version, latest in [('1.2.3', '1.2.4', '1.2.3'), ('1.3.0-rc.1', '1.3.0-rc.2', '1.3.0-rc.1')]:
            with self.subTest(version=version), patch.object(release, 'gh_api') as api, \
                    patch.object(release, 'write_release_commit', return_value='prepared'), \
                    patch.object(release, 'output'):
                release.complete_plan('a' * 40, current, version, latest)
            api.assert_not_called()

    def test_patch_and_none_levels_have_no_approval(self):
        for level in ['patch', 'none', 'Major']:
            with self.subTest(level=level), patch.object(release, 'gh_api') as api, \
                    self.assertRaisesRegex(ValueError, 'No approval exists'):
                release.require_release_approval(level, '1.2.4')
            api.assert_not_called()

    def test_resume_of_pending_minor_or_major_is_not_an_approval_bypass(self):
        for version in ['2.0.0', '1.3.0']:
            with self.subTest(version=version), patch.object(release, 'gh_api', return_value='[]'), \
                    self.assertRaisesRegex(ValueError, 'explicit approval'):
                release.complete_plan('tagged', version, version, '1.2.3')

    def test_rejected_review_cannot_reuse_an_earlier_approval(self):
        reviews = [self.review('minor', '1.3.0'), self.review('minor', '1.3.0', state='rejected')]
        with patch.object(release, 'gh_api', return_value=json.dumps(reviews)), \
                self.assertRaisesRegex(ValueError, 'rejected review'):
            release.require_release_approval('minor', '1.3.0')

    def test_exact_approval_allows_the_planned_version_write(self):
        for level, version in [('major', '2.0.0'), ('minor', '1.3.0')]:
            with self.subTest(level=level), \
                    patch.object(release, 'gh_api', return_value=json.dumps([self.review(level, version)])), \
                    patch.object(release, 'write_release_commit', return_value='prepared') as write, \
                    patch.object(release, 'output') as output:
                release.complete_plan('a' * 40, '1.2.3', version, '1.2.3')
            write.assert_called_once_with('a' * 40, version)
            output.assert_called_once_with(revision='prepared', release='true', version=version)

    def test_approval_job_verifies_the_planned_level_and_version(self):
        with patch.dict(os.environ, RELEASE_BUMP_LEVEL='minor', RELEASE_VERSION='1.3.0'), \
                patch.object(release, 'gh_api', return_value=json.dumps([self.review('minor', '1.3.0')])):
            release.verify_approval()
        with patch.dict(os.environ, RELEASE_BUMP_LEVEL='minor', RELEASE_VERSION='1.3.0'), \
                patch.object(release, 'gh_api', return_value=json.dumps([self.review('major', '1.3.0')])), \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.verify_approval()

    def test_summary_names_the_exact_comment_for_gated_levels_only(self):
        for level, required, expected in [
            ('minor', 'true', f'Approve minor release 1.3.0 from {"a" * 40}'),
            ('patch', 'false', None),
        ]:
            with self.subTest(level=level), tempfile.NamedTemporaryFile('r', suffix='.md') as summary, \
                    patch.dict(os.environ, GITHUB_STEP_SUMMARY=summary.name, PROPOSED_VERSION='1.3.0',
                               BUMP_LEVEL=level, APPROVAL_REQUIRED=required, WORKFLOW_SOURCE='a' * 40):
                release.write_summary()
                text = summary.read()
            self.assertIn(f'Proposed version: 1.3.0 ({level})', text)
            if expected:
                self.assertIn('release-approval environment', text)
                self.assertIn(expected + '\n', text)
            else:
                self.assertNotIn('Approve', text)

    def test_review_lookup_failure_is_fatal(self):
        with patch.object(release, 'gh_api', side_effect=RuntimeError('403')), \
                self.assertRaisesRegex(RuntimeError, '403'):
            release.require_release_approval('minor', '1.3.0')


if __name__ == '__main__':
    unittest.main()
