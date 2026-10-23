"""The shared planner must support a real static Python project without Cargo."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]


def load(name, source):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('uv_release', ROOT / '.github/actions/prepare-cargo-release/release.py')
tag = load('uv_tag', ROOT / '.github/actions/tag-tested-release/tag.py')


class UvReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        previous = Path.cwd()
        os.chdir(temporary.name)
        self.addCleanup(os.chdir, previous)
        self.root = Path.cwd()
        self.git('init', '-b', 'main')
        for key, value in [('user.name', 'Release fixture'),
                           ('user.email', 'release@example.invalid'),
                           ('commit.gpgsign', 'false'), ('core.hooksPath', '/dev/null')]:
            self.git('config', key, value)
        self.project('0.6.1')
        Path('blocked_backend.py').write_text('raise RuntimeError("Version planning built the project")\n')
        environment = patch.dict(os.environ, UV_PYTHON=sys.executable,
                                 GITHUB_REF='refs/heads/main', GITHUB_REPOSITORY='owner/fixture',
                                 RELEASE_MANIFEST_KIND='uv', RELEASE_TAG_FORMAT='semver')
        environment.start()
        self.addCleanup(environment.stop)
        subprocess.run(['uv', 'lock'], check=True, capture_output=True, text=True)
        self.git('add', 'pyproject.toml', 'uv.lock', 'blocked_backend.py')
        self.git('commit', '-m', 'chore(release): prepare 0.6.1')
        self.git('remote', 'add', 'origin', temporary.name)

    def project(self, version):
        Path('pyproject.toml').write_text(
            '[build-system]\nrequires=[]\nbuild-backend="blocked_backend"\nbackend-path=["."]\n'
            '[project]\nname="release-fixture"\n'
            f'version="{version}"\nrequires-python=">=3.11"\ndependencies=["packaging==26.0"]\n')

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def writer(self):
        response = json.dumps({'data': {'createCommitOnBranch': {'commit': {'oid': 'a' * 40}}}})
        return patch.object(release, 'gh_api', return_value=response)

    def test_real_uv_bump_relocks_without_building_or_a_local_commit(self):
        source = self.git('rev-parse', 'HEAD')
        before = tomllib.loads(Path('uv.lock').read_text())
        with self.writer() as api:
            revision = release.write_release_commit(source, '0.6.2', manifest_kind='uv')
        self.assertEqual(revision, 'a' * 40)
        self.assertEqual(self.git('rev-parse', 'HEAD'), source)
        self.assertFalse(Path('Cargo.toml').exists())
        self.assertFalse(Path('.venv').exists(), 'uv version must use --no-sync')
        self.assertEqual(tomllib.loads(Path('pyproject.toml').read_text())['project']['version'], '0.6.2')
        after = tomllib.loads(Path('uv.lock').read_text())
        external = lambda lock: [item for item in lock['package'] if item['name'] != 'release-fixture']
        self.assertEqual(external(before), external(after))
        own = next(item for item in after['package'] if item['name'] == 'release-fixture')
        self.assertEqual(own['version'], '0.6.2')
        payload = json.loads(api.call_args.kwargs['input'])['variables']['input']
        self.assertEqual(payload['expectedHeadOid'], source)
        self.assertEqual(payload['branch']['branchName'], 'main')
        additions = {item['path']: base64.b64decode(item['contents'])
                     for item in payload['fileChanges']['additions']}
        self.assertEqual(set(additions), {'pyproject.toml', 'uv.lock'})
        for name, content in additions.items():
            self.assertEqual(content, Path(name).read_bytes())

    def test_prepare_uses_static_python_version_and_the_same_expected_head_writer(self):
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v0.6.1')
        self.git('commit', '--allow-empty', '-m', 'fix(core): repair')
        source = self.git('rev-parse', 'HEAD')
        with patch.object(release, 'release_pending', return_value=False), \
                self.writer() as api, patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision='a' * 40, release='true', version='0.6.2')
        self.assertEqual(json.loads(api.call_args.kwargs['input'])['variables']['input']['expectedHeadOid'], source)

    def test_uv_prerelease_policy_preserves_candidate_and_manifest_spelling(self):
        for current, target in [('0.6.1a1', '0.6.1a2'), ('0.6.1b2', '0.6.1b3'),
                                ('0.6.1rc3', '0.6.1rc4')]:
            with self.subTest(current=current):
                self.project(current)
                subprocess.run(['uv', 'lock'], check=True, capture_output=True, text=True)
                self.git('add', 'pyproject.toml', 'uv.lock')
                self.git('commit', '-m', f'chore(release): prepare {current}')
                self.git('-c', 'tag.gpgsign=false', 'tag', f'v{current}')
                self.git('commit', '--allow-empty', '-m', 'feat(core)!: replace')
                with patch.dict(os.environ, RELEASE_TAG_FORMAT='pep440'), \
                        patch.object(release, 'release_pending', return_value=False), \
                        self.writer(), patch.object(release, 'output') as output:
                    release.prepare()
                output.assert_called_once_with(revision='a' * 40, release='true', version=target)
                self.assertEqual(tomllib.loads(Path('pyproject.toml').read_text())['project']['version'], target)
                self.git('add', 'pyproject.toml', 'uv.lock')
                self.git('commit', '-m', f'chore(release): prepare {target}')

    def test_uv_tag_reads_the_exact_python_revision_and_refuses_retargeting(self):
        source = self.git('rev-parse', 'HEAD')
        tag.tag_release('0.6.1', source, manifest_kind='uv')
        tag.tag_release('0.6.1', source, manifest_kind='uv')
        self.git('commit', '--allow-empty', '-m', 'fix(core): later')
        later = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'different revision'):
            tag.tag_release('0.6.1', later, manifest_kind='uv')
        with self.assertRaisesRegex(ValueError, 'manifest version'):
            tag.tag_release('0.6.2', later, manifest_kind='uv')
        self.assertEqual(self.git('rev-parse', 'v0.6.1^{commit}'), source)

    def test_uv_prerelease_tag_format_is_explicit(self):
        for version, semantic in [('0.6.1a2', '0.6.1-alpha.2'),
                                  ('0.6.1b3', '0.6.1-beta.3'),
                                  ('0.6.1rc4', '0.6.1-rc.4')]:
            self.project(version)
            self.git('add', 'pyproject.toml')
            self.git('commit', '-m', f'chore(release): prepare {version}')
            source = self.git('rev-parse', 'HEAD')
            for spelling, expected in [('semver', semantic), ('pep440', version)]:
                with self.subTest(version=version, spelling=spelling):
                    tag.tag_release(version, source, spelling, manifest_kind='uv')
                    self.assertEqual(self.git('rev-parse', f'v{expected}^{{commit}}'), source)

    def test_unknown_backend_never_falls_back_to_a_manifest(self):
        with self.assertRaisesRegex(ValueError, 'manifest kind'):
            release.write_release_commit(self.git('rev-parse', 'HEAD'), '0.6.2', manifest_kind='typo')
        with self.assertRaisesRegex(ValueError, 'manifest kind'):
            tag.tag_release('0.6.1', self.git('rev-parse', 'HEAD'), manifest_kind='typo')

    def test_missing_dynamic_and_malformed_python_versions_fail_before_writing(self):
        cases = ['not toml', '[project]\nname="fixture"\n',
                 '[project]\nversion="0.6.1"\ndynamic=["version"]\n',
                 '[project]\nversion=6\n', '[project]\nversion="0.6.1.dev1"\n',
                 '[project]\nversion="0.6.1.post1"\n', '[project]\nversion="1!0.6.1"\n',
                 '[project]\nversion="0.6.1+local"\n']
        for content in cases:
            with self.subTest(content=content):
                Path('pyproject.toml').write_text(content)
                with self.writer() as api, self.assertRaises(ValueError):
                    release.write_release_commit(self.git('rev-parse', 'HEAD'), '0.6.2', manifest_kind='uv')
                api.assert_not_called()

    def test_uv_pending_release_keeps_original_tag_and_manifest_version(self):
        self.project('0.6.1a2')
        self.git('add', 'pyproject.toml')
        self.git('commit', '-m', 'chore(release): prepare 0.6.1a2')
        source = self.git('rev-parse', 'HEAD')
        self.git('-c', 'tag.gpgsign=false', 'tag', 'v0.6.1a2')
        self.git('commit', '--allow-empty', '-m', 'feat(core): later feature')
        with patch.dict(os.environ, RELEASE_TAG_FORMAT='pep440'), \
                patch.object(release, 'release_pending', return_value=True), \
                patch.object(release, 'write_release_commit') as writer, \
                patch.object(release, 'output') as output:
            release.prepare()
        output.assert_called_once_with(revision=source, release='true', version='0.6.1a2')
        writer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
