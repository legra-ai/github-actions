# Merge tested Dependabot update

Use in a trusted `workflow_run` handler for complete CI. Never check out PR
code. The dedicated merge App needs contents/write, pull_requests/write, workflows/write and
administration/read. The workflow permission permits CI dependency updates. It must have no other write permissions. Pass its numeric
`app-id` as well as its installation `token`.

The merger revalidates the current title and exact tested head. It verifies
that current main is an ancestor and rechecks main before the merge request.
Stale heads request Dependabot own signed rebase and fail the current merge
attempt. Only a new head with complete fresh CI can merge. API failures
are hard errors; the action never merges or updates a branch to hide them.

A client ancestry check alone cannot prevent main advancing before GitHub
processes the merge. The App must obey an active strict status-check ruleset
on main. The action verifies its token identity and that a strict checks rule
has no applicable bypass for it. GitHub then enforces base freshness atomically
with the merge, while the request's head SHA guards the tested head.

Use a separate release App for signed version preparation. The merge App may
bypass the review rule only; it must never bypass CI. The release writer's
identity is rejected if it is exempt from all strict checks rules.

The App-token merge starts main CI through the normal push event. No explicit
workflow dispatch is needed. Main still validates the prepared source before
publishing through the sole release pipeline.

Provisioning and rollout: [dedicated merge App](../../apps/dependency-merger.md).
