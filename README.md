# legra-ai/github-actions

[![License: CC BY-SA 4.0](https://img.shields.io/badge/license-CC%20BY--SA%204.0-lightgrey.svg)](LICENSE)

Reusable GitHub Actions for Rust CI/CD workflows.

## Overview

This repository contains reusable composite actions for common CI/CD tasks
in Rust projects. All actions provide caching and consistent behavior
across workflows.

## Available Actions

See [`.github/actions/README.md`](.github/actions/README.md) for complete
documentation of all available actions.

### Quick Links

- **[Setup Actions](.github/actions/README.md#setup-actions)** - Install
  development tools (cargo-binstall, cargo-edit, cocogitto, etc.)
- **[Version Management](.github/actions/README.md#version-management-actions)** -
  Get and calculate versions
- **[Changelog & Release](.github/actions/README.md#changelog--release-actions)** -
  Generate changelogs, PR logs, release pages, and badges
- **[Release Management](.github/actions/README.md#release-management-actions)** -
  Create releases, attach artifacts, update badges

## Usage

Reference actions using the path syntax:

```yaml
- name: Setup Cocogitto
  uses: legra-ai/github-actions/.github/actions/setup-cocogitto@main
  with:
    version: 6.5.0 # Optional, defaults to env var or 6.5.0

- name: Generate changelog
  uses: legra-ai/github-actions/.github/actions/generate-changelog@main
  with:
    release-tag: v0.1.0
```

## Versioning

- **Initial release**: `v0.0.1`
- Use `@main` until all bugs are ironed out
- After stabilization, bump to `v1.0.0` and use `@v1` going forward

## License

Creative Commons Attribution-ShareAlike 4.0 International

See [LICENSE](LICENSE) for details.

### Tested Cargo maintenance

Use `.github/workflows/cargo-maintenance.yml` for a single public Cargo package.
Pin both the reusable workflow reference and its `policy-revision` input to the
same reviewed 40-character shared-actions commit. Set `crate-name` and `kind`
(`library` or `binary`), and inherit the organization release secrets. PR jobs
require no secrets. Only main mints the repository-scoped release writer.

Callers provide `rust-toolchain.toml`, `rustfmt-toolchain`, `scripts/fmt.sh`, a
tracked lockfile, and integration tests included in the crate alongside both
license files. Daily scheduled recovery and the shared trusted title / tested
Dependabot merge workflows belong in the caller. Remove old version/tag/manual
publishers when adopting this workflow.

All jobs check out the prepared source revision. Binary packages build six
platform archives before tagging/publishing, preserve original draft assets on
recovery, and execute public downloads on Linux, macOS and Windows. Package tests
run from extracted archives on all three systems, then from the public registry
before the GitHub draft is made public. Required-check policy and independent
release-health monitoring must also be configured; this workflow alone does not
certify a repository's maintenance policy.
