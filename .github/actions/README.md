# Reusable GitHub Actions

This directory contains reusable composite actions for common CI/CD
tasks. These actions provide caching and consistent behavior across
workflows.

## Available Actions

Each action has its own README with detailed documentation. Click on
the action name to view its documentation:

### Setup Actions

- **[setup-cargo-binstall](setup-cargo-binstall/README.md)** - Install
  cargo-binstall for fast binary installations
- **[setup-cargo-edit](setup-cargo-edit/README.md)** - Install
  cargo-edit (provides cargo set-version)
- **[setup-cargo-fmt-toml](setup-cargo-fmt-toml/README.md)** - Install
  cargo-fmt-toml for Cargo.toml formatting
- **[setup-cargo-propagate-features](setup-cargo-propagate-features/README.md)** -
  Install cargo-propagate-features
- **[setup-cargo-version-info](setup-cargo-version-info/README.md)** -
  Install cargo-version-info for unified version management
- **[setup-cocogitto](setup-cocogitto/README.md)** - Install Cocogitto
  for version management
- **[setup-dotenvage](setup-dotenvage/README.md)** - Install dotenvage
  for environment file processing
- **[setup-dioxus](setup-dioxus/README.md)** - Install Dioxus CLI
- **[setup-ekg-cli](setup-ekg-cli/README.md)** - Build EKG CLI
  (project-specific)
- **[setup-rust-toolchain-from-file](setup-rust-toolchain-from-file/README.md)** -
  Read the channel from `rust-toolchain.toml` and install the toolchain,
  optionally adding the Swatinem shared rust-cache

### Version Management Actions

- **[get-version](get-version/README.md)** - Get current version from
  Cargo.toml and compare with latest tag
- **[calculate-next-version](calculate-next-version/README.md)** -
  Calculate next patch version from latest release

### Changelog & Release Actions

- **[generate-changelog](generate-changelog/README.md)** - Generate
  changelog from conventional commits
- **[generate-pr-log](generate-pr-log/README.md)** - Generate list of
  merged PRs
- **[generate-release-page](generate-release-page/README.md)** -
  Generate complete release page
- **[generate-build-badges](generate-build-badges/README.md)** -
  Generate build artifact badges

### Release Management Actions

- **[create-or-update-release](create-or-update-release/README.md)** -
  Create or update GitHub release
- **[publish-draft-release](publish-draft-release/README.md)** -
  Publish draft release
- **[attach-artifact-to-release](attach-artifact-to-release/README.md)** -
  Attach artifacts to release
- **[update-release-badge](update-release-badge/README.md)** - Update
  badge in release body
- **[package-artifacts](package-artifacts/README.md)** - Package
  artifacts into zip files
- **[generate-manifest](generate-manifest/README.md)** - Generate
  manifest.json for distribution

---

## Implementation Details

### Caching Strategy

All actions use GitHub Actions cache to speed up builds:

- **cargo-binstall**: Cached by OS and architecture
- **cargo-edit**: Cached by version, OS, and architecture
- **cargo-fmt-toml**: Cached by OS and architecture
- **cargo-version-info**: Cached by OS and architecture
- **cocogitto**: Cached by version, OS, and architecture (still used
  for version bumping)

Cache keys include platform and architecture to ensure cross-platform
builds work correctly.

### Dependency Chain

Actions have the following dependency chain:

```text
setup-cocogitto
    ├── setup-cargo-binstall
    └── setup-cargo-edit
            └── setup-cargo-binstall

setup-cargo-version-info
    └── setup-cargo-binstall

generate-changelog
generate-pr-log
generate-release-page
generate-build-badges
    └── setup-cargo-version-info
```

This ensures all required tools are available with proper caching.

### PATH Management

All actions automatically add `~/.cargo/bin` to PATH, making installed
tools immediately available in subsequent steps.

### Cross-Platform Support

All actions work on:

- Linux (ubuntu-latest, ubuntu-24.04, etc.)
- macOS (macos-latest, macos-15-xlarge, etc.)
- Windows (windows-latest)

Windows binaries are handled with `.exe` extension automatically.

---

## Example Workflow

Here's a complete example using all actions:

```yaml
name: Release

on:
  push:
    branches: [main]

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0

      - name: Configure Git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

      - name: Setup Cocogitto
        uses: ./.github/actions/setup-cocogitto
        # This automatically installs cargo-binstall and cargo-edit

      - name: Bump version
        run: cog bump --patch
        # This uses cargo set-version internally via pre_bump_hooks

      - name: Get new version
        id: version
        run: |
          VERSION=$(grep '^version' Cargo.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
          echo "version=$VERSION" >> $GITHUB_OUTPUT

      - name: Generate changelog
        uses: ./.github/actions/generate-changelog
        with:
          release-tag: v${{ steps.version.outputs.version }}
          output-file: CHANGELOG.md

      - name: Create GitHub Release
        run: |
          gh release create "v${{ steps.version.outputs.version }}" \
            --title "v${{ steps.version.outputs.version }}" \
            --notes-file CHANGELOG.md
        env:
          GH_TOKEN: ${{ github.token }}
```

---

## Maintenance

### Updating cargo-edit Version

To update the cargo-edit version, edit
`.github/actions/setup-cargo-edit/action.yml` and change the version
in the cache key and install command:

```yaml
key: cargo-edit-0.13.0-${{ runner.os }}-${{ runner.arch }}
# and
cargo binstall --no-confirm --force --version 0.13.0 cargo-edit
```

### Updating Cocogitto Version

To update the Cocogitto version, edit
`.github/actions/setup-cocogitto/action.yml` and change the version in
the cache key and install command:

```yaml
key: cocogitto-6.5.0-${{ runner.os }}-${{ runner.arch }}
# and
cargo binstall --no-confirm --force --version 6.5.0 cocogitto
```

### Testing Locally

The bash scripts in `.bash/` can be tested locally:

```bash
# Test changelog generation
./.bash/gha-generate-changelog.sh CHANGELOG.md v0.1.3
```

---

---

## Further Reading

- [cargo-edit Documentation](https://github.com/killercup/cargo-edit)
- [Cocogitto Documentation](https://docs.cocogitto.io/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [GitHub Actions Composite Actions](https://docs.github.com/actions/creating-actions/creating-a-composite-action)
