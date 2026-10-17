"""Optional-feature behavior must execute before and after publication."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackageFeatureTests(unittest.TestCase):
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
            self.assertIn('public_contract', result.stdout)
            self.assertIn('FAILED', result.stdout)

    def test_checkout_gate_executes_default_and_all_feature_contracts(self):
        workflow = (ROOT / '.github/workflows/cargo-maintenance.yml').read_text()
        self.assertIn('cargo test --locked --all-targets --all-features', workflow)
        self.assertIn('cargo test --locked --doc --all-features', workflow)


if __name__ == '__main__':
    unittest.main()
