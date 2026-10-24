# Prepare Cargo release

Run after a full-history checkout of the workflow revision. Pass its `revision`
output to **every** validation, build and publication checkout. Only release when
`release` is `true` and all repository checks succeed. Main release workflows must
use one concurrency group with `cancel-in-progress: false`.

The action compares all commits since the latest reachable version tag.
Fixes and dependency changes produce a patch; `feat` a minor;
`!` or `BREAKING CHANGE` a major. Documentation, style and CI-only changes do not
release. A higher manifest version is respected. No tag baseline uses the manifest.
Every considered commit must match the scoped Conventional Commit policy shared
with PR-title and merge-time validation. Invalid headers fail, including during
manual bumps and initial releases; no unknown-message patch fallback exists.

On main, `cargo version-info` prepares the version and its configured companion
files and GitHub's GraphQL API records a verified commit on main with an
expected-head guard. The `token` input must be the organisation's release-writer GitHub
App token, minted per run and scoped to the repository: the App is a bypass
actor on the main rulesets (the review gate exists for outside contributors),
and its push starts the ordinary main pipeline, which resumes at that exact
prepared commit instead of preparing again. A main checkout that is no longer
the remote head never prepares anything. PR runs return their checked-out
revision without mutation.

Requires a full git checkout, Python 3.11+, Rust and GitHub CLI.
No publishing token is used here. Registry publication belongs exclusively to the
calling pipeline after its validation gate.

Prerelease manifests support numeric `alpha`, `beta`, and `rc` candidates.
A releasable change advances the candidate number within its intended version;
even a breaking change does not silently promote an alpha to a stable release.
Changing the intended version, channel, or promoting to stable is an explicit
manifest change. Stable manifests retain the usual major/minor/patch policy.

`tag-format: pep440` recognizes existing Python tags such as `v0.2.0a1`
as Cargo version `0.2.0-alpha.1`; the default `semver` recognizes
`v0.2.0-alpha.1`. These are alternative repository policies, not aliases:
the planner uses only the selected spelling and never retags historical releases.
Outputs always carry the Cargo semantic version; companion hooks must synchronize
Python's PEP 440 spelling before the verified version commit is recorded.

## Major release approval

A major-number increase never writes a version commit or authorizes publication
without an explicit review by `jgeluk`. This includes manually raised manifests,
initial releases with a nonzero major number, and retries of unfinished major
releases. General implementation, merge, or release approval does not suffice.

Call this action first with `plan-only: 'true'` using a read-only token. The
`major-approval-required` output identifies plans needing review. This mode
returns the proposed version and source but performs no version write.

For those plans, run a job in a protected GitHub environment named
`major-release`, configured with `jgeluk` as required reviewer and administrator
bypass disabled. Name the job with the proposed version and show the workflow
source SHA. The reviewer must enter this exact approval comment:

```text
Approve major release VERSION from WORKFLOW_SOURCE_SHA
```

Run normal preparation only after that job succeeds (or is skipped for a
non-major plan). The action reads GitHub's review history for the current run
and checks the human identity, environment, exact version, and workflow source.
It does not accept a Boolean approval input. The calling workflow needs
`actions: read` for this lookup. Do not approve the environment through an agent
using the owner's credentials without the user's explicit approval of that
specific major version and source.

Keep the existing non-cancelling main concurrency group. If main advances
before preparation, the existing expected-head checks prevent stale publication.
Plan-only results must never be wired directly into publication.
