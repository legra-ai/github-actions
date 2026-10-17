"""Public installation-channel checks and immutable recovery-archive identity."""

import json
import tarfile
from urllib.parse import quote
import zipfile


class NotPublished(ValueError):
    """An expected publication is still absent, without a service/authentication failure."""


class Sources:
    def tag_revision(self, version):
        obj = self.api.github(f'{self.root}/git/ref/tags/v{version}')['object']
        # bounded: GitHub tags may be annotated; refuse pathological chains beyond eight links.
        for _ in range(8):
            if obj['type'] == 'commit':
                return obj['sha']
            if obj['type'] != 'tag':
                raise ValueError('Release tag does not identify a commit')
            obj = self.api.github(f'{self.root}/git/tags/{obj["sha"]}')['object']
        raise ValueError('Release tag annotation chain exceeds eight links')

    def recovery_manifest(self, version, release):
        if release is None or release['draft']:
            return None
        assets = release['assets']
        if len(assets) > 128:
            raise ValueError('Release exceeds the 128-asset inspection limit')
        name = self.config['recovery_asset']
        matches = [asset for asset in assets if asset['name'] == name]
        if len(matches) != 1:
            raise ValueError(f'Missing unique recovery asset {name}')
        with self.api.download(matches[0]['browser_download_url']) as (path, _):
            with zipfile.ZipFile(path) as bundle:
                if bundle.getinfo('manifest.json').file_size > 256 * 1024:
                    raise ValueError('Recovery manifest exceeds 256 KiB')
                manifest = json.loads(bundle.read('manifest.json'))
        if manifest['version'] != version or manifest['revision'] != self.tag_revision(version):
            raise ValueError('Recovery archive version/revision differs from the release tag')
        if not 1 <= len(manifest['files']) <= 64:
            raise ValueError('Recovery archive must contain between one and 64 packages')
        return manifest

    def check_registries(self, version, release):
        manifest = (self.recovery_manifest(version, release)
                    if self.config['recovery_asset'] is not None else None)
        failures = []
        for kind, name in self.config['registries'].items():
            try:
                getattr(self, f'check_{kind}')(name, version, manifest)
            except NotPublished as error:
                failures.append(f'{kind}: {error}')
        if failures:
            raise NotPublished('; '.join(failures))

    def check_crates(self, name, version, manifest):
        metadata = self.api.json(f'https://crates.io/api/v1/crates/{quote(name)}/{version}')
        if metadata is None or metadata['version']['num'] != version:
            raise NotPublished(f'{name} {version} is missing')
        with self.api.download(f'https://crates.io/api/v1/crates/{quote(name)}/{version}/download') as (path, _):
            with tarfile.open(path) as archive:
                member = archive.getmember(f'{name}-{version}/.cargo_vcs_info.json')
                if member.size > 256 * 1024:
                    raise ValueError('Crate source identity exceeds 256 KiB')
                identity = json.load(archive.extractfile(member))
        if identity['git']['sha1'] != self.tag_revision(version):
            raise ValueError('Published crate source differs from the release tag')

    def check_npm(self, name, version, manifest):
        metadata = self.api.json(f'https://registry.npmjs.org/{quote(name, safe="")}/{version}')
        if metadata is None or metadata['version'] != version:
            raise NotPublished(f'{name} {version} is missing')
        with self.api.download(metadata['dist']['tarball']) as (_, digest):
            if manifest:
                packages = {name: value for name, value in manifest['files'].items() if name.endswith('.tgz')}
                if len(packages) != 1 or digest != next(iter(packages.values())):
                    raise ValueError('Published npm archive differs from the preserved release archive')

    def check_pypi(self, name, version, manifest):
        metadata = self.api.json(f'https://pypi.org/pypi/{quote(name)}/{version}/json')
        if metadata is None or metadata['info']['version'] != version:
            raise NotPublished(f'{name} {version} is missing')
        files = metadata['urls']
        if len(files) > 64:
            raise ValueError('PyPI version exceeds the 64-file inspection limit')
        wheels = {filename: digest for filename, digest in manifest['files'].items()
                  if filename.endswith('.whl')} if manifest else {}
        if manifest and not wheels:
            raise ValueError('Recovery archive contains no Python wheels')
        for filename, expected in wheels.items():
            matches = [item for item in files if item['filename'] == filename]
            if len(matches) != 1 or matches[0]['digests']['sha256'] != expected:
                raise ValueError(f'Missing or mismatched PyPI wheel: {filename}')
            with self.api.download(matches[0]['url']) as (_, digest):
                if digest != expected:
                    raise ValueError(f'PyPI wheel download differs from release archive: {filename}')

    def check_cli(self, version, release):
        if not self.config['cli_assets']:
            return
        if release is None or release['draft']:
            raise NotPublished(f'CLI v{version} downloads are not public')
        for name in self.config['cli_assets']:
            matches = [item for item in release['assets'] if item['name'] == name]
            if len(matches) != 1:
                raise ValueError(f'Missing unique CLI asset: {name}')
            asset = matches[0]
            if asset.get('state') != 'uploaded' or not asset.get('digest', '').startswith('sha256:'):
                raise ValueError(f'CLI asset has no verified SHA-256 digest: {name}')
            with self.api.download(asset['browser_download_url']) as (_, digest):
                if f'sha256:{digest}' != asset['digest']:
                    raise ValueError(f'CLI download checksum mismatch: {name}')
