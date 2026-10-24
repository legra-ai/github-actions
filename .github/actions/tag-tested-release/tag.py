"""Tag only the exact validated revision with its manifest version."""

import os
import pathlib
import re
import runpy
import subprocess


ReleaseManifest = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / 'release_manifest.py'))['ReleaseManifest']


def tag_release(version, revision, tag_format="semver", manifest_kind='cargo'):
    if tag_format not in ('semver', 'pep440'):
        raise ValueError(f'Unsupported release tag format: {tag_format!r}')
    manifest = ReleaseManifest(manifest_kind)
    policy_version = manifest.policy_version(version)
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Invalid release version or revision')
    if manifest.version(subprocess.check_output(['git', 'show', f'{revision}:{manifest.path}'], text=True)) != version:
        raise ValueError('Release tag does not match manifest version')
    spelling = policy_version
    if tag_format == 'pep440':
        for channel, marker in [('alpha', 'a'), ('beta', 'b'), ('rc', 'rc')]:
            spelling = spelling.replace(f'-{channel}.', marker)
    tag = f'v{spelling}'
    exists = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}'], capture_output=True, text=True)
    if exists.returncode == 0:
        if exists.stdout.strip() != revision:
            raise ValueError(f'{tag} already identifies a different revision')
    elif exists.returncode == 1:
        subprocess.run(['git', '-c', 'user.name=github-actions[bot]',
                        '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
                        '-c', 'tag.gpgSign=false', 'tag', '-a', tag, revision, '-m', f'Release {tag}'], check=True)
    else:
        raise RuntimeError(exists.stderr)
    subprocess.run(['git', 'push', 'origin', f'refs/tags/{tag}'], check=True)


if __name__ == '__main__':
    tag_release(os.environ['RELEASE_VERSION'], os.environ['RELEASE_REVISION'], os.environ.get('RELEASE_TAG_FORMAT', 'semver'), os.environ.get('RELEASE_MANIFEST_KIND', 'cargo'))
