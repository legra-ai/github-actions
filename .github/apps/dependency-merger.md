# Dedicated dependency merger

The release writer can bypass CI to record signed version commits. Reusing it
for PR merges lets outdated green heads bypass strict base checks. A client
precheck cannot close the final race: GitHub's merge API compares only the head
SHA. The dedicated merger has no CI bypass, so GitHub enforces that final check.

## App grant

Register the private org-owned App described by
[the manifest](dependency-merger-manifest.json). It requests only repository
contents/write, pull_requests/write and administration/read. Webhooks are
inactive. It has no Actions, checks, statuses, administration-write or org-wide
permissions. Install only on the repositories included in the approved rollout.

Store `RELEASE_MERGER_APP_ID` and `RELEASE_MERGER_APP_KEY` as organization secrets
selected for those repositories. Keep the existing release-writer secrets for
publication only. Never print or commit private keys.

## Server policy

Require strict CI checks for current main, signed commits and linear history.
Grant the new App a bypass of the separate review rule only. Do not add it to
check-rule bypasses. Preserve required reviews for other actors and preserve
existing release-writer exceptions needed for signed version preparation.

For github-actions itself, introduce strict required contexts: test,
workflow-identity, package-isolation (ubuntu-24.04), package-isolation (macos-15),
package-isolation (windows-latest) and Conventional Commit, all from integration
15368. This repo has no version publisher and needs no CI-bypass actor. Its
review rule may allow the administrator role and the dedicated merger only.

## Activation

Provision the App and secrets before merging the workflow change. Validate the
new token against a protected canary branch: current tested heads may merge;
stale heads must fail, including when main advances between precheck and merge.
The canary must not run publication. Record GitHub-verified signatures.

Then update consumers to the merged policy revision and add the required
`app-id` input and dedicated credentials to their trusted merge handlers. Never
silently reuse release-writer credentials. Observe a real dependency merge and
its normal main CI/publication. Record incomplete rollout requirements.
