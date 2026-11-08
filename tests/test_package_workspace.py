"""Private native adapters must not hide or replace the root release package."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('workspace_package_policy',
    ROOT / '.github/actions/test-cargo-package/package_test.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)

class PackageWorkspaceTests(unittest.TestCase):
    def package(self, root, path, name, publish=None):
        return {'name': name, 'manifest_path': str(root / path), 'publish': publish,
                'features': {}, 'targets': [{'kind': ['lib']}]}

    def metadata(self, root, packages):
        with patch.object(POLICY.subprocess, 'check_output', return_value=json.dumps({'packages': packages}).encode()):
            return POLICY.package_metadata(root, {})

    def test_root_package_selected_independently_of_private_member_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = self.package(root, 'Cargo.toml', 'kernel')
            private = self.package(root, 'python/Cargo.toml', 'native', [])
            self.assertEqual(self.metadata(root, [private, public]), public)
            self.assertEqual(self.metadata(root, [public, private]), public)

    def test_another_publishable_member_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'private'):
                self.metadata(root, [self.package(root, 'Cargo.toml', 'kernel'),
                    self.package(root, 'other/Cargo.toml', 'other')])

    def test_missing_duplicate_or_private_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = self.package(root, 'Cargo.toml', 'kernel')
            for packages in ([], [public, public], [self.package(root, 'Cargo.toml', 'kernel', [])]):
                with self.subTest(packages=packages), self.assertRaises(ValueError):
                    self.metadata(root, packages)

    def test_every_checkout_command_names_the_selected_package(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(Path(directory), 'Cargo.toml', 'kernel')
            for command in POLICY.feature_commands(package):
                self.assertEqual(command[command.index('--package') + 1], 'kernel')

if __name__ == '__main__':
    unittest.main()
