// Called only by a trusted workflow_run handler; never checks out PR code.
const validateTitle = require('../conventional-commit/validate.cjs');
module.exports = async function mergeTestedDependabot(github, context, appId) {
  const run = context.payload.workflow_run;
  const {owner, repo} = context.repo;
  const repository = `${owner}/${repo}`;
  if (run.event !== 'pull_request' || run.conclusion !== 'success' ||
      run.head_repository?.full_name !== repository) return;

  const {data: pulls} = await github.rest.pulls.list({
    owner, repo, state: 'open', base: 'main', head: `${owner}:${run.head_branch}`,
  });
  for (const pr of pulls) {
    if (pr.user.login !== 'dependabot[bot]' || pr.base.ref !== 'main' ||
        pr.head.repo?.full_name !== repository || pr.head.sha !== run.head_sha) continue;
    const title = validateTitle(pr.title);
    const actor = await requireStrictMergeIdentity(github, owner, repo, appId);
    const {data: base} = await github.rest.repos.getBranch({owner, repo, branch: 'main'});
    const baseSha = base.commit.sha;
    const {data: comparison} = await github.rest.repos.compareCommitsWithBasehead({
      owner, repo, basehead: `${baseSha}...${run.head_sha}`, per_page: 1,
    });
    if (comparison.status !== 'ahead' || comparison.merge_base_commit?.sha !== baseSha) {
      await requestSignedRebase(github, owner, repo, pr, baseSha, actor);
      throw new Error(`PR ${pr.number} does not include current main; rebase and retest`);
    }
    const {data: latest} = await github.rest.repos.getBranch({owner, repo, branch: 'main'});
    if (latest.commit.sha !== baseSha) {
      await requestSignedRebase(github, owner, repo, pr, latest.commit.sha, actor);
      throw new Error(`main advanced for PR ${pr.number}; rebase and retest`);
    }
    // The identity cannot bypass strict checks. GitHub therefore rejects a
    // base advance after this check atomically when processing the merge.

    const {data: result} = await github.rest.pulls.merge({
      owner, repo, pull_number: pr.number, sha: run.head_sha, merge_method: 'squash',
      commit_title: `${title} (#${pr.number})`, commit_message: pr.body || '',
    });
    if (!result.merged) throw new Error(`Merge refused for PR ${pr.number}`);
    // The writer token is an installed App, so this merge starts the push
    // pipeline on main by itself; no explicit dispatch is needed.
  }
};

async function requireStrictMergeIdentity(github, owner, repo, appId) {
  if (!Number.isSafeInteger(appId) || appId <= 0) {
    throw new Error('A dedicated merge App ID is required');
  }
  const {viewer} = await github.graphql('query { viewer { login } }');
  if (!viewer.login.endsWith('[bot]')) throw new Error('Merge token must belong to a GitHub App');
  const {data: app} = await github.rest.apps.getBySlug({app_slug: viewer.login.slice(0, -5)});
  if (app.id !== appId) throw new Error('Merge token identity does not match the configured App ID');
  const writes = Object.entries(app.permissions).filter(([, level]) => level === 'write');
  if (writes.some(([permission]) => !['contents', 'pull_requests', 'workflows'].includes(permission)) ||
      app.permissions.administration !== 'read') {
    throw new Error('Merge App requires administration read and only contents/pull_requests/workflows write');
  }
  const {data: rules} = await github.request('GET /repos/{owner}/{repo}/rules/branches/{branch}', {
    owner, repo, branch: 'main', per_page: 100,
  });
  // bounded: one API page contains at most 100 effective branch rules.
  for (const rule of rules) {
    if (rule.type !== 'required_status_checks' ||
        !rule.parameters.strict_required_status_checks_policy ||
        !rule.parameters.required_status_checks.length) continue;
    const {data: policy} = await github.request('GET /repos/{owner}/{repo}/rulesets/{ruleset_id}', {
      owner, repo, ruleset_id: rule.ruleset_id,
    });
    // GitHub redacts actor lists without ruleset write access. Its caller
    // verdict includes every bypass principal without granting this App admin.
    if (policy.enforcement === 'active' && policy.current_user_can_bypass === 'never') {
      return viewer.login;
    }
  }
  throw new Error('Merge App bypasses strict checks or main lacks a strict checks ruleset');
}

async function requestSignedRebase(github, owner, repo, pr, baseSha, actor) {
  const marker = `<!-- legra-rebase:${pr.head.sha}:${baseSha} -->`;
  // bounded: stream at most 100 comments per API page; never hydrate the thread.
  for await (const page of github.paginate.iterator(github.rest.issues.listComments, {
    owner, repo, issue_number: pr.number, per_page: 100,
  })) {
    if (page.data.some(comment => comment.user?.login === actor && comment.body?.includes(marker))) return;
  }
  await github.rest.issues.createComment({
    owner, repo, issue_number: pr.number,
    body: `@dependabot rebase\n\nThe tested head does not include current main. ` +
      `Dependabot must rebase and pass complete CI again before merging.\n\n${marker}`,
  });
}
