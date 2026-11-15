"""Publication happens only in the run that validated the exact release revision."""

import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('release_decision', ROOT / '.github/scripts/release_decision.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ReleaseDecision = module.ReleaseDecision

SOURCE = 'a' * 40
RELEASE = 'b' * 40


class DecisionTests(unittest.TestCase):
    def decide(self, revision=SOURCE, run_revision=SOURCE, planned='true', planned_version='1.2.4',
               manifest_version='1.2.3', tagged=False):
        return ReleaseDecision(revision, run_revision, planned, planned_version, manifest_version, tagged)

    def test_source_run_writes_the_version_commit_but_never_publishes(self):
        decision = self.decide()
        self.assertTrue(decision.write_version)
        self.assertFalse(decision.publish)
        self.assertEqual(decision.outputs(), {'version': '1.2.3', 'write-version': 'true', 'publish': 'false'})

    def test_release_revision_publishes_only_in_its_own_run(self):
        decision = self.decide(revision=RELEASE, run_revision=RELEASE, manifest_version='1.2.4')
        self.assertTrue(decision.publish)
        self.assertFalse(decision.write_version)

    def test_a_rerun_of_the_source_run_does_not_publish_the_untested_release_revision(self):
        # The planner resumes the version commit an earlier attempt wrote; this
        # run's caller jobs validated the source, not that commit.
        decision = self.decide(revision=RELEASE, run_revision=SOURCE, manifest_version='1.2.4')
        self.assertFalse(decision.publish)
        self.assertFalse(decision.write_version)

    def test_an_unfinished_tagged_release_is_completed_from_a_later_run(self):
        decision = self.decide(revision=RELEASE, run_revision=SOURCE, manifest_version='1.2.4', tagged=True)
        self.assertTrue(decision.publish)

    def test_a_stale_or_unplanned_run_does_nothing(self):
        for planned in ['false']:
            decision = self.decide(planned=planned, planned_version='')
            self.assertEqual(decision.outputs()['write-version'], 'false')
            self.assertEqual(decision.outputs()['publish'], 'false')
        with self.assertRaises(ValueError):
            self.decide(planned='')

    def test_tags_and_manifest_are_read_from_the_planned_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=directory, text=True,
                                               stderr=subprocess.DEVNULL).strip()
            git('init', '-b', 'main')
            git('config', 'user.name', 'Release test')
            git('config', 'user.email', 'release@example.invalid')
            git('config', 'commit.gpgsign', 'false')
            git('config', 'core.hooksPath', '/dev/null')
            pathlib.Path(directory, 'Cargo.toml').write_text('[package]\nname="example"\nversion="1.2.4"\n')
            git('add', 'Cargo.toml')
            git('commit', '-m', 'chore(release): prepare 1.2.4')
            revision = git('rev-parse', 'HEAD')
            previous = pathlib.Path.cwd()
            os.chdir(directory)
            try:
                untagged = ReleaseDecision.from_git(revision, SOURCE, 'true', '1.2.4')
                git('-c', 'tag.gpgsign=false', 'tag', 'v1.2.4')
                tagged = ReleaseDecision.from_git(revision, SOURCE, 'true', '1.2.4')
            finally:
                os.chdir(previous)
        self.assertEqual(untagged.manifest_version, '1.2.4')
        self.assertFalse(untagged.publish)
        self.assertTrue(tagged.publish)


class WorkflowGraphTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()

    def job(self, name, following):
        return self.workflow.split(f'\n  {name}:\n', 1)[1].split(f'\n  {following}:\n', 1)[0]

    def test_planning_is_read_only(self):
        prepare = self.job('prepare', 'test')
        self.assertIn("RELEASE_PLAN_ONLY: 'true'", prepare)
        self.assertEqual(prepare.count('prepare-cargo-release/release.py'), 1)
        self.assertNotIn('create-github-app-token', prepare)
        self.assertIn('RUN_REVISION: ${{ github.sha }}', prepare)
        self.assertIn('.github/scripts/release_decision.py', prepare)

    def test_version_commit_waits_for_every_validation_job(self):
        version = self.job('version', 'publish')
        self.assertIn('needs: [prepare, test, binary]', version)
        self.assertIn("needs.prepare.outputs.write-version == 'true'", version)
        self.assertIn("needs.test.result == 'success'", version)
        self.assertIn('prepare-cargo-release/release.py', version)
        self.assertNotIn('RELEASE_PLAN_ONLY', version)

    def test_publication_follows_the_own_revision_decision(self):
        publish = self.job('publish', 'installed-binary')
        self.assertIn("needs.prepare.outputs.publish == 'true'", publish)
        self.assertNotIn('needs.prepare.outputs.release', publish)
        self.assertIn('RELEASE_PUBLICATION: ${{ needs.prepare.outputs.publish }}', self.job('binary', 'version'))


if __name__ == '__main__':
    unittest.main()
