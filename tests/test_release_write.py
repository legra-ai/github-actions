"""A needed version bump is written to main by the authorized writer."""

import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

SOURCE = pathlib.Path(__file__).parents[1] / '.github/actions/prepare-cargo-release/release.py'
spec = importlib.util.spec_from_file_location('release_write', SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseWriteTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('RELEASE_TOOL_CONTRACT') == '1',
                         'Public release tool contract runs in the native platform jobs')
    def test_public_tool_prepares_manifest_and_lock_without_a_local_commit(self):
        version = subprocess.check_output(['cargo', 'version-info', '--tool-version'], text=True)
        self.assertRegex(version, r'\b1\.0\.0\b')
        pathlib.Path('src').mkdir()
        pathlib.Path('src/lib.rs').write_text('pub const FIXTURE: bool = true;\n')
        self.git('add', 'src/lib.rs')
        self.git('commit', '-m', 'test(fixture): add package source')
        source = self.git('rev-parse', 'HEAD')
        real_run = subprocess.run
        writes = []

        def run(args, **kwargs):
            if args[:2] == ['gh', 'api']:
                self.assertEqual(args[2], 'graphql')
                writes.append(json.loads(kwargs['input'])['variables']['input'])
                return subprocess.CompletedProcess(args, 0,
                    '{"data":{"createCommitOnBranch":{"commit":{"oid":"prepared"}}}}', '')
            return real_run(args, **kwargs)

        with patch.dict(os.environ, CARGO_NET_OFFLINE='true'), \
                patch.object(release.subprocess, 'run', side_effect=run):
            revision = release.write_release_commit(source, '1.2.4')
        self.assertEqual(revision, 'prepared')
        self.assertEqual(self.git('rev-parse', 'HEAD'), source)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['expectedHeadOid'], source)
        self.assertEqual(writes[0]['branch']['branchName'], 'main')
        self.assertEqual({item['path'] for item in writes[0]['fileChanges']['additions']},
                         {'Cargo.toml', 'Cargo.lock'})
        for name in ('Cargo.toml', 'Cargo.lock'):
            self.assertIn('1.2.4', pathlib.Path(name).read_text())

    @unittest.skipUnless(os.environ.get('RELEASE_TOOL_CONTRACT') == '1',
                         'Public release tool contract runs in the native platform jobs')
    def test_public_tool_preserves_independent_components_and_syncs_python_locks(self):
        pathlib.Path('src').mkdir()
        pathlib.Path('src/lib.rs').write_text('// Root fixture.\n')
        pathlib.Path('child/src').mkdir(parents=True)
        pathlib.Path('child/src/lib.rs').write_text('// Child fixture.\n')
        child = '[package]\nname="component"\nversion.workspace=true\nedition="2024"\n'
        pathlib.Path('child/Cargo.toml').write_text(child)
        pathlib.Path('Cargo.toml').write_text('''[package]
name="fixture"
version="0.2.0-alpha.19"
edition="2024"
[package.metadata.version-info]
pre_bump_hooks=["uv run --no-project --python 3.13.16 python sync_python.py {{version}}"]
additional_files=["pyproject.toml", "uv.lock"]
[workspace]
members=["child"]
[workspace.package]
version="0.7.0"
''')
        pathlib.Path('pyproject.toml').write_text(
            '[project]\nname="fixture"\nversion="0.2.0a19"\nrequires-python=">=3.13,<3.14"\n')
        pathlib.Path('sync_python.py').write_text(
            'import subprocess, sys\n'
            'subprocess.run(["uv", "version", sys.argv[1].replace("-alpha.", "a"), '
            '"--no-sync"], check=True)\n')
        subprocess.run(['uv', 'lock', '--python', '3.13.16'], check=True)
        subprocess.run(['cargo', 'generate-lockfile', '--offline'], check=True)
        self.git('add', 'Cargo.toml', 'Cargo.lock', 'child', 'src', 'pyproject.toml',
                 'uv.lock', 'sync_python.py')
        self.git('commit', '-m', 'test(fixture): add independently versioned components')
        source = self.git('rev-parse', 'HEAD')
        real_run = subprocess.run
        writes = []

        def run(args, **kwargs):
            if args[:2] == ['gh', 'api']:
                writes.append(json.loads(kwargs['input'])['variables']['input'])
                return subprocess.CompletedProcess(args, 0,
                    '{"data":{"createCommitOnBranch":{"commit":{"oid":"prepared"}}}}', '')
            return real_run(args, **kwargs)

        with patch.dict(os.environ, CARGO_NET_OFFLINE='true'), \
                patch.object(release.subprocess, 'run', side_effect=run):
            revision = release.write_release_commit(source, '0.2.0-alpha.20')
        self.assertEqual(revision, 'prepared')
        self.assertEqual(self.git('rev-parse', 'HEAD'), source)
        document = tomllib.loads(pathlib.Path('Cargo.toml').read_text())
        self.assertEqual(document['package']['version'], '0.2.0-alpha.20')
        self.assertEqual(document['workspace']['package']['version'], '0.7.0')
        self.assertEqual(pathlib.Path('child/Cargo.toml').read_text(), child)
        packages = tomllib.loads(pathlib.Path('Cargo.lock').read_text())['package']
        self.assertEqual({item['name']: item['version'] for item in packages},
                         {'fixture': '0.2.0-alpha.20', 'component': '0.7.0'})
        self.assertEqual(tomllib.loads(pathlib.Path('pyproject.toml').read_text())
                         ['project']['version'], '0.2.0a20')
        python_packages = tomllib.loads(pathlib.Path('uv.lock').read_text())['package']
        self.assertEqual([(item['name'], item['version']) for item in python_packages],
                         [('fixture', '0.2.0a20')])
        self.assertFalse(pathlib.Path('.venv').exists())
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['expectedHeadOid'], source)
        self.assertEqual({item['path'] for item in writes[0]['fileChanges']['additions']},
                         {'Cargo.toml', 'Cargo.lock', 'pyproject.toml', 'uv.lock'})

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
