const assert = require('node:assert/strict');
const test = require('node:test');

const { validateCommits } = require('./commit_policy.cjs');

const commit = (message, parentCount = 1) => ({ sha: 'abcdef1234', message, parentCount });

test('conventional first lines pass and merge commits are exempt', () => {
  const result = validateCommits({
    commits: [
      commit('ci: plan CircleCI jobs before they start'),
      commit('fix(backend): wake the fixture realtime watcher on stop'),
      commit('Merge branch main into feature', 2),
    ],
    body: 'Breaking change: None',
  });
  assert.deepEqual(result.errors, []);
});

test('a non-conventional first line is reported with its short sha', () => {
  const result = validateCommits({ commits: [commit('Update stuff')], body: '' });
  assert.equal(result.errors.length, 1);
  assert.match(result.errors[0], /abcdef1 "Update stuff"/);
});

test('an unknown scope is rejected', () => {
  assert.equal(validateCommits({ commits: [commit('feat(ui): x')], body: '' }).errors.length, 1);
});

test('breaking commits need a declaration and a declaration needs a breaking commit', () => {
  const breaking = [commit('feat(api)!: drop the legacy route')];
  assert.equal(validateCommits({ commits: breaking, body: '' }).errors.length, 1);
  assert.deepEqual(validateCommits({ commits: breaking, body: '## Breaking change\n\nRoute removed.' }).errors, []);
  assert.deepEqual(
    validateCommits({ commits: [commit('feat: x\n\nBREAKING CHANGE: y')], body: 'Breaking change: route removed' }).errors,
    [],
  );
  assert.equal(validateCommits({ commits: [commit('feat: x')], body: 'Breaking change: yes' }).errors.length, 1);
});
