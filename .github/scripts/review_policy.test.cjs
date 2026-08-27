const assert = require('node:assert/strict');
const test = require('node:test');

const { validateReview } = require('./review_policy.cjs');

const pullRequest = { head: { sha: 'abcdef1234567890' } };

test('accepts a structured Changes Requested review on the current head', () => {
  const review = {
    state: 'changes_requested',
    commit_id: 'abcdef1234567890',
    body: `Exact head: abcdef1
Authority: docs/api.md
Observed behavior: The route returns internal notes.
Expected behavior: The claimant projection excludes internal notes.
Impact: Claimants can receive staff-only data.
Why this blocks current acceptance: The current issue changes this claimant response.
Risk family: Visibility boundary`,
  };
  assert.deepEqual(validateReview({ review, pullRequest }), { errors: [] });
});

test('rejects a stale or unexplained Changes Requested review', () => {
  const result = validateReview({
    review: { state: 'changes_requested', commit_id: 'old-head', body: 'Impact: Unclear' },
    pullRequest,
  });
  assert.ok(result.errors.some((error) => error.includes('current PR head')));
  assert.ok(result.errors.some((error) => error.includes('Authority')));
  assert.ok(result.errors.some((error) => error.includes('Risk family')));
});

test('does not impose blocker fields on comments or approvals', () => {
  assert.deepEqual(
    validateReview({ review: { state: 'approved', body: '' }, pullRequest }),
    { errors: [] },
  );
});
