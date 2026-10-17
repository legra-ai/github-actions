"""Run read-only inspection or reconcile durable publication alerts."""

import argparse
import json
import os
from pathlib import Path
import re

from release_alerts import reconcile
from release_health import Inspector
from release_http import API


def validate_config(config):
    if set(config) != {'repository', 'workflow', 'registries', 'cli_assets', 'recovery_asset', 'assignee'}:
        raise ValueError('Release monitor configuration has missing or unknown fields')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', config['repository']):
        raise ValueError('Expected an owner/repository identity')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.ya?ml', config['workflow']):
        raise ValueError('Expected a workflow filename')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', config['assignee']):
        raise ValueError('Expected a GitHub alert owner')
    registries = config['registries']
    if not registries or set(registries) - {'crates', 'npm', 'pypi'}:
        raise ValueError('Expected explicitly supported publication registries')
    if not all(isinstance(name, str) and name for name in registries.values()):
        raise ValueError('Registry package identities must be nonempty strings')
    assets = config['cli_assets']
    if not isinstance(assets, list) or len(assets) > 16 or len(set(assets)) != len(assets):
        raise ValueError('Expected at most 16 unique CLI asset names')
    recovery = config['recovery_asset']
    if recovery is None and set(registries) != {'crates'}:
        raise ValueError('npm and PyPI require an explicit preserved recovery archive')
    for name in [*assets, *([] if recovery is None else [recovery])]:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
            raise ValueError('Expected an artifact filename without directory components')


def load_config(path):
    if path.stat().st_size > 64 * 1024:
        raise ValueError('Monitor configuration exceeds 64 KiB')
    data = json.loads(path.read_text())
    if set(data) != {'repositories'}:
        raise ValueError('Expected a repositories configuration')
    configs = data['repositories']
    # bounded: one explicitly registered fleet slice, at most 20 repositories per monitor job.
    if not isinstance(configs, list) or not 1 <= len(configs) <= 20:
        raise ValueError('Expected between one and 20 monitored repositories')
    for config in configs:
        validate_config(config)
    if len({item['repository'] for item in configs}) != len(configs):
        raise ValueError('A repository may only be registered once')
    return configs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['inspect', 'monitor'])
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    token = os.environ.get('GH_TOKEN')
    if not token:
        raise ValueError('GH_TOKEN is required for GitHub API inspection')
    api = API(token)
    failed = False
    for config in load_config(args.config):
        report = Inspector(api, config).inspect()
        print(f'{report.repository}: {report.status}\n{report.body}\n')
        if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(summary, 'a') as stream:
                stream.write(f'## {report.repository}\n\n{report.body}\n\n')
        if args.command == 'monitor':
            reconcile(api, os.environ['GITHUB_REPOSITORY'], report, config['assignee'])
        failed |= report.status == 'unhealthy'
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
