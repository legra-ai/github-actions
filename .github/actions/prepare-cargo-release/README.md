# Prepare Cargo release

Run after a full-history checkout of the workflow revision. Pass its `revision`
output to **every** validation, build and publication checkout. Only release when
`release` is `true` and all repository checks succeed. Main release workflows must
use one concurrency group with `cancel-in-progress: false`.

The action compares all commits since the latest reachable stable version tag.
Fixes and dependency changes produce a patch; `feat` a minor;
`!` or `BREAKING CHANGE` a major. Documentation, style and CI-only changes do not
release. A higher manifest version is respected. No tag baseline uses the manifest.
Every considered commit must match the scoped Conventional Commit policy shared
with PR-title and merge-time validation. Invalid headers fail, including during
manual bumps and initial releases; no unknown-message patch fallback exists.

On main, `cargo version-info` prepares the version and its configured companion
files and GitHub's GraphQL API records a verified commit on main with an
expected-head guard. `GH_TOKEN` must be the organisation's release-writer GitHub
App token, minted per run and scoped to the repository: the App is a bypass
actor on the main rulesets (the review gate exists for outside contributors),
and its push starts the ordinary main pipeline, which resumes at that exact
prepared commit instead of preparing again. A main checkout that is no longer
the remote head never prepares anything. PR runs return their checked-out
revision without mutation.

Requires a full git checkout, Python 3.11+, Rust and GitHub CLI.
No publishing token is used here. Registry publication belongs exclusively to the
calling pipeline after its validation gate.
