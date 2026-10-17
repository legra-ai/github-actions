# Verify registry publication

Run after uploading, before publishing the GitHub release. Requires Python 3.11+.
Uses the same archive verification as the independent release monitor:

- `crates`: download the crate and match its VCS source to the tested revision.
- `npm`: download the tarball and match the preserved archive SHA-256.
- `pypi`: require every preserved wheel and verify its downloaded SHA-256.

For npm/PyPI, `archive` is the original release ZIP containing `manifest.json`
with `version`, `revision`, and a filename-to-SHA-256 `files` object. The manifest
must match the supplied tested version/revision before any registry request.
The caller must obtain this immutable ZIP through its existing recovery pipeline.

Only missing registry metadata or missing expected wheels are polled. Wrong
identities, duplicate files, authentication failures, service failures and download
errors fail immediately. Polling defaults to 300 seconds, with a 600-second cap
and five-second intervals; each HTTP operation also has its own 30-second timeout.
Exhausting the visibility budget fails the release. There is no alternate publisher,
credential fallback, rebuild, or acceptance of arbitrary upload errors.

```yaml
- uses: legra-ai/github-actions/.github/actions/verify-registry-publication@<reviewed-sha>
  with:
    registry: pypi
    package: dotenvage
    version: ${{ needs.prepare.outputs.version }}
    revision: ${{ needs.prepare.outputs.revision }}
    archive: release-packages.zip
```

Registry checks are anonymous. No GitHub or registry credentials are needed or sent.
