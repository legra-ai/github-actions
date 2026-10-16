# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a collection of reusable GitHub Actions (composite actions) for Rust CI/CD workflows. All actions are located in `.github/actions/` and provide caching and cross-platform support (Linux, macOS, Windows).

## Development Setup

```bash
# Setup git hooks (enforces Conventional Commits)
./setup-hooks.sh

# Requires cocogitto for commit validation
cargo install cocogitto
```

## Commit Message Requirements

**Scope is mandatory** - the git hook enforces this pattern:
```
<type>(<scope>): <subject>
```

Types that appear in changelog: `feat`, `fix`, `docs`, `refactor`, `perf`, `build`, `revert`
Types omitted from changelog: `style`, `test`, `ci`, `chore`

Common scopes: `actions`, `setup-*` (e.g., `setup-cocogitto`), `workflows`, `deps`

Examples:
```bash
feat(setup-dioxus): add build-from-source option
fix(actions): use --force with cargo-binstall
docs(actions): improve action documentation
```

Breaking changes use `!`: `feat(actions)!: change action input format`

## Architecture

### Action Structure

Each action in `.github/actions/` contains:
- `action.yml` - Composite action definition
- `README.md` - Action documentation with usage examples

### Action Categories

**Setup Actions** - Install tools with caching:
- `setup-cargo-binstall` - Base installer for Rust binaries
- `setup-cargo-edit` - Provides `cargo set-version`
- `setup-cocogitto` - Version management and changelog generation
- `setup-cargo-version-info` - Unified version management
- `setup-dioxus`, `setup-dotenvage`, `setup-cargo-fmt-toml`, etc.

**Version/Release Actions**:
- `get-version`, `calculate-next-version` - Version management
- `generate-changelog`, `generate-pr-log`, `generate-release-page` - Release content
- `create-or-update-release`, `publish-draft-release`, `attach-artifact-to-release`

### Dependency Chain

```
setup-cocogitto
    ├── setup-cargo-binstall
    └── setup-cargo-edit
            └── setup-cargo-binstall

setup-cargo-version-info
    └── setup-cargo-binstall

generate-* actions
    └── setup-cargo-version-info
```

### Caching Strategy

All actions cache binaries using keys that include: tool name, version, `runner.os`, and `runner.arch`. This ensures fast CI runs and cross-platform compatibility.

### PATH Management

Actions automatically add `~/.cargo/bin` to PATH.

## Testing

Bash scripts can be tested locally:
```bash
./.bash/gha-generate-changelog.sh CHANGELOG.md v0.1.3
```

## Usage Reference

Actions are referenced as:
```yaml
uses: dataroadinc/github-actions/.github/actions/setup-cocogitto@main
```

Use `@main` during development, `@vX.Y.Z` for production.
