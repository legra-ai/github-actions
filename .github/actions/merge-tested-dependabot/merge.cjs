// Called only by a trusted workflow_run handler; never checks out PR code.
const validateTitle = require('../conventional-commit/validate.cjs');
module.exports = async function mergeTestedDependabot(github, context) {
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
    const {data: result} = await github.rest.pulls.merge({
      owner, repo, pull_number: pr.number, sha: run.head_sha, merge_method: 'squash',
      commit_title: `${title} (#${pr.number})`, commit_message: pr.body || '',
    });
    if (!result.merged) throw new Error(`Merge refused for PR ${pr.number}`);
    // The writer token is an installed App, so this merge starts the push
    // pipeline on main by itself; no explicit dispatch is needed.
  }
};
