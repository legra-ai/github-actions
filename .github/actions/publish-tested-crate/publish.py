"""Publish only the tested checkout and require public source identity on every run."""

import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'verify-registry-publication'))
from verification import API, NotPublished, Verifier, await_publication


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
        subprocess.run(['cargo', 'publish', '--locked', '--allow-dirty', '--package', crate], check=True)
        await_publication(verifier.check, 300)
    print(f'{crate} {version} publicly verified from validated revision {revision}')


if __name__ == '__main__':
    main()
