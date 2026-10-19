"""Optional-feature behavior must execute before and after publication."""
import os
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_feature_policy',
    ROOT / '.github/actions/test-cargo-package/package_test.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class PackageFeatureTests(unittest.TestCase):
    def package(self, exclusions=None):
        return {'features': {'default': [], 'jemalloc': [], 'profiling': ['jemalloc']},
                'metadata': {'legra-ci': {'unsupported-features': exclusions or {}}},
                'targets': [{'kind': ['lib']}]}

    def test_windows_exercises_supported_features_without_requesting_unix_allocator(self):
        package = self.package({'windows': ['jemalloc', 'profiling']})
        self.assertEqual(PACKAGE.optional_feature_args(package, 'Windows'), ['--no-default-features'])
        for system in ('Linux', 'Darwin'):
            self.assertEqual(PACKAGE.optional_feature_args(package, system), ['--all-features'])

    def test_cargo_null_metadata_retains_full_feature_coverage(self):
        package = self.package()
        package['metadata'] = None
        self.assertEqual(PACKAGE.optional_feature_args(package, 'Windows'), ['--all-features'])

    def test_other_optional_features_remain_enabled_on_windows(self):
        package = self.package({'windows': ['jemalloc', 'profiling']})
        package['features']['portable'] = []
        self.assertEqual(PACKAGE.optional_feature_args(package, 'Windows'),
                         ['--no-default-features', '--features', 'portable'])

    def test_archive_honors_the_declared_platform_contract(self):
        with tempfile.TemporaryDirectory(prefix='cargo-platform-contract-') as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            (root / 'tests').mkdir()
            (root / 'Cargo.toml').write_text(
                '[package]\nname="platform-contract-fixture"\nversion="0.1.0"\n'
                'edition="2021"\nlicense="MIT OR Apache-2.0"\n'
                'include=["src/**", "tests/**", "Cargo.toml", "Cargo.lock", "LICENSE-MIT", "LICENSE-APACHE"]\n'
                '[features]\nextra=[]\n'
                '[package.metadata.legra-ci.unsupported-features]\nwindows=["extra"]\n')
            (root / 'rust-toolchain.toml').write_text('[toolchain]\nchannel="1.89.0"\n')
            (root / 'src/lib.rs').write_text(
                '#[cfg(all(feature="extra", target_os="windows"))]\n'
                'compile_error!("extra is unsupported on Windows");\n'
                'pub fn available() -> bool { true }\n')
            (root / 'tests/contract.rs').write_text(
                '#[test] fn public_contract() { assert!(platform_contract_fixture::available()); }\n')
            for name in ['LICENSE-MIT', 'LICENSE-APACHE']:
                (root / name).write_text('Test fixture; never published.\n')
            env = {**os.environ, 'CARGO_NET_OFFLINE': 'true'}
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True, capture_output=True)
            subprocess.run(['cargo', '+1.89.0', 'generate-lockfile', '--offline'], cwd=root,
                           env=env, check=True, capture_output=True)
            result = subprocess.run(
                [sys.executable, str(ROOT / '.github/actions/test-cargo-package/package_test.py')],
                cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Validated platform-contract-fixture-0.1.0 archive sha256:', result.stdout)

    def test_exclusions_cannot_hide_a_feature_on_every_ci_platform(self):
        package = self.package({name: ['jemalloc', 'profiling']
                                for name in ('linux', 'macos', 'windows')})
        with self.assertRaisesRegex(ValueError, 'every platform'):
            PACKAGE.optional_feature_args(package, 'Windows')

    def test_invalid_support_declarations_fail_before_running_cargo(self):
        for exclusions in ({'windwos': ['jemalloc']}, {'windows': ['typo']},
                           {'windows': ['jemalloc', 'jemalloc']}, {'windows': 'jemalloc'},
                           {'windows': ['jemalloc']}):
            with self.subTest(exclusions=exclusions), self.assertRaises(ValueError):
                PACKAGE.optional_feature_args(self.package(exclusions), 'Windows')
        package = self.package({'windows': ['jemalloc', 'profiling']})
        package['features']['default'] = ['jemalloc']
        with self.assertRaisesRegex(ValueError, 'default'):
            PACKAGE.optional_feature_args(package, 'Windows')

    def test_archive_with_a_broken_optional_feature_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='cargo-feature-contract-') as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            (root / 'tests').mkdir()
            (root / 'Cargo.toml').write_text(
                '[package]\nname="feature-contract-fixture"\nversion="0.1.0"\n'
                'edition="2021"\nlicense="MIT OR Apache-2.0"\n'
                'include=["src/**", "tests/**", "Cargo.toml", "Cargo.lock", "LICENSE-MIT", "LICENSE-APACHE"]\n'
                '[features]\nextra=[]\n')
            (root / 'rust-toolchain.toml').write_text('[toolchain]\nchannel="1.89.0"\n')
            (root / 'src/lib.rs').write_text('pub fn available() -> bool { !cfg!(feature="extra") }\n')
            (root / 'tests/contract.rs').write_text(
                '#[test] fn public_contract() { assert!(feature_contract_fixture::available()); }\n')
            for name in ['LICENSE-MIT', 'LICENSE-APACHE']:
                (root / name).write_text('Test fixture; never published.\n')
            env = {**os.environ, 'CARGO_NET_OFFLINE': 'true'}
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True, capture_output=True)
            subprocess.run(['cargo', '+1.89.0', 'generate-lockfile', '--offline'], cwd=root,
                           env=env, check=True, capture_output=True)
            result = subprocess.run(
                [sys.executable, str(ROOT / '.github/actions/test-cargo-package/package_test.py')],
                cwd=root, env=env, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0,
                                'An archive whose optional feature fails was accepted: ' + result.stdout + result.stderr)
            self.assertIn('public_contract', result.stdout, result.stderr)
            self.assertIn('FAILED', result.stdout)

    def test_checkout_gate_executes_default_and_all_feature_contracts(self):
        workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()
        self.assertIn('cargo test --locked --all-targets', workflow)
        self.assertIn('package_test.py" checkout', workflow)
        commands = PACKAGE.feature_commands(self.package(), 'Linux')
        self.assertIn(['cargo', 'test', '--locked', '--all-targets', '--all-features'], commands)
        self.assertIn(['cargo', 'test', '--locked', '--doc', '--all-features'], commands)


if __name__ == '__main__':
    unittest.main()
