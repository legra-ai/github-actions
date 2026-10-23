"""Explicit manifest boundary shared by release preparation and tested tagging."""

from pathlib import Path
import re
import subprocess
import tomllib


class ReleaseManifest:
    """Keep native manifest spelling separate from the existing release policy."""

    def __init__(self, kind):
        if kind not in ('cargo', 'uv'):
            raise ValueError(f'Unsupported release manifest kind: {kind!r}')
        self.kind = kind
        self.path = 'Cargo.toml' if kind == 'cargo' else 'pyproject.toml'
        self.lock = 'Cargo.lock' if kind == 'cargo' else 'uv.lock'

    def policy_version(self, version):
        if not isinstance(version, str):
            raise ValueError('Release manifest version must be a string')
        base = r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)'
        suffix = (r'(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?' if self.kind == 'cargo'
                  else r'(?:(a|b|rc)(0|[1-9]\d*))?')
        match = re.fullmatch(f'({base}){suffix}', version)
        if match is None:
            raise ValueError(f'Unsupported {self.kind} release manifest version: {version!r}')
        base, channel, candidate = match.groups()
        if channel is None:
            return base
        channel = {'a': 'alpha', 'b': 'beta'}.get(channel, channel)
        return f'{base}-{channel}.{candidate}'

    def manifest_version(self, policy_version):
        if self.kind == 'cargo':
            self.policy_version(policy_version)
            return policy_version
        match = re.fullmatch(r'(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?', policy_version)
        if match is None:
            raise ValueError(f'Unsupported release policy version: {policy_version!r}')
        base, channel, candidate = match.groups()
        marker = {'alpha': 'a', 'beta': 'b', 'rc': 'rc'}.get(channel)
        version = base if marker is None else f'{base}{marker}{candidate}'
        self.policy_version(version)
        return version

    def version(self, contents=None):
        document = tomllib.loads(Path(self.path).read_text() if contents is None else contents)
        if self.kind == 'cargo':
            workspace = document.get('workspace', {})
            package = workspace.get('package', document.get('package', {}))
        else:
            package = document.get('project', {})
            if not isinstance(package, dict):
                raise ValueError('Release requires a static project.version')
            dynamic = package.get('dynamic', [])
            if not isinstance(dynamic, list) or any(not isinstance(field, str) for field in dynamic):
                raise ValueError('Project dynamic fields must be an array of strings')
            if 'version' in dynamic:
                raise ValueError('Release requires a static project.version')
        if not isinstance(package, dict) or 'version' not in package:
            raise ValueError(f'Release manifest {self.path} has no static version')
        version = package['version']
        self.policy_version(version)
        return version

    def bump(self, version):
        self.version()
        self.policy_version(version)
        if self.kind == 'cargo':
            subprocess.run(['cargo', 'version-info', 'bump', '--version', version, '--no-commit'], check=True)
        else:
            if not Path(self.lock).is_file():
                raise ValueError('Native uv release preparation requires uv.lock')
            subprocess.run(['uv', 'version', version, '--no-sync'], check=True)

    def release_paths(self, changed):
        paths = list(changed)
        if Path(self.lock).exists() and self.lock not in paths:
            paths.append(self.lock)
        if self.path not in paths:
            raise RuntimeError(f'Version bump did not update {self.path}')
        return paths
