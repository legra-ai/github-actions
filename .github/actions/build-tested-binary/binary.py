"""Build, preserve and smoke-test an immutable binary installation archive."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from urllib.request import urlopen
import zipfile


def identity():
    crate, version, revision, target = (os.environ[key] for key in
        ['RELEASE_CRATE', 'RELEASE_VERSION', 'RELEASE_REVISION', 'RELEASE_TARGET'])
    if not re.fullmatch(r'cargo-[a-z-]+', crate) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid binary package/version')
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not re.fullmatch(r'[a-z0-9_-]+', target):
        raise ValueError('Invalid binary source/target')
    return {'crate': crate, 'version': version, 'revision': revision, 'target': target}


def gh(*args):
    return subprocess.check_output(['gh', *args])


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def release(info):
    # The REST tag endpoint excludes drafts. Resolve the named release through
    # GraphQL, then fetch its full asset metadata through the REST release ID.
    owner, name = os.environ['GITHUB_REPOSITORY'].split('/', 1)
    query = ('query($owner:String!,$name:String!,$tag:String!){'
             'repository(owner:$owner,name:$name){release(tagName:$tag){databaseId}}}')
    result = subprocess.run(['gh', 'api', 'graphql', '-f', 'query=' + query,
                             '-f', 'owner=' + owner, '-f', 'name=' + name,
                             '-f', 'tag=v' + info['version']], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    payload = json.loads(result.stdout)
    if payload.get('errors') or payload['data']['repository'] is None:
        raise RuntimeError('Release lookup did not resolve the authorized repository')
    found = payload['data']['repository']['release']
    if found is None:
        return None
    release_id = found['databaseId']
    if type(release_id) is not int or release_id <= 0:
        raise ValueError('Release lookup returned an invalid database ID')
    metadata = json.loads(gh('api', f'repos/{owner}/{name}/releases/{release_id}'))
    if metadata.get('tag_name') != 'v' + info['version']:
        raise ValueError('Resolved release differs from the requested tag')
    return metadata


def archive_name(info):
    return f'{info["crate"]}-{info["target"]}.zip'


def validate(path, info, smoke=True):
    binary = info['crate'] + ('.exe' if 'windows' in info['target'] else '')
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != {binary, 'release.json'}:
            raise ValueError('Binary archive has unexpected files')
        metadata = json.loads(archive.read('release.json'))
        if any(metadata.get(key) != value for key, value in info.items()):
            raise ValueError('Binary archive differs from tested release identity')
        data = archive.read(binary)
        if hashlib.sha256(data).hexdigest() != metadata['sha256']:
            raise ValueError('Binary archive executable digest mismatch')
        if smoke:
            host = subprocess.check_output(['rustc', '-vV'], text=True).split('host: ')[1].splitlines()[0]
            if host == info['target']:
                installed = Path('binary-smoke') / binary
                installed.parent.mkdir(exist_ok=True)
                installed.write_bytes(data)
                installed.chmod(0o755)
                subprocess.run([str(installed.resolve()), info['crate'].removeprefix('cargo-'), '--help'], check=True)


def build(info):
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() != info['revision']:
        raise ValueError('Build checkout differs from tested revision')
    output = Path('binary-artifacts')
    output.mkdir(exist_ok=True)
    path = output / archive_name(info)
    existing = release(info) if os.environ.get('RELEASE_PUBLICATION') == 'true' else None
    matches = [asset for asset in existing['assets'] if asset['name'] == path.name] if existing else []
    if len(matches) > 1:
        raise ValueError('Duplicate binary release asset')
    if matches:
        asset = matches[0]
        path.write_bytes(gh('api', '-H', 'Accept: application/octet-stream',
                            f'repos/{os.environ["GITHUB_REPOSITORY"]}/releases/assets/{asset["id"]}'))
        if asset.get('digest') != 'sha256:' + digest(path):
            raise ValueError('Preserved release asset digest mismatch')
    else:
        subprocess.run(['cargo', 'build', '--locked', '--release', '--target', info['target'], '--bin', info['crate']], check=True)
        binary = info['crate'] + ('.exe' if 'windows' in info['target'] else '')
        metadata = json.loads(subprocess.check_output(['cargo', 'metadata', '--no-deps', '--format-version', '1']))
        built = Path(metadata['target_directory']) / info['target'] / 'release' / binary
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(built, binary)
            archive.writestr('release.json', json.dumps({**info, 'sha256': digest(built)}, sort_keys=True))
    validate(path, info)


def upload(info):
    existing = release(info)
    if not existing or not existing['draft']:
        raise ValueError('Binary upload requires the pending draft release')
    paths = sorted(Path('binary-artifacts').glob('*.zip'))
    if len(paths) != 6:
        raise ValueError('Expected exactly six platform binary archives')
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            artifact_info = json.loads(archive.read('release.json'))
        if any(artifact_info.get(key) != info[key] for key in ['crate', 'version', 'revision']):
            raise ValueError('Binary artifact source/version mismatch')
        validate(path, {key: artifact_info[key] for key in info}, smoke=False)
        matches = [asset for asset in existing['assets'] if asset['name'] == path.name]
        if matches:
            if len(matches) != 1 or matches[0].get('digest') != 'sha256:' + digest(path):
                raise ValueError('Refusing to replace an existing release binary')
        else:
            subprocess.run(['gh', 'release', 'upload', 'v' + info['version'], str(path)], check=True)


def public(info):
    path = Path(archive_name(info))
    repository = os.environ['GITHUB_REPOSITORY']
    with urlopen(f'https://github.com/{repository}/releases/download/v{info["version"]}/{path.name}', timeout=60) as response:
        with path.open('wb') as output:
            while chunk := response.read(64 * 1024):
                output.write(chunk)
    validate(path, info)


if __name__ == '__main__':
    {'build': build, 'upload': upload, 'public': public}[sys.argv[1]](identity())
