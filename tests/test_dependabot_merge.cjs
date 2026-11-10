const {test} = require('node:test');
const assert = require('node:assert/strict');
const merge = require('../.github/actions/merge-tested-dependabot/merge.cjs');

function fixture() {
  const calls = [];
  const updates = [];
  const run = {event: 'pull_request', conclusion: 'success', head_sha: 'tested', head_branch: 'dependabot/cargo/serde', head_repository: {full_name: 'org/crate'}};
  const pr = {number: 1, title: 'build(deps): update serde', body: 'Dependency update.', user: {login: 'dependabot[bot]'}, head: {sha: 'tested', repo: {full_name: 'org/crate'}}, base: {ref: 'main'}};
  const comparison = {status: 'ahead', merge_base_commit: {sha: 'current-base'}};
  const appId = 123;
  const viewer = {login: 'legra-dependency-merger[bot]'};
  const app = {id: appId, permissions: {contents: 'write', pull_requests: 'write', administration: 'read'}};
  const policy = {enforcement: 'active', current_user_can_bypass: 'never'};
  const rules = [{type: 'required_status_checks', ruleset_id: 99,
    parameters: {strict_required_status_checks_policy: true, required_status_checks: [{context: 'test'}]}}];
  const github = {
    graphql: async () => ({viewer}),
    request: async route => ({data: route.endsWith('/{ruleset_id}') ? policy : rules}),
    rest: {
    apps: {getBySlug: async () => ({data: app})},
    repos: {get: async () => ({data: {default_branch: 'main'}}), getBranch: async () => ({data: {commit: {sha: 'current-base'}}}),
      compareCommitsWithBasehead: async () => ({data: comparison})},
    pulls: {updateBranch: async args => {updates.push(args); return {status: 202};}, list: async () => ({data: [pr]}), merge: async args => {calls.push(args); return {data: {merged: true}};}},
    actions: {createWorkflowDispatch: async args => calls.push(args)},
  }};
  return {calls, updates, run, pr, github, comparison, appId, viewer, app, policy, rules, context: {repo: {owner: 'org', repo: 'crate'}, payload: {workflow_run: run}}};
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

for (const status of ['behind', 'diverged']) {
  test(`green CI cannot merge a head whose ancestry is ${status} current main`, async () => {
    const f = fixture();
    f.comparison.status = status;
    f.comparison.merge_base_commit.sha = 'old-base';
    f.comparison.behind_by = 1;
    await merge(f.github, f.context, f.appId);
    assert.deepEqual(f.calls, []);
    assert.deepEqual(f.updates, [{owner: 'org', repo: 'crate', pull_number: 1, expected_head_sha: 'tested'}]);
  });
}

test('comparison must prove that the exact current main commit is an ancestor', async () => {
  const f = fixture();
  f.comparison.merge_base_commit.sha = 'old-base';
  await assert.rejects(merge(f.github, f.context, f.appId), /current default branch.*rebase.*retest/i);
  assert.deepEqual(f.calls, []);
});

test('main advancing during the ancestry check invalidates the green run', async () => {
  const f = fixture();
  let reads = 0;
  f.github.rest.repos.getBranch = async () => ({data: {commit: {sha: ++reads === 1 ? 'current-base' : 'new-base'}}});
  await merge(f.github, f.context, f.appId);
  assert.deepEqual(f.calls, []);
  assert.equal(f.updates.length, 1);
});

for (const operation of ['get', 'getBranch', 'compareCommitsWithBasehead']) {
  test(`${operation} failure cannot authorize a merge`, async () => {
    const f = fixture();
    f.github.rest.repos[operation] = async () => {throw new Error('API unavailable');};
    await assert.rejects(merge(f.github, f.context, f.appId), /API unavailable/);
    assert.deepEqual(f.calls, []);
  });
}

for (const scenario of ['writer-token', 'user-token', 'admin-write', 'extra-write',
                         'missing-checks', 'non-strict', 'empty-checks', 'role-bypass', 'hidden-policy', 'unknown-verdict', 'disabled-policy']) {
  test(`${scenario} cannot weaken server enforcement`, async () => {
    const f = fixture();
    if (scenario === 'writer-token') f.policy.current_user_can_bypass = 'always';
    if (scenario === 'user-token') f.viewer.login = 'operator';
    if (scenario === 'admin-write') f.app.permissions.administration = 'write';
    if (scenario === 'extra-write') f.app.permissions.actions = 'write';
    if (scenario === 'missing-checks') f.rules.length = 0;
    if (scenario === 'non-strict') f.rules[0].parameters.strict_required_status_checks_policy = false;
    if (scenario === 'empty-checks') f.rules[0].parameters.required_status_checks.length = 0;
    if (scenario === 'role-bypass') f.policy.current_user_can_bypass = 'pull_requests_only';
    if (scenario === 'hidden-policy') delete f.policy.current_user_can_bypass;
    if (scenario === 'unknown-verdict') f.policy.current_user_can_bypass = 'unknown';
    if (scenario === 'disabled-policy') f.policy.enforcement = 'disabled';
    await assert.rejects(merge(f.github, f.context, f.appId));
    assert.deepEqual(f.calls, []);
  });
}

test('a read-only App uses GitHub caller verdict while bypass actors are redacted', async () => {
  const f = fixture();
  assert.equal(f.policy.bypass_actors, undefined);
  assert.equal(f.policy.current_user_can_bypass, 'never');
  await merge(f.github, f.context, f.appId);
  assert.equal(f.calls.length, 1);
});

test('an empty actor list cannot substitute for a missing caller verdict', async () => {
  const f = fixture();
  f.policy.bypass_actors = [];
  delete f.policy.current_user_can_bypass;
  await assert.rejects(merge(f.github, f.context, f.appId));
  assert.deepEqual(f.calls, []);
});

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

test('stale CI refreshes the branch without issuing unsupported App commands', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.comparison.behind_by = 1;
  const comments = [];
  f.github.rest.issues = {createComment: async args => {
    comments.push(args);
    throw new Error('Sorry, only users with push access can use that command.');
  }};
  await merge(f.github, f.context, f.appId);
  assert.deepEqual(f.calls, []);
  assert.equal(f.updates.length, 1);
  assert.deepEqual(comments, []);
});

test('branch refreshing requires a new complete CI run before the refreshed head can merge', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.comparison.behind_by = 1;
  await merge(f.github, f.context, f.appId);
  assert.deepEqual(f.calls, []);
  assert.equal(f.updates.length, 1);

  f.pr.head.sha = 'refreshed';
  f.comparison.status = 'ahead';
  await merge(f.github, f.context, f.appId);
  assert.deepEqual(f.calls, [], 'old green CI cannot authorize the new head');

  f.run.head_sha = 'refreshed';
  await merge(f.github, f.context, f.appId);
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].sha, 'refreshed');
});

test('workflow dependency updates remain supported by the merge identity', async () => {
  const f = fixture();
  f.app.permissions.workflows = 'write';
  await merge(f.github, f.context, f.appId);
  assert.equal(f.calls.length, 1);
});

test('an identical or unproven ancestry cannot request a branch refresh', async () => {
  for (const status of ['identical', 'diverged']) {
    const f = fixture();
    f.comparison.status = status;
    await assert.rejects(merge(f.github, f.context, f.appId), /current default branch.*rebase.*retest/i);
    assert.deepEqual(f.calls, []);
    assert.deepEqual(f.updates, []);
  }
});

test('a failed branch refresh remains an error and cannot merge', async () => {
  const f = fixture();
  f.comparison.status = 'diverged';
  f.comparison.behind_by = 1;
  f.github.rest.pulls.updateBranch = async () => {throw new Error('merge conflict');};
  await assert.rejects(merge(f.github, f.context, f.appId), /merge conflict/);
  assert.deepEqual(f.calls, []);
});

test('a branch refresh must be explicitly accepted by GitHub', async () => {
  const f = fixture();
  f.comparison.status = 'behind';
  f.comparison.behind_by = 1;
  f.github.rest.pulls.updateBranch = async () => ({status: 200});
  await assert.rejects(merge(f.github, f.context, f.appId), /refresh.*accepted/i);
  assert.deepEqual(f.calls, []);
});

test('a writer with CI bypass cannot refresh a dependency branch', async () => {
  const f = fixture();
  f.comparison.status = 'behind';
  f.comparison.behind_by = 1;
  f.policy.current_user_can_bypass = 'always';
  await assert.rejects(merge(f.github, f.context, f.appId));
  assert.deepEqual(f.updates, []);
});

test('a server-side base race refreshes the branch instead of merging stale CI', async () => {
  const f = fixture();
  let reads = 0;
  f.github.rest.repos.getBranch = async () => ({data: {commit: {sha: ++reads < 3 ? 'current-base' : 'new-base'}}});
  f.github.rest.pulls.merge = async () => {throw Object.assign(new Error('base advanced'), {status: 405});};
  await merge(f.github, f.context, f.appId);
  assert.deepEqual(f.calls, []);
  assert.equal(f.updates.length, 1);
});

test('merge errors with an unchanged base are never hidden as a refresh', async () => {
  const f = fixture();
  f.github.rest.pulls.merge = async () => {throw Object.assign(new Error('head changed'), {status: 409});};
  await assert.rejects(merge(f.github, f.context, f.appId), /head changed/);
  assert.deepEqual(f.updates, []);
});

for (const branch of ['master', 'feat/shared-ui']) {
  test(`the repository default branch ${branch} governs selection and enforcement`, async () => {
    const f = fixture();
    const observed = [];
    f.pr.base.ref = branch;
    f.github.rest.repos.get = async () => ({data: {default_branch: branch}});
    f.github.rest.pulls.list = async args => {
      observed.push(args.base);
      return {data: [f.pr]};
    };
    f.github.rest.repos.getBranch = async args => {
      observed.push(args.branch);
      return {data: {commit: {sha: 'current-base'}}};
    };
    const request = f.github.request;
    f.github.request = async (route, args) => {
      if (route.endsWith('/{branch}')) observed.push(args.branch);
      return request(route, args);
    };
    await merge(f.github, f.context, f.appId);
    assert.equal(f.calls.length, 1);
    assert.ok(observed.length >= 4);
    assert.ok(observed.every(value => value === branch));
  });
}

test('a main PR cannot merge when main is not the repository default', async () => {
  const f = fixture();
  f.github.rest.repos.get = async () => ({data: {default_branch: 'master'}});
  await merge(f.github, f.context, f.appId);
  assert.deepEqual(f.calls, []);
  assert.deepEqual(f.updates, []);
});

for (const value of [undefined, '', null]) {
  test(`missing default-branch metadata fails closed: ${value}`, async () => {
    const f = fixture();
    f.github.rest.repos.get = async () => ({data: {default_branch: value}});
    await assert.rejects(merge(f.github, f.context, f.appId), /default branch/i);
    assert.deepEqual(f.calls, []);
    assert.deepEqual(f.updates, []);
  });
}
