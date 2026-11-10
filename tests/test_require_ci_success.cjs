const {test} = require('node:test');
const assert = require('node:assert/strict');
const verify = require('../.github/actions/require-ci-success/verify.cjs');

for (const results of [
  {test: {result: 'success'}},
  {test: {result: 'success'}, publish: {result: 'skipped'}},
]) {
  test('all applicable CI jobs pass', () => verify(JSON.stringify(results)));
}

for (const result of ['failure', 'cancelled', 'pending', 'unknown']) {
  test(result + ' cannot authorize a merge', () => {
    assert.throws(() => verify(JSON.stringify({
      lint: {result: 'success'}, test: {result},
    })), /CI job test did not pass/);
  });
}

for (const results of [{}, {test: {result: 'skipped'}}]) {
  test('an empty or wholly skipped graph cannot pass', () => {
    assert.throws(() => verify(JSON.stringify(results)), /No CI validation job succeeded/);
  });
}

for (const results of [null, [], true, 7, {test: null}, {test: {}}]) {
  test('invalid CI result shape fails closed: ' + JSON.stringify(results), () => {
    assert.throws(() => verify(JSON.stringify(results)), /CI/);
  });
}

test('missing input fails without inventing success', () => {
  assert.throws(() => verify(undefined), /required/);
});

test('invalid JSON is rejected without echoing input contents', () => {
  assert.throws(() => verify('private-invalid-value'), error =>
    /valid JSON/.test(error.message) && !error.message.includes('private-invalid-value'));
});
