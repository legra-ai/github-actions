# Prepare tested release

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

With the default `manifest-kind: cargo`, `cargo version-info` prepares the version and its configured companion
files and GitHub's GraphQL API records a verified commit on main with an
expected-head guard. The `token` input must be the organisation's release-writer GitHub
App token, minted per run and scoped to the repository: the App is a bypass
actor on the main rulesets (the review gate exists for outside contributors),
and its push starts the ordinary main pipeline, which resumes at that exact
prepared commit instead of preparing again. A main checkout that is no longer
the remote head never prepares anything. PR runs return their checked-out
revision without mutation.

Requires a full git checkout, Python 3.11+ and GitHub CLI. The Cargo backend also
requires Rust. The explicit `manifest-kind: uv` backend installs pinned uv and
does not install or invoke Cargo.
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
With the Cargo backend, outputs carry the Cargo semantic version; companion hooks
synchronize Python's PEP 440 spelling before the verified version commit.

## Static Python projects

Set `manifest-kind: uv` in both preparation and `tag-tested-release`. This reads
the static `[project].version` in `pyproject.toml` and updates it through native
`uv version VERSION --no-sync`, retaining the updated `uv.lock` in the same
verified version commit. No virtual environment or project build is needed.
`uv.lock` must already exist. The output `version` is the actual Python manifest
spelling, such as `0.2.0a2`; stable versions keep their usual `0.2.0` spelling.

The same release policy and recovery guards apply. Numeric `a`, `b` and `rc`
candidates map explicitly to its existing alpha/beta/rc policy; breaking changes
advance a candidate rather than promoting it. Select the repository's existing
tag spelling with `tag-format: pep440` or `semver`; neither is inferred. Epochs,
post/dev/local versions, dynamic or malformed versions and unknown manifest kinds
are rejected. There is no manifest fallback, dummy Cargo file or second publisher.
