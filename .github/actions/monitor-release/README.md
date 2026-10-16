# Release health monitor

Runs independently of the monitored repository's publisher. The central
`release-health.yml` workflow checks the explicit fleet slice in
`.github/release-health.json` hourly and after monitoring changes land.
Dotenvage is the initial adopter.

A healthy result requires an active release workflow, a scheduled run within
36 hours, no failed/latest stalled main run, no releasable main changes older
than two hours, and the intended manifest version in every declared registry.
Crates must identify the release tag's source revision. npm tarballs and all
Python platform wheels must match the preserved recovery archive. Every CLI
archive is downloaded and checked against its GitHub SHA-256 digest.

The two-hour publication window applies only to packages that are still
absent. Authentication, registry service, identity and download failures fail
immediately. A pending result cannot close an existing alert.

The monitor creates one bot-owned issue per unhealthy repository in the
monitoring repository, updates/reopens that same issue on recurrence, and closes
it only after every check passes. A failed check also fails the workflow and
writes its findings to the job summary. GitHub issue subscriptions and Actions
failure notifications deliver the alerts; owners must keep those enabled.

Use a token with public GitHub read access and issue-write access to the
monitoring repository. Registry requests and artifact downloads never receive
the GitHub token. This monitor is for public repositories and stable `x.y.z`
versions. Register package identities and every supported CLI archive explicitly.

Read-only local verification:

```bash
python3 .github/actions/monitor-release/release_monitor.py inspect .github/release-health.json
```

`GH_TOKEN` must be present. `inspect` performs no GitHub writes. `monitor`
reconciles issues in `GITHUB_REPOSITORY`. Unhealthy results exit nonzero.

The independent central scheduler detects disabled target workflows and missing
target scheduler heartbeats. It cannot report its own total GitHub Actions
outage or its own scheduler being disabled; an external dead-man service is
needed for that additional guarantee. No such external service is provisioned
by this action.
