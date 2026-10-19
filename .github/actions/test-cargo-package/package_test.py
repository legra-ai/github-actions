"""Exercise the actual crate archive outside its source checkout."""
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import re
import sys
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


def optional_feature_args(package, system=None):
    """Exercise every feature on its explicitly supported CI platforms."""
    features = package['features']
    if len(features) > 4096:
        raise ValueError('Feature policy exceeds the 4096-feature manifest limit')
    metadata = package.get('metadata')
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict) or not isinstance(metadata.get('legra-ci', {}), dict):
        raise ValueError('Feature policy metadata must be a table')
    excluded = metadata.get('legra-ci', {}).get('unsupported-features', {})
    systems = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}
    if not isinstance(excluded, dict) or set(excluded) - set(systems.values()):
        raise ValueError('Unsupported-features must map known CI platforms to feature lists')
    names = set(features) - {'default'}
    for items in excluded.values():
        if (not isinstance(items, list) or any(not isinstance(item, str) for item in items)
                or len(set(items)) != len(items) or set(items) - names):
            raise ValueError('Unsupported-features contains invalid or duplicate feature names')
    for name in names:
        if all(name in excluded.get(target, []) for target in systems.values()):
            raise ValueError(f'Feature {name} is excluded from every platform')
    if not excluded:
        return ['--all-features']
    target = systems.get(system or platform.system())
    if target is None:
        raise ValueError('Feature support is not declared for this CI platform')
    unsupported = set(excluded.get(target, []))

    def closure(start):
        # bounded: feature declarations are capped above; visited breaks cycles.
        pending, seen = list(start), set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            pending.extend(item for item in features.get(name, []) if item in features)
        return seen

    if closure(['default']) & unsupported:
        raise ValueError('The default feature set requests an unsupported feature')
    supported = names - unsupported
    if closure(supported) & unsupported:
        raise ValueError('A supported feature requests an unsupported feature')
    if not unsupported:
        return ['--all-features']
    args = ['--no-default-features']
    if supported:
        args += ['--features', ','.join(sorted(supported))]
    return args


def package_metadata(root, env):
    metadata = json.loads(subprocess.check_output(
        ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1'], cwd=root, env=env))
    if len(metadata['packages']) != 1:
        raise ValueError('Package validation requires exactly one Cargo package')
    return metadata['packages'][0]


def feature_commands(package, system=None):
    flags = optional_feature_args(package, system)
    commands = [['cargo', 'test', '--locked', '--all-targets', *flags]]
    if any('lib' in target['kind'] for target in package['targets']):
        commands.append(['cargo', 'test', '--locked', '--doc', *flags])
    commands += [['cargo', 'clippy', '--locked', '--all-targets', *flags, '--', '-D', 'warnings'],
                 ['cargo', 'doc', '--locked', '--no-deps', *flags]]
    return commands


def checkout():
    env = package_environment(Path.cwd())
    package = package_metadata(Path.cwd(), env)
    for command in feature_commands(package):
        subprocess.run(command, env=env, check=True)


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
        metadata = package_metadata(unpacked, env)
        feature_args = optional_feature_args(metadata)
        for selection in [['--all-targets'], ['--all-targets', *feature_args],
                          ['--doc'], ['--doc', *feature_args]]:
            # A binary-only package has no doctest target.
            if '--doc' in selection:
                if not any('lib' in target['kind'] for target in metadata['targets']):
                    continue
            subprocess.run(['cargo', 'test', '--locked', *selection, '--', '--test-threads=1'],
                           cwd=unpacked, env=env, check=True)
        print(f'Validated {stem} archive sha256:{hashlib.file_digest(archive_path.open("rb"), "sha256").hexdigest()}')


if __name__ == '__main__':
    if sys.argv[1:] == ['checkout']:
        checkout()
    elif sys.argv[1:]:
        raise ValueError('Unknown package validation command')
    else:
        main()
