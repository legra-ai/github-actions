"""Independent root packages own preparation and immutable tag versions."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ACTIONS = Path(__file__).resolve().parents[1] / '.github/actions'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ACTIONS / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest = load('mixed_release_manifest', 'release_manifest.py')
release = load('mixed_release_prepare', 'prepare-cargo-release/release.py')
tag = load('mixed_release_tag', 'tag-tested-release/tag.py')
MIXED = '''[package]
name = "fixture"
version = "0.2.0-alpha.19"

[workspace]
members = []

[workspace.package]
version = "0.7.0"
'''


class CargoManifestTests(unittest.TestCase):
    def test_explicit_root_version_is_independent_of_workspace_components(self):
        self.assertEqual(manifest.ReleaseManifest('cargo').version(MIXED), '0.2.0-alpha.19')

    def test_virtual_and_explicitly_inherited_roots_use_workspace_version(self):
        for contents in (
            '[workspace.package]\nversion = "0.7.0"\n',
            MIXED.replace('version = "0.2.0-alpha.19"', 'version.workspace = true'),
        ):
            with self.subTest(contents=contents):
                self.assertEqual(manifest.ReleaseManifest('cargo').version(contents), '0.7.0')

    def test_malformed_root_version_never_falls_back_to_a_workspace(self):
        for field in ('version = "bad"', 'version = 19', 'version.workspace = false',
                      'version.workspace = 1', 'version = ["0.2.0"]', 'description = "no version"'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                manifest.ReleaseManifest('cargo').version(
                    MIXED.replace('version = "0.2.0-alpha.19"', field))

    def test_tag_matches_the_root_version_at_the_exact_revision(self):
        source = 'a' * 40
        exists = subprocess.CompletedProcess([], 0, source, '')
        with patch.object(tag.subprocess, 'check_output', return_value=MIXED), \
                patch.object(tag.subprocess, 'run', return_value=exists) as commands:
            tag.tag_release('0.2.0-alpha.19', source, 'pep440')
        self.assertEqual(commands.call_args.args[0], ['git', 'push', 'origin', 'refs/tags/v0.2.0a19'])
        with patch.object(tag.subprocess, 'check_output', return_value=MIXED), \
                patch.object(tag.subprocess, 'run') as commands, \
                self.assertRaisesRegex(ValueError, 'manifest version'):
            tag.tag_release('0.7.0', source, 'pep440')
        commands.assert_not_called()

    def test_real_history_plan_uses_root_tag_without_mutating_either_version(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path.cwd()
            os.chdir(directory)
            try:
                def git(*args):
                    return subprocess.check_output(['git', *args], text=True,
                                                   stderr=subprocess.DEVNULL).strip()
                git('init', '-b', 'main')
                git('config', 'user.name', 'Release fixture')
                git('config', 'user.email', 'fixture@example.invalid')
                git('config', 'commit.gpgsign', 'false')
                git('config', 'core.hooksPath', '/dev/null')
                Path('Cargo.toml').write_text(MIXED)
                git('add', 'Cargo.toml')
                git('commit', '-m', 'chore(release): prepare 0.2.0-alpha.19')
                git('-c', 'tag.gpgsign=false', 'tag', 'v0.2.0a19')
                git('remote', 'add', 'origin', directory)
                git('commit', '--allow-empty', '-m', 'feat(runtime): add a root capability')
                source = git('rev-parse', 'HEAD')
                with patch.dict(os.environ, GITHUB_REF='refs/heads/main',
                                RELEASE_PLAN_ONLY='true', RELEASE_MANIFEST_KIND='cargo',
                                RELEASE_TAG_FORMAT='pep440'), \
                        patch.object(release, 'release_pending', return_value=False), \
                        patch.object(release, 'write_release_commit') as writer, \
                        patch.object(release, 'output') as output:
                    release.prepare()
                output.assert_called_once_with(revision=source, release='true',
                                               version='0.2.0-alpha.20',
                                               major_approval_required='false')
                writer.assert_not_called()
                self.assertEqual(Path('Cargo.toml').read_text(), MIXED)
                self.assertEqual(git('status', '--porcelain'), '')
            finally:
                os.chdir(old)


if __name__ == '__main__':
    unittest.main()
