const assert = require('node:assert/strict');
const test = require('node:test');

const { issueReferences, sectionContent, validatePullRequestBody } = require('./pr_policy.cjs');

const owner = 'CS778-S2-2026-AWS-Challenge';
const repo = 'scenario-08-northwind-fnol-agent';

test('accepts a Draft pull request with a valid issue reference', () => {
  const result = validatePullRequestBody({
    body: '## Linked issue\n\nRefs #192\n\n## Summary\n\nImplements the first bounded part; verification remains pending.',
    isDraft: true,
    owner,
    repo,
  });
  assert.deepEqual(result, { errors: [], references: [192] });
});

test('rejects an empty placeholder Draft pull request', () => {
  const result = validatePullRequestBody({
    body: '## Linked issue\n\nRefs #192\n\n## Summary\n\n<!-- pending -->',
    isDraft: true,
    owner,
    repo,
  });
  assert.ok(result.errors.some((error) => error.includes('Summary')));
});

test('accepts a complete ready-for-review pull request', () => {
  const body = `## Linked issue

Closes #192

## Summary

Adds repository guardrails.

## Acceptance evidence

- The policy tests pass.

## Local validation

- Command: \`./scripts/check.ps1 -SkipInstall\`
- Result: PASS

## Contract and data impact

- API contract: none.
- Persistence schema: none.
- Fixtures and tests: policy validator coverage added.
- Claimant and staff projections: none.

## Dependencies and risks

- Dependencies: none.
- Remaining risks: local hooks can be bypassed.
`;
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.deepEqual(result, { errors: [], references: [192] });
});

test('accepts a ready pull request without local evidence when a remote provider is active', () => {
  const body = `## Linked issue

Refs #192

## Summary

The remote quality profile supplies the merge gate.

## Acceptance evidence

- Remote checks are configured for this pull request.

## Local validation

- Remote provider: CircleCI

## Contract and data impact

- API contract: none.
- Persistence schema: none.
- Fixtures and tests: policy validator coverage added.
- Claimant and staff projections: none.

## Dependencies and risks

- Dependencies: none.
- Remaining risks: remote provider availability is part of the active profile.
`;
  const result = validatePullRequestBody({
    body,
    isDraft: false,
    owner,
    repo,
    requireLocalQualityEvidence: false,
  });
  assert.deepEqual(result, { errors: [], references: [192] });
});

test('rejects a ready pull request with empty template sections', () => {
  const body = `## Linked issue

Refs #192

## Summary

<!-- placeholder -->

## Acceptance evidence

-

## Local validation

- Command:
- Result:
`;
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('Summary')));
  assert.ok(result.errors.some((error) => error.includes('Acceptance evidence')));
  assert.ok(result.errors.some((error) => error.includes('Result: PASS')));
  assert.ok(result.errors.some((error) => error.includes('API contract:')));
  assert.ok(result.errors.some((error) => error.includes('Dependencies:')));
});

test('rejects labelled template fields without values', () => {
  const body = `## Linked issue

Refs #192

## Summary

Adds repository guardrails.

## Acceptance evidence

- Policy tests pass.

## Local validation

- Command: \`./scripts/check.ps1\`
- Result: PASS

## Contract and data impact

- API contract:
- Persistence schema: None
- Fixtures and tests: Updated
- Claimant and staff projections: None

## Dependencies and risks

- Dependencies: None
- Remaining risks:
`;
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('API contract:')));
  assert.ok(result.errors.some((error) => error.includes('Remaining risks:')));
});

test('accepts only short or same-repository issue references', () => {
  const content = `Refs #12
Fixes https://github.com/${owner}/${repo}/issues/13
Refs https://github.com/example/other/issues/14`;
  assert.deepEqual(issueReferences(content, owner, repo), [12, 13]);
});

test('extracts a section without comments', () => {
  const content = sectionContent('## Summary\n<!-- prompt -->\nActual result\n## Risks\nNone', 'Summary');
  assert.equal(content, 'Actual result');
});
