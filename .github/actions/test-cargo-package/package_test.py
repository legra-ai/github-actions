"""Exercise the actual crate archive outside its source checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import re
import tarfile
import tempfile
import tomllib
from urllib.request import Request, urlopen


def validate_files(files):
    if not any(name.startswith('tests/') and name.endswith('.rs') for name in files):
        raise ValueError('Crate archive must ship integration tests')
    if not {'LICENSE-MIT', 'LICENSE-APACHE'} <= files:
        raise ValueError('Crate archive must ship both declared license files')


def package_environment(root):
    """An extracted archive must not select the runner's unrelated default Rust."""
    toolchain = tomllib.loads((root / 'rust-toolchain.toml').read_text())['toolchain']['channel']
    if not re.fullmatch(r'(?:[0-9]+\.[0-9]+\.[0-9]+|nightly-[0-9]{4}-[0-9]{2}-[0-9]{2})', toolchain):
        raise ValueError('Package tests require an exact compiler pin')
    return {**os.environ, 'RUSTUP_TOOLCHAIN': toolchain}


def main():
    package_env = package_environment(Path.cwd())
    package = tomllib.loads(Path('Cargo.toml').read_text())['package']
    name, version = package['name'], package['version']
    stem = f'{name}-{version}'
    published = os.environ.get('PACKAGE_PUBLISHED') == 'true'
    with tempfile.TemporaryDirectory(prefix='cargo-package-test-') as directory:
        root = Path(directory)
        if published:
            url = f'https://static.crates.io/crates/{name}/{stem}.crate'
            with urlopen(Request(url, headers={'User-Agent': 'legra-package-validation'}), timeout=60) as response:
                data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError('Published crate exceeds 64 MiB validation limit')
            archive_path = root / f'{stem}.crate'
            archive_path.write_bytes(data)
        else:
            subprocess.run(['cargo', 'package', '--locked', '--allow-dirty', '--no-verify',
                            '--target-dir', str(root)], env=package_env, check=True)
            archive_path = root / 'package' / f'{stem}.crate'
        with tarfile.open(archive_path) as archive:
            files = {member.name.removeprefix(stem + '/') for member in archive.getmembers()}
            validate_files(files)
            tracked = subprocess.check_output(['git', 'ls-files', 'tests/'], text=True).splitlines()
            missing = set(tracked) - files
            if missing:
                raise ValueError(f'Published archive omits tracked tests: {sorted(missing)}')
            if published:
                identity = json.load(archive.extractfile(f'{stem}/.cargo_vcs_info.json'))
                if identity['git']['sha1'] != os.environ['RELEASE_REVISION']:
                    raise ValueError('Published crate differs from tested source revision')
            archive.extractall(root / 'unpacked', filter='data')
        unpacked = root / 'unpacked' / stem
        env = {**package_env, 'CARGO_TARGET_DIR': str(root / 'test-build')}
        for selection in ['--all-targets', '--doc']:
            # A binary-only package has no doctest target.
            if selection == '--doc':
                metadata = json.loads(subprocess.check_output(
                    ['cargo', 'metadata', '--no-deps', '--format-version', '1'], cwd=unpacked, env=env))
                if not any('lib' in target['kind'] for pkg in metadata['packages'] for target in pkg['targets']):
                    continue
            subprocess.run(['cargo', 'test', '--locked', selection, '--', '--test-threads=1'],
                           cwd=unpacked, env=env, check=True)
        print(f'Validated {stem} archive sha256:{hashlib.file_digest(archive_path.open("rb"), "sha256").hexdigest()}')


if __name__ == '__main__':
    main()
