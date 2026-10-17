"""Guard credential-free validation and immutable Cargo release ordering."""
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]


class MaintenanceTests(unittest.TestCase):
    def test_pr_validation_does_not_require_publication_secrets(self):
        workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()
        self.assertNotIn('required: true\n', workflow.split('    secrets:')[1])
        self.assertIn("if: github.ref == 'refs/heads/main'", workflow)
        self.assertIn('actions/create-github-app-token@v3', workflow)
        self.assertIn('cancel-in-progress: false', workflow)

    def test_publication_waits_for_tests_and_all_binary_builds(self):
        workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()
        self.assertIn('needs: [prepare, test, binary]', workflow)
        self.assertIn("needs.binary.result == 'skipped'", workflow)
        self.assertIn('draft: true', workflow)
        self.assertIn('ref: ${{ needs.prepare.outputs.revision }}', workflow)
        self.assertIn('publish-tested-crate', workflow)
        self.assertIn('test-cargo-package', workflow)
        self.assertIn('published: true', workflow)
        self.assertNotIn('secrets: inherit', workflow)

    def test_archive_validation_rejects_missing_tests_and_licenses(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('package_test', ROOT / '.github/actions/test-cargo-package/package_test.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for files in [{'src/lib.rs', 'LICENSE-MIT', 'LICENSE-APACHE'},
                      {'src/lib.rs', 'tests/public_api.rs', 'LICENSE-MIT'}]:
            with self.subTest(files=files), self.assertRaises(ValueError):
                module.validate_files(files)
        module.validate_files({'src/lib.rs', 'tests/public_api.rs', 'LICENSE-MIT', 'LICENSE-APACHE'})


if __name__ == '__main__':
    unittest.main()
