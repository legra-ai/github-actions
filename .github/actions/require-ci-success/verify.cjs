function verify(input) {
  if (!input) throw new Error('CI results input is required');
  let results;
  try { results = JSON.parse(input); }
  catch { throw new Error('CI results must be valid JSON'); }
  if (!results || typeof results !== 'object' || Array.isArray(results)) {
    throw new Error('CI results must be a job map');
  }
  let succeeded = false;
  // bounded: the finite workflow needs map is limited by the Action input environment.
  for (const [job, value] of Object.entries(results)) {
    if (!value || !['success', 'skipped'].includes(value.result)) {
      throw new Error(`CI job ${job} did not pass`);
    }
    succeeded ||= value.result === 'success';
  }
  if (!succeeded) throw new Error('No CI validation job succeeded');
}
module.exports = verify;
if (require.main === module) verify(process.env.INPUT_RESULTS);
