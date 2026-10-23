# Tag tested release

Call only after every validation/build job succeeds, using the revision output
from `prepare-cargo-release`. Requires a full checkout and `contents: write`.
Validates the manifest at that revision and creates/pushes its annotated version
tag. An existing tag must resolve to exactly that commit; conflicts are fatal.
Create a draft GitHub release afterward and finalize it only after publication.

Numeric `alpha`, `beta`, and `rc` Cargo prereleases are supported. Set
`tag-format: pep440` in both preparation and tagging for repositories whose
existing tags use Python spelling (`v0.2.0a1` for `0.2.0-alpha.1`). Manifest
validation uses the explicitly selected manifest; tag spelling never changes its source.

Set `manifest-kind: uv` in both actions for a static Python project. Validation
then reads `pyproject.toml` at the exact tested revision, and the `version` input
must match that manifest's PEP 440 spelling. Stable, numeric `a`, `b` and `rc`
versions are supported; dynamic and other version forms fail. The default Cargo
backend retains its existing manifest and semantic-version behavior. Both use
the same immutable tag check and publication remains in the calling pipeline.
