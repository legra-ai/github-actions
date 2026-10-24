"""Release decisions must include unattended changes without duplicate releases."""

import importlib.util
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).parents[1] / '.github/actions/prepare-cargo-release/release.py'
spec = importlib.util.spec_from_file_location('release', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleasePlanTests(unittest.TestCase):
    def test_prerelease_changes_advance_the_candidate_without_promoting_to_stable(self):
        for message in ['fix(core): repair', 'feat(core): add', 'feat(core)!: replace']:
            self.assertEqual(release.next_version('0.2.0-alpha.1', '0.2.0-alpha.1', [message]), '0.2.0-alpha.2')
        self.assertIsNone(release.next_version('0.2.0-alpha.1', '0.2.0-alpha.1', ['docs(core): clarify']))

    def test_prerelease_order_and_explicit_promotion(self):
        self.assertLess(release.version_tuple('0.2.0-alpha.2'), release.version_tuple('0.2.0-alpha.10'))
        self.assertLess(release.version_tuple('0.2.0-rc.1'), release.version_tuple('0.2.0'))
        self.assertEqual(release.next_version('0.2.0', '0.2.0-alpha.9', ['chore(release): promote']), '0.2.0')
        with self.assertRaises(ValueError):
            release.next_version('0.2.0-alpha.1', '0.2.0', ['fix(core): repair'])

    def test_pep440_tags_preserve_existing_release_identity(self):
        self.assertEqual(release.tag_version('v0.2.0a12', 'pep440'), '0.2.0-alpha.12')
        self.assertEqual(release.tag_version('v0.2.0b2', 'pep440'), '0.2.0-beta.2')
        self.assertEqual(release.tag_version('v0.2.0rc3', 'pep440'), '0.2.0-rc.3')
        self.assertIsNone(release.tag_version('v0.2.0-alpha.1', 'pep440'))
        with self.assertRaises(ValueError):
            release.tag_version('v0.2.0', 'typo')

    def test_dependency_updates_release_a_patch(self):
        self.assertEqual(release.next_version('0.1.1', '0.1.1', ['build(deps): update serde']), '0.1.2')

    def test_features_release_a_minor(self):
        self.assertEqual(release.next_version('1.2.3', '1.2.3', ['feat(tree): add scopes']), '1.3.0')

    def test_breaking_changes_override_features(self):
        for message in ['fix(tree)!: change format', 'feat(tree): change\n\nBREAKING CHANGE: wire shape']:
            self.assertEqual(release.next_version('1.2.3', '1.2.3', [message]), '2.0.0')

    def test_zero_user_model_breaking_changes_release_a_minor(self):
        for current, expected in [('0.2.2', '0.3.0'), ('2.0.3', '2.1.0'), ('6.1.0', '6.2.0')]:
            for message in ['fix(model)!: replace shape',
                            'feat(model): replace\n\nBREAKING CHANGE: new shape']:
                with self.subTest(current=current, message=message):
                    self.assertEqual(
                        release.next_version(current, current, [message], 'minor'), expected)

    def test_minor_policy_keeps_fixes_patch_and_features_minor(self):
        self.assertEqual(release.next_version('6.1.0', '6.1.0', ['fix(model): repair'], 'minor'), '6.1.1')
        self.assertEqual(release.next_version('6.1.0', '6.1.0', ['feat(model): add'], 'minor'), '6.2.0')

    def test_invalid_breaking_change_policy_is_never_defaulted(self):
        for policy in ['patch', 'typo', '', None]:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                release.next_version('6.1.0', '6.1.0', ['fix(model)!: replace'], policy)

    def test_minor_policy_keeps_prereleases_in_their_candidate_series(self):
        self.assertEqual(
            release.next_version('6.2.0-alpha.1', '6.2.0-alpha.1',
                                 ['feat(model)!: replace'], 'minor'),
            '6.2.0-alpha.2')

    def test_docs_and_ci_alone_do_not_release(self):
        self.assertIsNone(release.next_version('0.1.1', '0.1.1', ['docs(readme): clarify', 'ci(test): adjust runner']))

    def test_unreleased_manual_bump_is_preserved(self):
        self.assertEqual(release.next_version('0.2.0', '0.1.1', ['chore(release): prepare']), '0.2.0')

    def test_published_release_commit_does_not_loop(self):
        self.assertIsNone(release.next_version('0.1.2', '0.1.2', []))

    def test_failed_release_does_not_require_a_new_version(self):
        self.assertEqual(release.next_version('0.1.2', '0.1.1', ['fix(tree): repair']), '0.1.2')

    def test_first_release_uses_manifest(self):
        self.assertEqual(release.next_version('0.1.0', None, ['feat(tree): initial']), '0.1.0')

    def test_history_is_not_limited_to_latest_commit(self):
        self.assertEqual(release.next_version('0.1.1', '0.1.1', ['fix(tree): repair', 'docs(readme): clarify']), '0.1.2')

    def test_invalid_messages_fail_even_with_manual_or_initial_version(self):
        for latest in ['0.1.1', '0.1.0', None]:
            for message in ['Update source', 'fix: missing scope', 'oops(core): unknown type', 'fix(core): ']:
                with self.subTest(latest=latest, message=message), self.assertRaises(ValueError):
                    release.next_version('0.1.1', latest, [message])

    def test_lower_manifest_is_refused(self):
        with self.assertRaises(ValueError):
            release.next_version('0.1.0', '0.1.1', ['fix(tree): repair'])


if __name__ == '__main__':
    unittest.main()
