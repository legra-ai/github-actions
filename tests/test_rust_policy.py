"""Regression coverage for the shared compiler and formatter policy."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/rust_policy.py"


class RustPolicyTests(unittest.TestCase):
    def test_shared_crate_workflow_uses_the_exact_stable_compiler(self):
        workflow = SOURCE.parents[1] / ".github/workflows/cargo-crate-ci.yml"
        text = workflow.read_text()
        self.assertNotIn("cargo +nightly ", text)
        self.assertIn("rust-toolchain@nightly\n", text)
        self.assertIn("toolchain: nightly-2026-10-16", text)
        self.assertIn("rust-toolchain@1.99.1", text)

    def setUp(self):
        spec = importlib.util.spec_from_file_location("rust_policy", SOURCE)
        self.policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.policy)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "fixture"\nedition = "2024"\nrust-version = "1.99.1"\n'
        )
        (self.root / "rust-toolchain.toml").write_text(
            '[toolchain]\nchannel = "1.99.1"\ncomponents = ["rustfmt", "clippy"]\n'
        )
        (self.root / "rustfmt-toolchain").write_text("nightly-2026-10-16\n")

    def test_matching_stable_policy_passes(self):
        self.assertEqual(self.policy.inspect(self.root), [])

    def test_old_minimum_fails(self):
        manifest = self.root / "Cargo.toml"
        manifest.write_text(manifest.read_text().replace("1.99.1", "1.85"))
        self.assertTrue(self.policy.inspect(self.root))

    def test_workspace_minimum_and_member_inheritance(self):
        (self.root / "Cargo.toml").write_text(
            '[workspace.package]\nedition = "2024"\nrust-version = "1.99.1"\n'
            '[package]\nname = "fixture"\nedition.workspace = true\nrust-version.workspace = true\n'
        )
        self.assertEqual(self.policy.inspect(self.root), [])

    def test_missing_or_floating_toolchain_fails(self):
        toolchain = self.root / "rust-toolchain.toml"
        toolchain.unlink()
        self.assertTrue(self.policy.inspect(self.root))
        toolchain.write_text('[toolchain]\nchannel = "stable"\n')
        self.assertTrue(self.policy.inspect(self.root))

    def test_virtual_workspace_with_root_package_metadata(self):
        (self.root / "Cargo.toml").write_text(
            '[workspace.package]\nedition = "2024"\nrust-version = "1.99.1"\n'
            '[package.metadata.release]\nshared = true\n'
        )
        self.assertEqual(self.policy.inspect(self.root), [])

    def test_nightly_requires_explicit_exception_and_exact_date(self):
        toolchain = self.root / "rust-toolchain.toml"
        toolchain.write_text('[toolchain]\nchannel = "nightly-2026-10-16"\n')
        self.assertTrue(self.policy.inspect(self.root))
        self.assertEqual(self.policy.inspect(self.root, allow_nightly=True), [])
        toolchain.write_text('[toolchain]\nchannel = "nightly"\n')
        self.assertTrue(self.policy.inspect(self.root, allow_nightly=True))

    def test_formatter_must_use_the_pinned_nightly(self):
        formatter = self.root / "rustfmt-toolchain"
        formatter.write_text("1.99.1\n")
        self.assertTrue(self.policy.inspect(self.root))
        formatter.write_text("nightly-2026-10-16\n")
        self.assertEqual(self.policy.inspect(self.root), [])

    def test_hook_does_not_pass_cargo_separator_to_formatter_wrapper(self):
        hooks = self.root / ".githooks"
        hooks.mkdir()
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\n./scripts/fmt.sh -- --check\n")
        self.assertTrue(self.policy.inspect(self.root))
        hook.write_text("#!/bin/sh\n./scripts/fmt.sh --check\n")
        self.assertEqual(self.policy.inspect(self.root), [])


if __name__ == "__main__":
    unittest.main()
