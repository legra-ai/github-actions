"""Require public archive identity, allowing only bounded registry visibility delay."""

import json
import os
from pathlib import Path
import re
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).parent.parent / 'monitor-release'))
from release_http import API, DownloadNotFound
from release_sources import NotPublished, Sources


def await_publication(check, timeout, *, clock=time.monotonic, sleep=time.sleep):
    if not 0 < timeout <= 600:
        raise ValueError('Publication visibility timeout must be between 1 and 600 seconds')
    deadline = clock() + timeout
    while True:
        try:
            check()
            return
        except NotPublished as error:
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError(f'Public publication not verified within {timeout}s: {error}') from error
            print(f'Waiting for public registry visibility: {error}', flush=True)
            sleep(min(5, remaining))


def load_manifest(path, version, revision):
    with zipfile.ZipFile(path) as archive:
        if archive.namelist().count('manifest.json') != 1:
            raise ValueError('Expected one preserved archive manifest')
        if archive.getinfo('manifest.json').file_size > 256 * 1024:
            raise ValueError('Preserved archive manifest exceeds 256 KiB')
        manifest = json.loads(archive.read('manifest.json'))
    if (manifest['version'], manifest['revision']) != (version, revision):
        raise ValueError('Preserved archive version/revision differs from validated source')
    files = manifest['files']
    if not isinstance(files, dict) or not 1 <= len(files) <= 64:
        raise ValueError('Expected between one and 64 preserved packages')
    for name, digest in files.items():
        if Path(name).name != name or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('Invalid preserved package filename')
        if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('Expected a preserved SHA-256 package digest')
    return manifest


class Verifier(Sources):
    def __init__(self, api, registry, package, version, revision, manifest):
        if registry not in ('crates', 'npm', 'pypi'):
            raise ValueError('Unsupported registry')
        if registry in ('npm', 'pypi') and manifest is None:
            raise ValueError('Language bindings require a preserved release archive')
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('Expected a stable release version')
        if not re.fullmatch(r'[a-f0-9]{40}', revision):
            raise ValueError('Expected the complete validated source revision')
        self.api = api
        self.registry = registry
        self.package = package
        self.version = version
        self.revision = revision
        self.manifest = manifest

    def tag_revision(self, version):
        # The release pipeline supplies its tested revision, independently of mutable main.
        if version != self.version:
            raise ValueError('Verification version changed')
        return self.revision

    def check(self):
        try:
            getattr(self, f'check_{self.registry}')(self.package, self.version, self.manifest)
        except DownloadNotFound as error:
            # Registry metadata can become visible before the immutable archive.
            raise NotPublished(str(error)) from error


def main():
    registry, package, version, revision = (os.environ[key] for key in
                                          ['VERIFY_REGISTRY', 'VERIFY_PACKAGE', 'VERIFY_VERSION', 'VERIFY_REVISION'])
    archive = os.environ.get('VERIFY_ARCHIVE')
    manifest = load_manifest(Path(archive), version, revision) if archive else None
    verifier = Verifier(API(''), registry, package, version, revision, manifest)
    await_publication(verifier.check, int(os.environ.get('VERIFY_TIMEOUT', '300')))
    print(f'Verified public {registry} package {package} {version} from {revision}')


if __name__ == '__main__':
    main()
