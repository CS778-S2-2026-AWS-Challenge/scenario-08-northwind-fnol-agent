const assert = require('node:assert/strict');
const test = require('node:test');

const { auditPullRequestEvent, windowMatches } = require('./governance_audit.cjs');

function body(actions = 'None') {
  return `## Governance exception

- Protected actions: ${actions}
- Reason: Restore the required quality provider while preserving an exact exception record.
- Operator: @Ysoseri1224
- Allowed PRs: #341, #342
- Window starts: 2026-08-27T01:00:00Z
- Window expires: 2026-08-27T02:00:00Z
- Restoration evidence: Verify ruleset 20630713 is active and required checks are restored.`;
}

test('matches an exact governance operator, PR, action, and time window', () => {
  const result = windowMatches({
    body: body('Temporarily disable ruleset, merge, and restore ruleset'),
    pullNumber: 341,
    actor: 'Ysoseri1224',
    operation: 'merge',
    occurredAt: '2026-08-27T01:30:00Z',
  });
  assert.equal(result.matches, true);
});

test('does not treat a broad or expired record as a governance window', () => {
  const result = windowMatches({
    body: body('Repository maintenance'),
    pullNumber: 341,
    actor: 'Ysoseri1224',
    operation: 'merge',
    occurredAt: '2026-08-27T03:00:00Z',
  });
  assert.equal(result.matches, false);
  assert.ok(result.reasons.some((reason) => reason.includes('does not allow merge')));
  assert.ok(result.reasons.some((reason) => reason.includes('outside')));
});

test('classifies an authorised governance self-merge separately', () => {
  const result = auditPullRequestEvent({
    action: 'closed',
    pullRequest: {
      number: 341,
      merged: true,
      user: { login: 'Ysoseri1224' },
      body: body('Temporarily disable ruleset, merge, and restore ruleset'),
    },
    actor: 'Ysoseri1224',
    occurredAt: '2026-08-27T01:30:00Z',
  });
  assert.equal(result.classification, 'governance_window_merge');
  assert.equal(result.incident, false);
});

test('flags an ordinary self-merge without claiming who controlled the account', () => {
  const result = auditPullRequestEvent({
    action: 'closed',
    pullRequest: { number: 341, merged: true, user: { login: 'jxu316-arch' }, body: body() },
    actor: 'jxu316-arch',
    occurredAt: '2026-08-27T01:30:00Z',
  });
  assert.equal(result.classification, 'self_merge_without_matching_governance_window');
  assert.equal(result.incident, true);
});

test('records Draft and Ready actors without inferring authorisation', () => {
  const result = auditPullRequestEvent({
    action: 'ready_for_review',
    pullRequest: { number: 341, merged: false, user: { login: 'jxu316-arch' }, body: '' },
    actor: 'jxu316-arch',
    occurredAt: '2026-08-27T01:30:00Z',
  });
  assert.equal(result.classification, 'protected_pr_state_observed:ready_for_review');
  assert.equal(result.incident, false);
});

test('flags a non-fast-forward PR branch update', () => {
  const result = auditPullRequestEvent({
    action: 'synchronize',
    pullRequest: { number: 341, merged: false, user: { login: 'jxu316-arch' }, body: '' },
    actor: 'jxu316-arch',
    occurredAt: '2026-08-27T01:30:00Z',
    nonFastForward: true,
  });
  assert.equal(result.classification, 'non_fast_forward_pr_update');
  assert.equal(result.incident, true);
});
