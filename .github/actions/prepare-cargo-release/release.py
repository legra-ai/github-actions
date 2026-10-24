"""Prepare one signed release revision for all downstream validation jobs."""

import base64
import json
import os
import pathlib
import re
import runpy
import subprocess


ReleaseManifest = runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / 'release_manifest.py'))['ReleaseManifest']


def version_tuple(value):
    match = re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?', value)
    if not match:
        raise ValueError(f'Expected semantic version with optional alpha/beta/rc candidate, got {value!r}')
    major, minor, patch, channel, candidate = match.groups()
    return (int(major), int(minor), int(patch),
            {'alpha': 0, 'beta': 1, 'rc': 2, None: 3}[channel], int(candidate or 0))


def tag_version(tag, tag_format):
    if tag_format not in ('semver', 'pep440'):
        raise ValueError(f'Unsupported release tag format: {tag_format!r}')
    pattern = (r'v(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?' if tag_format == 'pep440'
               else r'v(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?')
    match = re.fullmatch(pattern, tag)
    if not match:
        return None
    base, channel, candidate = match.groups()
    if channel:
        channel = {'a': 'alpha', 'b': 'beta'}.get(channel, channel)
        base += f'-{channel}.{candidate}'
    version_tuple(base)
    return base


def next_version(current, latest, messages, breaking_change_bump='major'):
    if breaking_change_bump not in ('major', 'minor'):
        raise ValueError(f'Invalid breaking-change bump policy: {breaking_change_bump!r}')
    policy = json.loads((pathlib.Path(__file__).parent.parent / 'conventional-commit/policy.json').read_text())
    for message in messages:
        header = message.splitlines()[0] if message else ''
        if not re.fullmatch(policy['header_pattern'], header):
            raise ValueError(f'Conventional Commit required: {header!r}')
    current_tuple = version_tuple(current)
    if latest is None or current_tuple > version_tuple(latest):
        return current
    if current_tuple < version_tuple(latest):
        raise ValueError('Manifest version is behind the latest release tag')
    level = 0
    for message in messages:
        header = message.splitlines()[0]
        if re.match(r'\w+(?:\([^\n]+\))?!:', header) or re.search(r'^BREAKING[ -]CHANGE:', message, re.M):
            level = max(level, 2 if breaking_change_bump == 'minor' else 3)
        elif re.match(r'feat(?:\([^\n]+\))?:', header):
            level = max(level, 2)
        elif not re.match(r'(?:docs|style|ci)\([^\n]+\):|chore\(release\):', header):
            level = max(level, 1)
    if '-' in current:
        if level == 0:
            return None
        base, candidate = current.rsplit('.', 1)
        return f'{base}.{int(candidate) + 1}'
    major, minor, patch = current_tuple[:3]
    return {0: None, 1: f'{major}.{minor}.{patch + 1}',
            2: f'{major}.{minor + 1}.0', 3: f'{major + 1}.0.0'}[level]


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def output(**values):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        for key, value in values.items():
            stream.write(f'{key}={value}\n')


def release_pending(tag):
    result = subprocess.run(['gh', 'api', f'repos/{os.environ["GITHUB_REPOSITORY"]}/releases/tags/{tag}'],
                            capture_output=True, text=True)
    if result.returncode == 0:
        return json.loads(result.stdout)['draft']
    if 'HTTP 404' in result.stderr:
        return True
    raise RuntimeError(result.stderr)


def require_major_approval(version):
    """Accept only the owner's explicit review of this version and workflow source."""
    repository = os.environ['GITHUB_REPOSITORY']
    run_id = os.environ['GITHUB_RUN_ID']
    source = os.environ['GITHUB_SHA']
    if not re.fullmatch(r'[0-9a-f]{40}', source) or not run_id.isdecimal():
        raise ValueError('Invalid workflow approval identity')
    comment = f'Approve major release {version} from {source}'
    review_environment = dict(os.environ, GH_TOKEN=os.environ['RELEASE_APPROVAL_TOKEN'])
    reviews = json.loads(gh_api(f'repos/{repository}/actions/runs/{run_id}/approvals',
                               env=review_environment))
    if any(review['state'] == 'rejected'
           and any(environment['name'] == 'major-release'
                   for environment in review['environments'])
           for review in reviews):
        raise ValueError('Major release requires explicit approval; this run has a rejected review')
    for review in reviews:
        if (review['state'] == 'approved'
                and review['user']['login'] == 'jgeluk'
                and review['user']['type'] == 'User'
                and any(environment['name'] == 'major-release'
                        for environment in review['environments'])
                and review['comment'] == comment):
            return
    raise ValueError(f'Major release requires explicit approval by jgeluk in the '
                     f'major-release environment with comment: {comment}')


def complete_plan(source, current, version, latest, manifest_kind='cargo'):
    """Expose a read-only decision or enforce approval before any release mutation."""
    manifest = ReleaseManifest(manifest_kind)
    target = manifest.manifest_version(version) if version is not None else None
    current_manifest = manifest.manifest_version(current)
    candidate = version_tuple(version) if version is not None else None
    baseline = version_tuple(latest) if latest is not None else (0, 0, 0, 3, 0)
    major = candidate is not None and (
        candidate[0] > baseline[0]
        or (candidate[0] > 0 and candidate[1:4] == (0, 0, 3) and baseline[3] < 3))
    if os.environ.get('RELEASE_PLAN_ONLY', 'false') == 'true':
        output(revision=source, release=str(version is not None).lower(),
               version=target or current_manifest, major_approval_required=str(major).lower())
        return
    if major:
        require_major_approval(target)
    if version is None:
        output(revision=source, release='false', version=current_manifest)
    elif version == current:
        output(revision=source, release='true', version=target)
    else:
        if manifest_kind == 'cargo':
            revision = write_release_commit(source, target)
        else:
            revision = write_release_commit(source, target, manifest_kind=manifest_kind)
        output(revision=revision, release='true', version=target)


def prepare():
    manifest_kind = os.environ.get('RELEASE_MANIFEST_KIND', 'cargo')
    manifest = ReleaseManifest(manifest_kind)
    source = run('git', 'rev-parse', 'HEAD')
    if os.environ['GITHUB_REF'] != 'refs/heads/main':
        output(revision=source, release='false', version='')
        return
    remote = run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0]
    if source != remote:
        subprocess.run(['git', 'fetch', 'origin', remote], check=True)
        parent = run('git', 'rev-parse', f'{remote}^')
        message = run('git', 'log', '-1', '--format=%B', remote)
        if parent == source and message.startswith('chore(release): prepare ') and f'Release source: {source}' in message:
            # Resume the exact version commit an earlier attempt already wrote.
            subprocess.run(['git', 'checkout', '--detach', remote], check=True)
            source = remote
        else:
            # A newer main run includes these changes; never publish a stale base.
            output(revision=source, release='false', version='')
            return
    current = manifest.policy_version(manifest.version())
    tag_format = os.environ.get('RELEASE_TAG_FORMAT', 'semver')
    tags = {tag: tag_version(tag, tag_format)
            for tag in run('git', 'tag', '--merged', 'HEAD', '--list', 'v*').splitlines()}
    tags = {tag: version for tag, version in tags.items() if version is not None}
    tag = max(tags, key=lambda item: version_tuple(tags[item])) if tags else None
    if tag and release_pending(tag):
        # Finish a partial multi-registry release at its immutable source before
        # advancing the version, even if newer main commits have arrived.
        previous = [version for name, version in tags.items() if name != tag]
        baseline = max(previous, key=version_tuple) if previous else None
        complete_plan(run('git', 'rev-parse', f'{tag}^{{commit}}'),
                      tags[tag], tags[tag], baseline, manifest_kind=manifest_kind)
        return
    revisions = f'{tag}..HEAD' if tag else 'HEAD'
    messages = [message.strip() for message in run('git', 'log', '--format=%B%x00', revisions).split('\0') if message.strip()]
    version = next_version(current, tags[tag] if tag else None, messages,
                           os.environ.get('RELEASE_BREAKING_CHANGE_BUMP', 'major'))
    complete_plan(source, current, version, tags[tag] if tag else None,
                  manifest_kind=manifest_kind)


def gh_api(*args, **kwargs):
    result = subprocess.run(['gh', 'api', *args], capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def write_release_commit(source, version, manifest_kind='cargo'):
    """Record the version commit on main with an expected-head guard.

    `GH_TOKEN` must be the authorized release writer (the organisation's
    release-writer GitHub App, minted per run and scoped to this repository):
    it bypasses the review gate that exists for outside contributors, and its
    push starts the ordinary main pipeline, which then finds the prepared
    version and resumes at this exact commit.
    """
    manifest = ReleaseManifest(manifest_kind)
    manifest.bump(version)
    # Release lockfiles bind validation and publication to one dependency graph,
    # including libraries that previously ignored Cargo.lock in development.
    paths = manifest.release_paths(run('git', 'diff', '--name-only').splitlines())
    additions = [{'path': path, 'contents': base64.b64encode(pathlib.Path(path).read_bytes()).decode()}
                 for path in paths]
    payload = {
        'query': 'mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid } } }',
        'variables': {'input': {
            'branch': {'repositoryNameWithOwner': os.environ['GITHUB_REPOSITORY'], 'branchName': 'main'},
            'expectedHeadOid': source,
            'message': {'headline': f'chore(release): prepare {version}', 'body': f'Release source: {source}'},
            'fileChanges': {'additions': additions},
        }},
    }
    response = json.loads(gh_api('graphql', '--input', '-', input=json.dumps(payload)))
    if response.get('errors'):
        raise RuntimeError(response['errors'])
    return response['data']['createCommitOnBranch']['commit']['oid']

if __name__ == '__main__':
    prepare()
