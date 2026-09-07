"""A needed version bump is written to main by the authorized writer."""

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = pathlib.Path(__file__).parents[1] / '.github/actions/prepare-cargo-release/release.py'
spec = importlib.util.spec_from_file_location('release_write', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseWriteTests(unittest.TestCase):
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
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v1.2.3')
        self.git('remote', 'add', 'origin', self.directory.name)
        env = patch.dict(os.environ, GITHUB_REF='refs/heads/main', GITHUB_REPOSITORY='owner/example')
        env.start()
        self.addCleanup(env.stop)

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()

    def mock_commands(self, responses):
        real_run = subprocess.run
        calls = []

        def run(args, **kwargs):
            if args[0] == 'gh':
                calls.append((args, kwargs.get('input')))
                stdout, code, stderr = responses.pop(0)
                return subprocess.CompletedProcess(args, code, stdout, stderr)
            if args[:3] == ['cargo', 'version-info', 'bump']:
                version = args[args.index('--version') + 1]
                pathlib.Path('Cargo.toml').write_text(f'[package]\nname="example"\nversion="{version}"\n')
                return subprocess.CompletedProcess(args, 0, '', '')
            return real_run(args, **kwargs)

        return patch.object(release.subprocess, 'run', side_effect=run), calls

    def test_unreleased_fix_writes_the_version_commit_to_main(self):
        self.git('commit', '--allow-empty', '-m', 'fix(core): repair')
        source = self.git('rev-parse', 'HEAD')
        responses = [
            ('{"draft": false}', 0, ''),
            (json.dumps({'data': {'createCommitOnBranch': {'commit': {'oid': 'abc'}}}}), 0, ''),
        ]
        mock, calls = self.mock_commands(responses)
        with mock, patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision='abc', release='true', version='1.2.4')
        payload = json.loads(calls[1][1])['variables']['input']
        self.assertEqual(payload['branch']['branchName'], 'main')
        self.assertEqual(payload['expectedHeadOid'], source, 'expected-head guard binds the write to its source')
        self.assertEqual(payload['message']['headline'], 'chore(release): prepare 1.2.4')
        self.assertIn(f'Release source: {source}', payload['message']['body'])
        self.assertEqual([a['path'] for a in payload['fileChanges']['additions']], ['Cargo.toml'])

    def test_write_errors_fail_the_run(self):
        self.git('commit', '--allow-empty', '-m', 'fix(core): repair')
        responses = [('{"draft": false}', 0, ''), ('', 1, 'gh: Forbidden (HTTP 403)')]
        mock, _ = self.mock_commands(responses)
        with mock, self.assertRaisesRegex(RuntimeError, '403'):
            release.prepare()

    def test_stale_main_checkout_never_prepares(self):
        self.git('commit', '--allow-empty', '-m', 'fix(core): repair')
        stale = self.git('rev-parse', 'HEAD~1')
        self.git('checkout', '-q', '--detach', stale)
        with patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision=stale, release='false', version='')


if __name__ == '__main__':
    unittest.main()
