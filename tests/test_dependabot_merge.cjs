const {test} = require('node:test');
const assert = require('node:assert/strict');
const merge = require('../.github/actions/merge-tested-dependabot/merge.cjs');

function fixture() {
  const calls = [];
  const run = {event: 'pull_request', conclusion: 'success', head_sha: 'tested', head_branch: 'dependabot/cargo/serde', head_repository: {full_name: 'org/crate'}};
  const pr = {number: 1, title: 'build(deps): update serde', body: 'Dependency update.', user: {login: 'dependabot[bot]'}, head: {sha: 'tested', repo: {full_name: 'org/crate'}}, base: {ref: 'main'}};
  const github = {rest: {
    pulls: {list: async () => ({data: [pr]}), merge: async args => {calls.push(args); return {data: {merged: true}};}},
    actions: {createWorkflowDispatch: async args => calls.push(args)},
  }};
  return {calls, run, pr, github, context: {repo: {owner: 'org', repo: 'crate'}, payload: {workflow_run: run}}};
}

test('successful CI merges only its tested head; the writer merge itself starts main CI', async () => {
  const f = fixture();
  await merge(f.github, f.context);
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
    await assert.rejects(merge(f.github, f.context), /Conventional Commit/);
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
    await merge(f.github, f.context);
    assert.deepEqual(f.calls, []);
  });
}

test('merge refusal cannot dispatch publication', async () => {
  const f = fixture();
  f.github.rest.pulls.merge = async () => ({data: {merged: false}});
  await assert.rejects(merge(f.github, f.context));
  assert.deepEqual(f.calls, []);
});
