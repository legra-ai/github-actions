const {test} = require('node:test');
const assert = require('node:assert/strict');
const merge = require('../.github/actions/merge-tested-dependabot/merge.cjs');

function fixture() {
  const calls = [];
  const rebases = [];
  const comments = [];
  const run = {event: 'pull_request', conclusion: 'success', head_sha: 'tested', head_branch: 'dependabot/cargo/serde', head_repository: {full_name: 'org/crate'}};
  const pr = {number: 1, title: 'build(deps): update serde', body: 'Dependency update.', user: {login: 'dependabot[bot]'}, head: {sha: 'tested', repo: {full_name: 'org/crate'}}, base: {ref: 'main'}};
  const comparison = {status: 'ahead', merge_base_commit: {sha: 'current-base'}};
  const appId = 123;
  const viewer = {login: 'legra-dependency-merger[bot]'};
  const app = {id: appId, permissions: {contents: 'write', pull_requests: 'write', administration: 'read'}};
  const policy = {bypass_actors: [{actor_type: 'Integration', actor_id: 456}]};
  const rules = [{type: 'required_status_checks', ruleset_id: 99,
    parameters: {strict_required_status_checks_policy: true, required_status_checks: [{context: 'test'}]}}];
  const github = {
    graphql: async () => ({viewer}),
    paginate: {iterator: async function* () {yield {data: comments};}},
    request: async route => ({data: route.endsWith('/{ruleset_id}') ? policy : rules}),
    rest: {
    apps: {getBySlug: async () => ({data: app})},
    issues: {listComments: async () => ({}), createComment: async args => {rebases.push(args); return {data: {id: 1}};}},
    repos: {getBranch: async () => ({data: {commit: {sha: 'current-base'}}}),
      compareCommitsWithBasehead: async () => ({data: comparison})},
    pulls: {list: async () => ({data: [pr]}), merge: async args => {calls.push(args); return {data: {merged: true}};}},
    actions: {createWorkflowDispatch: async args => calls.push(args)},
  }};
  return {calls, rebases, comments, run, pr, github, comparison, appId, viewer, app, policy, rules, context: {repo: {owner: 'org', repo: 'crate'}, payload: {workflow_run: run}}};
}

test('successful CI merges only its tested head; the writer merge itself starts main CI', async () => {
  const f = fixture();
  await merge(f.github, f.context, f.appId);
  assert.equal(f.calls[0].sha, 'tested');
  assert.equal(f.calls[0].merge_method, 'squash');
  assert.equal(f.calls[0].commit_title, 'build(deps): update serde (#1)');
  assert.equal(f.calls[0].commit_message, 'Dependency update.');
  assert.equal(f.calls.length, 1, 'no explicit dispatch: the App-token merge triggers the push run');
});

for (const title of ['Update serde', 'build: update serde', 'oops(deps): update serde', 'fix(deps): ok\nforged']) {
  test(`invalid current title cannot merge: ${title}`, async () => {
    const f = fixture();
    f.pr.title = title;
    await assert.rejects(merge(f.github, f.context, f.appId), /Conventional Commit/);
    assert.deepEqual(f.calls, []);
  });
}

for (const scenario of ['failed', 'updated', 'human', 'fork', 'main-run']) {
  test(`${scenario} cannot merge`, async () => {
    const f = fixture();
    if (scenario === 'failed') f.run.conclusion = 'failure';
    if (scenario === 'updated') f.pr.head.sha = 'untested';
    if (scenario === 'human') f.pr.user.login = 'someone';
    if (scenario === 'fork') f.pr.head.repo.full_name = 'other/crate';
    if (scenario === 'main-run') f.run.event = 'push';
    await merge(f.github, f.context, f.appId);
    assert.deepEqual(f.calls, []);
  });
}

test('merge refusal cannot dispatch publication', async () => {
  const f = fixture();
  f.github.rest.pulls.merge = async () => ({data: {merged: false}});
  await assert.rejects(merge(f.github, f.context, f.appId));
  assert.deepEqual(f.calls, []);
});

for (const status of ['behind', 'diverged', 'identical']) {
  test(`green CI cannot merge a head whose ancestry is ${status} current main`, async () => {
    const f = fixture();
    f.comparison.status = status;
    f.comparison.merge_base_commit.sha = 'old-base';
    await assert.rejects(merge(f.github, f.context, f.appId), /current main.*rebase.*retest/i);
    assert.deepEqual(f.calls, []);
  });
}

test('comparison must prove that the exact current main commit is an ancestor', async () => {
  const f = fixture();
  f.comparison.merge_base_commit.sha = 'old-base';
  await assert.rejects(merge(f.github, f.context, f.appId), /current main.*rebase.*retest/i);
  assert.deepEqual(f.calls, []);
});

test('main advancing during the ancestry check invalidates the green run', async () => {
  const f = fixture();
  let reads = 0;
  f.github.rest.repos.getBranch = async () => ({data: {commit: {sha: ++reads === 1 ? 'current-base' : 'new-base'}}});
  await assert.rejects(merge(f.github, f.context, f.appId), /main advanced.*rebase.*retest/i);
  assert.deepEqual(f.calls, []);
});

for (const operation of ['getBranch', 'compareCommitsWithBasehead']) {
  test(`${operation} failure cannot authorize a merge`, async () => {
    const f = fixture();
    f.github.rest.repos[operation] = async () => {throw new Error('API unavailable');};
    await assert.rejects(merge(f.github, f.context, f.appId), /API unavailable/);
    assert.deepEqual(f.calls, []);
  });
}

for (const scenario of ['writer-token', 'user-token', 'admin-write', 'extra-write',
                         'missing-checks', 'non-strict', 'empty-checks', 'role-bypass', 'hidden-policy']) {
  test(`${scenario} cannot weaken server enforcement`, async () => {
    const f = fixture();
    if (scenario === 'writer-token') f.policy.bypass_actors.push({actor_type: 'Integration', actor_id: f.appId});
    if (scenario === 'user-token') f.viewer.login = 'operator';
    if (scenario === 'admin-write') f.app.permissions.administration = 'write';
    if (scenario === 'extra-write') f.app.permissions.actions = 'write';
    if (scenario === 'missing-checks') f.rules.length = 0;
    if (scenario === 'non-strict') f.rules[0].parameters.strict_required_status_checks_policy = false;
    if (scenario === 'empty-checks') f.rules[0].parameters.required_status_checks.length = 0;
    if (scenario === 'role-bypass') f.policy.bypass_actors.push({actor_type: 'RepositoryRole', actor_id: 5});
    if (scenario === 'hidden-policy') delete f.policy.bypass_actors;
    await assert.rejects(merge(f.github, f.context, f.appId));
    assert.deepEqual(f.calls, []);
  });
}

test('a different App cannot impersonate the configured merger', async () => {
  const f = fixture();
  f.app.id = 456;
  await assert.rejects(merge(f.github, f.context, f.appId), /token identity/);
  assert.deepEqual(f.calls, []);
});

test('a missing App ID cannot reuse the release writer implicitly', async () => {
  const f = fixture();
  await assert.rejects(merge(f.github, f.context), /dedicated merge App ID/);
  assert.deepEqual(f.calls, []);
});

test('GitHub refusing a base race is propagated without retry or dispatch', async () => {
  const f = fixture();
  f.github.rest.pulls.merge = async () => {throw new Error('405: branch is behind main');};
  await assert.rejects(merge(f.github, f.context, f.appId), /405/);
  assert.deepEqual(f.calls, []);
});

test('stale CI requests Dependabot own signed rebase and still fails this merge attempt', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  await assert.rejects(merge(f.github, f.context, f.appId), /rebase.*retest/i);
  assert.deepEqual(f.calls, []);
  assert.equal(f.rebases.length, 1);
  assert.equal(f.rebases[0].issue_number, 1);
  assert.match(f.rebases[0].body, /^@dependabot rebase\n/);
  assert.match(f.rebases[0].body, /legra-rebase:tested:current-base/);
});

test('rerunning the same stale head does not repeat the authenticated rebase request', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.comments.push({user: {login: f.viewer.login}, body: '<!-- legra-rebase:tested:current-base -->'});
  await assert.rejects(merge(f.github, f.context, f.appId), /rebase.*retest/i);
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.rebases, []);
});

test('a forged rebase marker cannot suppress the trusted request', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.comments.push({user: {login: 'someone'}, body: '<!-- legra-rebase:tested:current-base -->'});
  await assert.rejects(merge(f.github, f.context, f.appId));
  assert.equal(f.rebases.length, 1);
  assert.deepEqual(f.calls, []);
});

test('comment pages are streamed before requesting another rebase', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.github.paginate.iterator = async function* () {
    yield {data: [{user: {login: 'someone'}, body: 'unrelated'}]};
    yield {data: [{user: {login: f.viewer.login}, body: '<!-- legra-rebase:tested:current-base -->'}]};
  };
  await assert.rejects(merge(f.github, f.context, f.appId));
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.rebases, []);
});

test('failure to request a signed rebase cannot authorize the stale head', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.github.rest.issues.createComment = async () => {throw new Error('Rebase comment denied');};
  await assert.rejects(merge(f.github, f.context, f.appId), /Rebase comment denied/);
  assert.deepEqual(f.calls, []);
});

test('workflow dependency updates remain supported by the merge identity', async () => {
  const f = fixture();
  f.app.permissions.workflows = 'write';
  await merge(f.github, f.context, f.appId);
  assert.equal(f.calls.length, 1);
});
