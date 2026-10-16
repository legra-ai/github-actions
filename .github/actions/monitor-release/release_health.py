"""Check release liveness separately from installation-channel completeness."""

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import tomllib

from release_sources import Sources


@dataclass
class Report:
    repository: str
    status: str
    findings: list[str]

    @property
    def body(self):
        details = '\n'.join(f'- {finding}' for finding in self.findings)
        return (f'<!-- release-health:{self.repository} -->\n'
                f'Release health: **{self.status}**\n\n{details}\n\n'
                f'[Release workflow](https://github.com/{self.repository}/actions)\n\n'
                'Resolve the reported publication failures, resume the existing release pipeline, '
                'and let the monitor verify recovery. Do not publish a draft before all registries succeed.')


class Inspector(Sources):
    def __init__(self, api, config, now=None):
        self.api = api
        self.config = config
        self.now = now or datetime.now(timezone.utc)
        self.root = f'repos/{config["repository"]}'
        self.workflow = f'{self.root}/actions/workflows/{config["workflow"]}'

    def age(self, value):
        return (self.now - datetime.fromisoformat(value.replace('Z', '+00:00'))).total_seconds() / 3600

    def check_workflow(self):
        workflow = self.api.github(self.workflow)
        if workflow is None or workflow['state'] != 'active':
            raise ValueError(f'Release workflow is not active: {workflow}')
        runs = self.api.github(f'{self.workflow}/runs?branch=main&per_page=1')['workflow_runs']
        if not runs:
            raise ValueError('Release workflow has never run on main')
        latest = runs[0]
        if latest['status'] == 'completed' and latest['conclusion'] != 'success':
            raise ValueError(f'Release workflow {latest["conclusion"]}: {latest["html_url"]}')
        if latest['status'] != 'completed' and self.age(latest['created_at']) > 2:
            raise ValueError(f'Release workflow stalled for over two hours: {latest["html_url"]}')

    def check_schedule(self):
        runs = self.api.github(
            f'{self.workflow}/runs?branch=main&event=schedule&per_page=1')['workflow_runs']
        workflow = self.api.github(self.workflow)
        last = runs[0]['created_at'] if runs else workflow['created_at']
        if self.age(last) > 36:
            raise ValueError('No scheduled release-workflow heartbeat within 36 hours')

    def check_unreleased(self, version):
        source = Path(__file__).parent.parent / 'prepare-cargo-release/release.py'
        spec = importlib.util.spec_from_file_location('release_health_plan', source)
        plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plan)
        # bounded: at most 5,000 unreleased commits, one 100-commit API page at a time.
        for page in range(1, 51):
            comparison = self.api.github(
                f'{self.root}/compare/v{version}...main?per_page=100&page={page}')
            if comparison is None:
                return  # A missing release tag is reported by the publication check.
            commits = comparison['commits']
            for item in commits:
                commit = item['commit']
                if plan.next_version(version, version, [commit['message']]) is not None:
                    if self.age(commit['committer']['date']) > 2:
                        raise ValueError('Releasable changes on main remain unreleased for over two hours')
            if len(commits) < 100:
                return
        raise ValueError('Unreleased history exceeds the 5,000-commit inspection limit')

    def release_age(self, version):
        reference = self.api.github(f'{self.root}/git/ref/tags/v{version}')
        if reference:
            obj = reference['object']
            kind = 'tags' if obj['type'] == 'tag' else 'commits'
            detail = self.api.github(f'{self.root}/git/{kind}/{obj["sha"]}')
            return self.age(detail['tagger']['date'] if kind == 'tags' else detail['committer']['date'])
        commits = self.api.github(f'{self.root}/commits?path=Cargo.toml&per_page=1')
        if not commits:
            raise ValueError('Cannot establish the intended version age')
        return self.age(commits[0]['commit']['committer']['date'])

    def inspect(self):
        findings = []
        for check in (self.check_workflow, self.check_schedule):
            try:
                check()
            except Exception as error:
                findings.append(str(error))
        try:
            manifest = tomllib.loads(self.api.text(f'{self.root}/contents/Cargo.toml?ref=main'))
            package = manifest.get('workspace', {}).get('package') or manifest['package']
            version = package['version']
            release = self.api.github(f'{self.root}/releases/tags/v{version}')
            pending = release is None or release['draft']
            age = self.age(release['created_at']) if release else self.release_age(version)
            publication = []
            if pending:
                publication.append(f'v{version} is not publicly released')
            for check in (self.check_registries, self.check_cli):
                try:
                    check(version, release)
                except Exception as error:
                    publication.append(str(error))
            if not pending or age > 2:
                findings.extend(publication)
            self.check_unreleased(version)
            status = 'unhealthy' if findings else ('pending' if pending else 'healthy')
            return Report(self.config['repository'], status, findings)
        except Exception as error:
            return Report(self.config['repository'], 'unhealthy', [*findings, str(error)])
