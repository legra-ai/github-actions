"""Caller language packages are attached once, from the release revision's own run."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).parents[1]
ACTION = ROOT / '.github/actions/preserve-release-packages'
sys.path.insert(0, str(ACTION))
SPEC = importlib.util.spec_from_file_location('preserve', ACTION / 'preserve.py')
preserve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preserve)

VERSION = '1.2.3'
REVISION = 'a' * 40


def bundle(path, version=VERSION, revision=REVISION, files=None, tamper=None):
    files = files or {'pkg-1.2.3.tgz': b'npm', 'pkg-1.2.3-py3-none-any.whl': b'wheel'}
    manifest = {'version': version, 'revision': revision,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(name, tamper if tamper and name.endswith('.whl') else data)
        if tamper == b'extra':
            archive.writestr('extra.bin', b'x')
    return path


class FakeRelease:
    def __init__(self, assets, stored=None, draft=True):
        self.names = list(assets)
        self.stored = stored
        self.draft = draft
        self.uploaded = []

    def assets(self):
        if not self.draft:
            raise ValueError('public')
        return self.names

    def download(self, directory):
        target = Path(directory) / preserve.ASSET
        shutil.copyfile(self.stored, target)
        return target

    def upload(self, path):
        self.uploaded.append(Path(path))


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        self.local = self.directory / preserve.ASSET

    def test_first_publishing_run_attaches_its_own_tested_packages(self):
        bundle(self.local)
        release = FakeRelease([])
        self.assertEqual(preserve.preserve(release, self.local, VERSION, REVISION), 'attached')
        self.assertEqual(release.uploaded, [self.local])

    def test_resumed_release_keeps_the_original_asset_without_uploading(self):
        original = bundle(self.directory / 'original.zip')
        # A later run's packages come from another revision and must be ignored.
        bundle(self.local, revision='b' * 40)
        release = FakeRelease([preserve.ASSET, 'other.zip'], stored=original)
        self.assertEqual(preserve.preserve(release, self.local, VERSION, REVISION), 'kept')
        self.assertEqual(release.uploaded, [])

    def test_recovery_run_never_attaches_packages_of_another_revision(self):
        bundle(self.local, revision='b' * 40)
        release = FakeRelease([])
        with self.assertRaises(ValueError):
            preserve.preserve(release, self.local, VERSION, REVISION)
        self.assertEqual(release.uploaded, [])

    def test_identity_violations_fail_before_any_upload(self):
        cases = {'version': dict(version='1.2.4'), 'tampered': dict(tamper=b'changed'),
                 'extra': dict(tamper=b'extra')}
        for label, arguments in cases.items():
            with self.subTest(label):
                bundle(self.local, **arguments)
                release = FakeRelease([])
                with self.assertRaises(ValueError):
                    preserve.preserve(release, self.local, VERSION, REVISION)
                self.assertEqual(release.uploaded, [])

    def test_mismatched_preserved_asset_and_public_or_duplicate_releases_fail(self):
        bundle(self.local)
        stored = bundle(self.directory / 'stored.zip', revision='c' * 40)
        for release in [FakeRelease([preserve.ASSET], stored=stored),
                        FakeRelease([preserve.ASSET, preserve.ASSET], stored=stored),
                        FakeRelease([], draft=False)]:
            with self.subTest(assets=release.names, draft=release.draft), self.assertRaises(ValueError):
                preserve.preserve(release, self.local, VERSION, REVISION)
            self.assertEqual(release.uploaded, [])


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()
        self.publish = self.workflow.split('\n  publish:\n', 1)[1].split('\n  installed-binary:\n', 1)[0]

    def test_packages_are_preserved_on_the_draft_before_crates_io(self):
        preserve_step = self.publish.index('preserve-release-packages/preserve.py')
        self.assertLess(self.publish.index('draft: true'), preserve_step)
        self.assertLess(preserve_step, self.publish.index('publish-tested-crate/publish.py'))
        self.assertIn("if: inputs.release-packages != ''", self.publish)
        self.assertIn('name: ${{ inputs.release-packages }}', self.publish)

    def test_callers_with_further_registries_complete_the_release_themselves(self):
        completion = self.publish.split('- name: Complete verified release\n', 1)[1]
        self.assertTrue(completion.startswith('        if: inputs.complete-release\n'))
        self.assertIn('--draft=false', completion)
        inputs = self.workflow.split('    inputs:\n', 1)[1].split('    outputs:\n', 1)[0]
        self.assertIn('      complete-release:\n', inputs)
        self.assertIn('        default: true\n        type: boolean\n', inputs)

    def test_release_identity_is_exposed_to_caller_publishers(self):
        outputs = self.workflow.split('    outputs:\n', 1)[1].split('    secrets:\n', 1)[0]
        for name in ('publish', 'version', 'revision'):
            self.assertIn(f'value: ${{{{ jobs.prepare.outputs.{name} }}}}', outputs)


if __name__ == '__main__':
    unittest.main()
