# Tag tested release

Call only after every validation/build job succeeds, using the revision output
from `prepare-cargo-release`. Requires a full checkout and `contents: write`.
Validates the manifest at that revision and creates/pushes its annotated version
tag. An existing tag must resolve to exactly that commit; conflicts are fatal.
Create a draft GitHub release afterward and finalize it only after publication.

Numeric `alpha`, `beta`, and `rc` Cargo prereleases are supported. Set
`tag-format: pep440` in both preparation and tagging for repositories whose
existing tags use Python spelling (`v0.2.0a1` for `0.2.0-alpha.1`). Manifest
validation always uses the Cargo version; tag spelling never changes its source.
