// Called only by a trusted workflow_run handler; never checks out PR code.
const validateTitle = require('../conventional-commit/validate.cjs');
module.exports = async function mergeTestedDependabot(github, context, appId) {
  const run = context.payload.workflow_run;
  const {owner, repo} = context.repo;
  const repository = `${owner}/${repo}`;
  if (run.event !== 'pull_request' || run.conclusion !== 'success' ||
      run.head_repository?.full_name !== repository) return;

  const {data: metadata} = await github.rest.repos.get({owner, repo});
  const branch = metadata?.default_branch;
  if (typeof branch !== 'string' || !branch) {
    throw new Error('Repository default branch metadata is required');
  }

  const {data: pulls} = await github.rest.pulls.list({
    owner, repo, state: 'open', base: branch, head: `${owner}:${run.head_branch}`,
  });
  for (const pr of pulls) {
    if (pr.user.login !== 'dependabot[bot]' || pr.base.ref !== branch ||
        pr.head.repo?.full_name !== repository || pr.head.sha !== run.head_sha) continue;
    const title = validateTitle(pr.title);
    await requireStrictMergeIdentity(github, owner, repo, appId, branch);
    const {data: base} = await github.rest.repos.getBranch({owner, repo, branch});
    const baseSha = base.commit.sha;
    const {data: comparison} = await github.rest.repos.compareCommitsWithBasehead({
      owner, repo, basehead: `${baseSha}...${run.head_sha}`, per_page: 1,
    });
    if (comparison.status !== 'ahead' || comparison.merge_base_commit?.sha !== baseSha) {
      if (['behind', 'diverged'].includes(comparison.status) &&
          Number.isSafeInteger(comparison.behind_by) && comparison.behind_by > 0) {
        await refreshBranch(github, owner, repo, pr.number, run.head_sha);
        return;
      }
      throw new Error(`PR ${pr.number} does not include current default branch; rebase and retest`);
    }
    const {data: latest} = await github.rest.repos.getBranch({owner, repo, branch});
    if (latest.commit.sha !== baseSha) {
      await refreshBranch(github, owner, repo, pr.number, run.head_sha);
      return;
    }
    // The identity cannot bypass strict checks. GitHub therefore rejects a
    // base advance after this check atomically when processing the merge.

    let result;
    try {
      ({data: result} = await github.rest.pulls.merge({
        owner, repo, pull_number: pr.number, sha: run.head_sha, merge_method: 'squash',
        commit_title: `${title} (#${pr.number})`, commit_message: pr.body || '',
      }));
    } catch (error) {
      if (![405, 409].includes(error.status)) throw error;
      const {data: current} = await github.rest.repos.getBranch({owner, repo, branch});
      if (current.commit.sha === baseSha) throw error;
      await refreshBranch(github, owner, repo, pr.number, run.head_sha);
      return;
    }
    if (!result.merged) throw new Error(`Merge refused for PR ${pr.number}`);
    // The writer token is an installed App, so this merge starts the push
    // pipeline on main by itself; no explicit dispatch is needed.
  }
};

async function refreshBranch(github, owner, repo, number, sha) {
  const response = await github.rest.pulls.updateBranch({
    owner, repo, pull_number: number, expected_head_sha: sha,
  });
  if (response.status !== 202) {
    throw new Error(`Branch refresh for PR ${number} was not accepted by GitHub`);
  }
  // An App update triggers a new pull_request CI run. This invocation never
  // merges the refreshed head using the earlier green result.
  console.log(`PR ${number} refreshed; waiting for CI on its new head`);
}

async function requireStrictMergeIdentity(github, owner, repo, appId, branch) {
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
    owner, repo, branch, per_page: 100,
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
      return;
    }
  }
  throw new Error('Merge App bypasses strict checks or main lacks a strict checks ruleset');
}

