"""Publish only the tested checkout and require public source identity on every run."""

import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'verify-registry-publication'))
from verification import API, NotPublished, Verifier, await_publication


def assert_clean_package(crate):
    """Generated staging files may exist, but every package input must be committed."""
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], check=True)
    # bounded: one distributable package, capped at 5,000 source paths.
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], text=True).split('\0'))
    files = subprocess.check_output(
        ['cargo', 'package', '--locked', '--allow-dirty', '--list', '--package', crate],
        text=True).splitlines()
    if len(files) > 5000:
        raise ValueError('Package source exceeds the 5,000-file validation limit')
    # Cargo generates these from its own metadata and the committed manifest.
    generated = {'.cargo_vcs_info.json', 'Cargo.toml.orig'}
    unknown = set(files) - tracked - generated
    if unknown:
        raise ValueError(f'Package contains uncommitted source inputs: {sorted(unknown)}')


def main():
    crate, version, revision = (os.environ[key] for key in ['RELEASE_CRATE', 'RELEASE_VERSION', 'RELEASE_REVISION'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', crate):
        raise ValueError('Invalid crate name')
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != revision:
        raise ValueError('Publication checkout differs from validated revision')
    verifier = Verifier(API(''), 'crates', crate, version, revision, None)
    try:
        verifier.check()
    except NotPublished:
        assert_clean_package(crate)
        subprocess.run(['cargo', 'publish', '--locked', '--allow-dirty', '--package', crate], check=True)
        await_publication(verifier.check, 300)
    print(f'{crate} {version} publicly verified from validated revision {revision}')


if __name__ == '__main__':
    main()
