"""An unfinished tagged release must survive later commits on main."""

import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = pathlib.Path(__file__).parents[1] / '.github/actions/prepare-cargo-release/release.py'
spec = importlib.util.spec_from_file_location('release_recovery', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        previous = pathlib.Path.cwd()
        os.chdir(self.directory.name)
        self.addCleanup(os.chdir, previous)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Release test')
        self.git('config', 'user.email', 'release@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', '/dev/null')
        pathlib.Path('Cargo.toml').write_text('[package]\nname="example"\nversion="1.2.3"\n')
        self.git('add', 'Cargo.toml')
        self.git('commit', '-m', 'chore(release): prepare 1.2.3')
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v1.2.2')
        self.tagged = self.git('rev-parse', 'HEAD')
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v1.2.3')
        self.git('remote', 'add', 'origin', self.directory.name)
        env = patch.dict(os.environ, GITHUB_REF='refs/heads/main', GITHUB_REPOSITORY='owner/example')
        env.start()
        self.addCleanup(env.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()

    def mock_api(self, result):
        real_run = subprocess.run

        def run(args, **kwargs):
            return result if args[0] == 'gh' else real_run(args, **kwargs)

        return patch.object(release.subprocess, 'run', side_effect=run)

    def test_python_alpha_resumes_original_tag_before_newer_main(self):
        pathlib.Path('Cargo.toml').write_text('[package]\nname="example"\nversion="1.3.0-alpha.2"\n')
        self.git('add', 'Cargo.toml')
        self.git('commit', '-m', 'chore(release): prepare 1.3.0-alpha.2')
        original = self.git('rev-parse', 'HEAD')
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v1.3.0a2')
        self.git('commit', '--allow-empty', '-m', 'feat(core): newer feature')
        result = subprocess.CompletedProcess([], 0, '{"draft": true}', '')
        with patch.dict(os.environ, RELEASE_TAG_FORMAT='pep440'), self.mock_api(result), patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision=original, release='true', version='1.3.0-alpha.2')

    def test_pending_release_is_resumed_before_later_changes(self):
        for message in ['docs(readme): clarify', 'fix(core): repair']:
            with self.subTest(message=message):
                self.git('commit', '--allow-empty', '-m', message)
                result = subprocess.CompletedProcess([], 0, '{"draft": true}', '')
                with self.mock_api(result), patch.object(release, 'output') as output:
                    release.prepare()
                output.assert_called_once_with(revision=self.tagged, release='true', version='1.2.3')

    def test_missing_release_is_resumed_at_original_tag(self):
        self.git('commit', '--allow-empty', '-m', 'docs(readme): clarify')
        result = subprocess.CompletedProcess([], 1, '', 'gh: Not Found (HTTP 404)')
        with self.mock_api(result), patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision=self.tagged, release='true', version='1.2.3')

    def test_completed_release_and_docs_do_not_publish(self):
        self.git('commit', '--allow-empty', '-m', 'docs(readme): clarify')
        current = self.git('rev-parse', 'HEAD')
        result = subprocess.CompletedProcess([], 0, '{"draft": false}', '')
        with self.mock_api(result), patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision=current, release='false', version='1.2.3')

    def test_preproduction_policy_plans_a_minor_without_requesting_major_review(self):
        self.git('commit', '--allow-empty', '-m', 'feat(core)!: replace format')
        result = subprocess.CompletedProcess([], 0, '{"draft": false}', '')
        with self.mock_api(result), patch.dict(os.environ, RELEASE_BREAKING_CHANGE_BUMP='minor'), \
                patch.object(release, 'require_major_approval') as approval, \
                patch.object(release, 'write_release_commit', return_value='prepared') as write, \
                patch.object(release, 'output') as output:
            release.prepare()
        approval.assert_not_called()
        write.assert_called_once_with(self.git('rev-parse', 'HEAD'), '1.3.0')
        output.assert_called_once_with(revision='prepared', release='true', version='1.3.0')

    def test_automatic_major_cannot_write_without_approval(self):
        self.git('commit', '--allow-empty', '-m', 'feat(core)!: replace format')
        result = subprocess.CompletedProcess([], 0, '{"draft": false}', '')
        with self.mock_api(result), patch.object(release, 'gh_api', return_value='[]'), \
                patch.dict(os.environ, GITHUB_RUN_ID='123', GITHUB_SHA='a' * 40,
                           RELEASE_APPROVAL_TOKEN='read-only'), \
                patch.object(release, 'write_release_commit') as write, \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.prepare()
        write.assert_not_called()

    def test_pending_major_cannot_bypass_the_gate(self):
        pathlib.Path('Cargo.toml').write_text('[package]\nname="example"\nversion="2.0.0"\n')
        self.git('add', 'Cargo.toml')
        self.git('commit', '-m', 'chore(release): prepare 2.0.0')
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v2.0.0')
        result = subprocess.CompletedProcess([], 0, '{"draft": true}', '')
        with self.mock_api(result), patch.object(release, 'gh_api', return_value='[]'), \
                patch.dict(os.environ, GITHUB_RUN_ID='123', GITHUB_SHA='a' * 40,
                           RELEASE_APPROVAL_TOKEN='read-only'), \
                self.assertRaisesRegex(ValueError, 'explicit approval'):
            release.prepare()

    def test_api_failure_is_not_an_absent_release(self):
        self.git('commit', '--allow-empty', '-m', 'docs(readme): clarify')
        result = subprocess.CompletedProcess([], 1, '', 'gh: Forbidden (HTTP 403)')
        with self.mock_api(result), self.assertRaisesRegex(RuntimeError, '403'):
            release.prepare()
