# setup-rust-toolchain-from-file

Read the Rust channel from `rust-toolchain.toml` and install that exact
toolchain, optionally adding the
[`Swatinem/rust-cache`](https://github.com/Swatinem/rust-cache) shared
target cache. Collapses the boilerplate every Rust CI job otherwise
repeats — sed-parse the channel out of `rust-toolchain.toml`, call
`actions-rust-lang/setup-rust-toolchain`, then call `rust-cache` — into
a single composite action.

## Usage

```yaml
- name: Checkout code
  uses: actions/checkout@v6

- name: Set up Rust toolchain
  uses: dataroadinc/github-actions/.github/actions/setup-rust-toolchain-from-file@main
  with:
    components: clippy,rustfmt
    cache-shared-key: my-repo-ci
```

For lint-only or format-only jobs that do not build, skip the cache:

```yaml
- name: Set up Rust toolchain
  uses: dataroadinc/github-actions/.github/actions/setup-rust-toolchain-from-file@main
  with:
    components: rustfmt
    cache: "false"
```

## Inputs

| Input | Default | Description |
| ----- | ------- | ----------- |
| `path` | `rust-toolchain.toml` | Path (relative to checkout root) of the rust-toolchain file to read. |
| `components` | `""` | Comma-separated rustup components forwarded to `actions-rust-lang/setup-rust-toolchain`. |
| `cache` | `"true"` | When `"true"`, invokes `Swatinem/rust-cache`. Set to `"false"` for jobs that do not compile. |
| `cache-shared-key` | `""` | `shared-key` passed to `Swatinem/rust-cache`. Multiple jobs in the same workflow should share a value. |

## Outputs

| Output | Description |
| ------ | ----------- |
| `toolchain` | The toolchain channel resolved from the file (e.g. `nightly-2025-08-29`). |

## What it does

1. Resolves the channel from `rust-toolchain.toml` (one `channel = "..."` line under `[toolchain]`).
2. Calls
   [`actions-rust-lang/setup-rust-toolchain@v1`](https://github.com/actions-rust-lang/setup-rust-toolchain)
   with that channel and the requested components.
3. Optionally calls
   [`Swatinem/rust-cache@v2`](https://github.com/Swatinem/rust-cache)
   with the supplied shared key.

## Why a composite action

Without this action, every Rust job in a workflow repeats the same
three blocks (≈30 lines each):

```yaml
- name: Resolve Rust toolchain
  id: rust_toolchain
  run: |
    VERSION="$(sed -n 's/^channel = "\([^"]*\)"/\1/p' rust-toolchain.toml | head -n 1)"
    if [ -z "$VERSION" ]; then
      echo "Failed to resolve Rust toolchain channel" >&2
      exit 1
    fi
    echo "version=$VERSION" >> "$GITHUB_OUTPUT"

- name: Set up Rust toolchain
  uses: actions-rust-lang/setup-rust-toolchain@v1
  with:
    toolchain: ${{ steps.rust_toolchain.outputs.version }}
    components: clippy,rustfmt

- name: Cache Rust artifacts
  uses: Swatinem/rust-cache@v2
  with:
    shared-key: my-repo-ci
```

A workflow with 8 Rust jobs ends up carrying ≈240 lines of boilerplate
that drift independently and have no single source of truth. This
action makes that block one `uses:` line per job.

## Failure modes

- **Missing file**: `error file=<path>::rust-toolchain file not found`.
- **No `channel` line**: `error file=<path>::no channel = "..." line found in <file>`.

Both surface via `::error` annotations that GitHub renders inline on
the PR diff.

## Versioning

Use `@main` while iterating. After this and sibling actions stabilise,
the repository bumps to `v1.0.0` and consumers should pin to `@v1`.
