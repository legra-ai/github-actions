"""Publish only the tested checkout and require public source identity on every run."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / 'verify-registry-publication'))
from verification import API, NotPublished, Verifier, await_publication


class PackageSources:
    """Map `cargo package --list` entries, relative to the package root, to their checkout sources."""

    def __init__(self, crate):
        metadata = json.loads(subprocess.check_output(
            ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1'], text=True))
        packages = [package for package in metadata['packages'] if package['name'] == crate]
        if len(packages) != 1:
            raise ValueError(f'Workspace must contain exactly one package named {crate}')
        package = packages[0]
        self.directory = Path(package['manifest_path']).resolve().parent
        # Cargo stages the workspace lockfile and out-of-package readme/license
        # files at the package root under their own file names.
        self.relocated = {'Cargo.lock': Path(metadata['workspace_root']).resolve() / 'Cargo.lock'}
        for field in ('readme', 'license_file'):
            if package.get(field):
                source = (self.directory / package[field]).resolve()
                if source.parent != self.directory:
                    self.relocated.setdefault(source.name, source)

    def source(self, name):
        """Return the checkout path, relative to the current directory, that Cargo packages as `name`."""
        path = self.directory / name
        if name in self.relocated and not path.exists():
            path = self.relocated[name]
        return os.path.relpath(path)


def assert_clean_package(crate):
    """Generated staging files may exist, but every package input must be committed."""
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], check=True)
    sources = PackageSources(crate)
    # Cargo generates these from its metadata and the committed manifest.
    generated = {'.cargo_vcs_info.json', 'Cargo.toml.orig'}
    command = ['cargo', 'package', '--locked', '--allow-dirty', '--list', '--package', crate]
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as listing:
        try:
            # bounded: stream one package, at most 5,000 source paths.
            for count, line in enumerate(listing.stdout, 1):
                if count > 5000:
                    raise ValueError('Package source exceeds the 5,000-file validation limit')
                name = line.rstrip('\n')
                if name in generated:
                    continue
                result = subprocess.run(
                    ['git', '--literal-pathspecs', 'ls-files', '--error-unmatch', '--', sources.source(name)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                if result.returncode != 0:
                    raise ValueError(f'Package contains an uncommitted source input: {name}: {result.stderr}')
            result = listing.wait()
            if result != 0:
                raise subprocess.CalledProcessError(result, command)
        except BaseException:
            if listing.poll() is None:
                listing.kill()
            listing.wait()
            raise


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
