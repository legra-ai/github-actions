# Publish tested crate

Call after all checks pass, from the exact validated revision with the generated
Cargo.lock present. Supply `CARGO_REGISTRY_TOKEN` through the calling step's env.
The action checks the public archive's VCS revision against the validated SHA on
every run. If absent, it publishes via Cargo and then waits up to 300 seconds for
the same public identity verification. A successful upload is not proof that the
crate is publicly installable. An unrelated existing version or registry error
fails immediately; only missing publication is polled. Retries verify an existing
archive without uploading it again.

The crate must retain `.cargo_vcs_info.json` in its package. Release completion
belongs after all registry publications; leave the GitHub release draft until then.
