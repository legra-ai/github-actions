"""Preserve a caller's tested language packages on the draft release, exactly once.

The first publishing run of a release revision attaches the run's own
release-packages.zip before any registry upload. Every later run resuming that
release keeps the original asset and only checks its identity, so recovery never
publishes packages that a different revision's jobs built and tested.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).parent.parent / 'verify-registry-publication'))
from verification import load_manifest

ASSET = 'release-packages.zip'


class ReleasePackages:
    """One release-packages.zip whose manifest and contents describe one tested revision."""

    def __init__(self, path):
        self.path = Path(path)

    def verify(self, version, revision):
        manifest = load_manifest(self.path, version, revision)
        expected = {'manifest.json', *manifest['files']}
        with zipfile.ZipFile(self.path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != expected:
                raise ValueError('Release packages differ from their manifest')
            for name, digest in manifest['files'].items():
                hasher = hashlib.sha256()
                with archive.open(name) as member:
                    # bounded: streamed in 1 MiB chunks.
                    while chunk := member.read(1 << 20):
                        hasher.update(chunk)
                if hasher.hexdigest() != digest:
                    raise ValueError(f'Release package identity mismatch: {name}')
        return manifest


class DraftRelease:
    """The GitHub release of one tag, through the authenticated gh CLI."""

    def __init__(self, tag, run=subprocess.run):
        self.tag = tag
        self.run = run

    def assets(self):
        result = self.run(['gh', 'release', 'view', self.tag, '--json', 'assets,isDraft'],
                          check=True, capture_output=True, text=True)
        release = json.loads(result.stdout)
        if not release['isDraft']:
            raise ValueError(f'{self.tag} is already public; its packages cannot change')
        return [asset['name'] for asset in release['assets']]

    def download(self, directory):
        self.run(['gh', 'release', 'download', self.tag, '--pattern', ASSET, '--dir', str(directory)],
                 check=True)
        return Path(directory) / ASSET

    def upload(self, path):
        # No --clobber: a preserved asset never changes identity.
        self.run(['gh', 'release', 'upload', self.tag, str(path)], check=True)


def preserve(release, local, version, revision):
    """Keep the original asset, or attach this run's packages of the same revision."""
    assets = release.assets()
    if assets.count(ASSET) > 1:
        raise ValueError(f'Duplicate {ASSET} assets')
    if ASSET in assets:
        with tempfile.TemporaryDirectory() as directory:
            ReleasePackages(release.download(directory)).verify(version, revision)
        return 'kept'
    if Path(local).name != ASSET:
        raise ValueError(f'Caller packages must be named {ASSET}')
    # Only the release revision's own run built and tested packages with this identity.
    ReleasePackages(local).verify(version, revision)
    release.upload(local)
    return 'attached'


def main():
    version = os.environ['RELEASE_VERSION']
    outcome = preserve(DraftRelease(f'v{version}'), os.environ['RELEASE_PACKAGES'], version,
                       os.environ['RELEASE_REVISION'])
    print(f'{ASSET} {outcome} for v{version} from {os.environ["RELEASE_REVISION"]}')


if __name__ == '__main__':
    main()
