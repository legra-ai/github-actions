"""Decide which release mutation, if any, this maintenance run may perform.

A caller's own validation jobs (for example native bindings built beside the
shared pipeline) can only gate this reusable workflow as a whole, and they
always check out the run's own revision. Publication is therefore confined to
the run whose revision is the release revision, so that every caller job has
validated exactly what is published. A run that still needs a version commit
only writes it, after its own validation; that commit's push starts the release
revision's own run, which publishes. The one exception is finishing a release
whose tag already exists: the tag is created only by a publishing run, so its
revision was fully validated by its own run before.
"""

import os
import subprocess
import tomllib


class ReleaseDecision:
    """The release plan, read against the manifest at the planned revision."""

    def __init__(self, revision, run_revision, planned, planned_version, manifest_version, tagged):
        if planned not in ('true', 'false'):
            raise ValueError(f'Unexpected release plan: {planned!r}')
        self.revision = revision
        self.run_revision = run_revision
        self.planned = planned == 'true'
        self.planned_version = planned_version
        self.manifest_version = manifest_version
        self.tagged = tagged

    @classmethod
    def from_git(cls, revision, run_revision, planned, planned_version):
        raw = subprocess.check_output(['git', 'show', f'{revision}:Cargo.toml'], text=True)
        manifest_version = tomllib.loads(raw)['package']['version']
        tags = subprocess.check_output(['git', 'tag', '--points-at', revision], text=True).split()
        return cls(revision, run_revision, planned, planned_version, manifest_version,
                   f'v{manifest_version}' in tags)

    @property
    def own_revision(self):
        return self.revision == self.run_revision

    @property
    def needs_version_commit(self):
        return self.planned and self.planned_version != self.manifest_version

    @property
    def write_version(self):
        return self.needs_version_commit and self.own_revision

    @property
    def publish(self):
        return self.planned and not self.needs_version_commit and (self.own_revision or self.tagged)

    def outputs(self):
        return {'version': self.manifest_version,
                'write-version': str(self.write_version).lower(),
                'publish': str(self.publish).lower()}


def main():
    decision = ReleaseDecision.from_git(os.environ['RELEASE_REVISION'], os.environ['RUN_REVISION'],
                                        os.environ['RELEASE_PLANNED'],
                                        os.environ['RELEASE_PLANNED_VERSION'])
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        for key, value in decision.outputs().items():
            stream.write(f'{key}={value}\n')


if __name__ == '__main__':
    main()
