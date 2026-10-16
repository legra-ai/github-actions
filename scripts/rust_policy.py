"""Audit the common Rust minimum and exact compiler/formatter pins.

Usage: python3 scripts/rust_policy.py PATH [PATH ...] [--nightly-repo PATH]
The nightly exception is explicit and still requires a dated toolchain.
"""

import argparse
from pathlib import Path
import re
import tomllib


RUST_VERSION = "1.99.1"
RUSTFMT_TOOLCHAIN = "nightly-2026-10-16"


def inspect(root: Path, *, allow_nightly: bool = False) -> list[str]:
    """Return policy violations for one repository's root configuration."""
    manifest = tomllib.loads((root / "Cargo.toml").read_text())
    workspace = manifest.get("workspace", {}).get("package", {})
    package = manifest.get("package", {})
    if "name" not in package:
        package = workspace
    errors = []
    for key, expected in [("rust-version", RUST_VERSION), ("edition", "2024")]:
        value = package.get(key)
        if isinstance(value, dict) and value.get("workspace"):
            value = workspace.get(key)
        if value != expected:
            errors.append(f"Cargo.toml {key}: expected {expected}, got {value}")
    toolchain_path = root / "rust-toolchain.toml"
    if not toolchain_path.is_file():
        return errors + ["missing rust-toolchain.toml"]
    channel = tomllib.loads(toolchain_path.read_text())["toolchain"]["channel"]
    dated_nightly = allow_nightly and re.fullmatch(r"nightly-\d{4}-\d{2}-\d{2}", channel)
    if channel != RUST_VERSION and not dated_nightly:
        errors.append(f"toolchain: expected {RUST_VERSION}, got {channel}")
    formatter = root / "rustfmt-toolchain"
    if formatter.is_file():
        if formatter.read_text().strip() != RUSTFMT_TOOLCHAIN:
            errors.append(f"rustfmt-toolchain must pin {RUSTFMT_TOOLCHAIN}")
    elif not dated_nightly:
        errors.append("missing nightly rustfmt-toolchain pin")
    for directory in [".githooks", ".git-hooks"]:
        hook = root / directory / "pre-commit"
        if hook.is_file() and re.search(r"\./scripts/fmt\.sh\s+--\s+--check", hook.read_text()):
            errors.append(f"{directory}/pre-commit must call fmt.sh --check without a Cargo separator")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", nargs="+", type=Path)
    parser.add_argument("--nightly-repo", action="append", type=Path, default=[])
    args = parser.parse_args()
    exceptions = {path.resolve() for path in args.nightly_repo}
    failed = False
    for root in args.repositories:
        try:
            errors = inspect(root, allow_nightly=root.resolve() in exceptions)
        except (OSError, KeyError, tomllib.TOMLDecodeError) as error:
            errors = [str(error)]
        for error in errors:
            print(f"{root}: {error}")
            failed = True
    if not failed:
        print(f"Rust {RUST_VERSION} policy passed for {len(args.repositories)} repositories")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
