const assert = require('node:assert/strict');
const test = require('node:test');

const {
  changedPathOverlap,
  issueReferences,
  loginIsDeclared,
  run,
  sectionContent,
  validatePullRequestBody,
} = require('./pr_policy.cjs');

const owner = 'CS778-S2-2026-AWS-Challenge';
const repo = 'scenario-08-northwind-fnol-agent';

function readyBody({ localValidation = '- Command: `./scripts/check.ps1 -SkipInstall`\n- Result: PASS' } = {}) {
  return `## Linked issue

Closes #192

## Summary

Adds repository guardrails.

- Primary owner: @jxu316-arch
- Owned behavior: Repository policy validation.
- Non-goals: No product changes.
- Scope changed since issue: No

## Acceptance evidence

- The policy tests pass.

## Local validation

${localValidation}

## Contract and data impact

- API contract: None
- Persistence schema: None
- Fixtures and tests: Policy validator coverage added.
- Claimant and staff projections: None

## Ownership and overlap

- Expected impact area: Repository policy files.
- Cross-owner impact: None
- Overlapping issues or PRs: None
- Owner agreement: Not required

## Base and delivery topology

- Base reviewed against: origin/main
- Stacked parent: None
- Intended merge order: Independent
- Main changes affecting this PR: None

## Failure-path analysis

- Risk class: Standard
- Ownership or stale authority: Policy fixtures cover owner matching.
- Retry, concurrency, or duplicate delivery: None - pure validation.
- Partial side effect or unknown outcome: None - pure validation.
- Recovery or reconciliation: None - pure validation.
- Sensitive-data or model-output exposure: None - no sensitive data.

## Dependencies and risks

- Dependencies: None
- Remaining risks: Local hooks can be bypassed.

## Governance exception

- Protected actions: None
- Reason: Not required
- Operator: Not required
- Allowed PRs: None
- Window starts: Not required
- Window expires: Not required
- Restoration evidence: Not required

## Governance confirmation

- [x] I have read AGENT.md and the governance skill in full. Version read: v1.0

## Documentation sync check

- [x] This PR contains no changes that require documentation updates
- [ ] Updated docs/api.md (API contract changes)
- [ ] Updated docs/persistence-schema.md (persistence changes)
- [ ] Updated docs/README.md (documents added, replaced, moved, or archived)

## Impact statement

- [x] I confirmed the changes do not affect unrelated code; any impact is described in the Summary
`;
}

function pullRequest(body = readyBody()) {
  return {
    number: 341,
    body,
    draft: false,
    user: { login: 'jxu316-arch' },
    base: { ref: 'main', sha: 'base-sha' },
    head: { sha: 'head-sha' },
  };
}

function policyContext(pr = pullRequest()) {
  return {
    payload: { pull_request: pr },
    repo: { owner, repo },
  };
}

function fakeGithub({ issueAssignees = ['jxu316-arch'], openPulls = [], files = {}, baseFiles = [] } = {}) {
  const rest = {
    issues: {
      get: async () => ({
        data: {
          number: 192,
          body: `### Owner or responsible contributor\n@${issueAssignees[0] || 'unassigned'}`,
          assignees: issueAssignees.map((login) => ({ login })),
        },
      }),
    },
    pulls: {
      list: async () => ({ data: openPulls }),
      listFiles: async ({ pull_number: number }) => ({ data: files[number] || [] }),
    },
    repos: {
      compareCommitsWithBasehead: async () => ({ data: { files: baseFiles } }),
    },
  };
  return {
    rest,
    paginate: async (method, input) => (await method(input)).data,
  };
}

function fakeCore() {
  return {
    failures: [],
    warnings: [],
    info() {},
    setFailed(message) { this.failures.push(message); },
    warning(message) { this.warnings.push(message); },
  };
}

test('accepts a Draft pull request with a valid issue reference', () => {
  const result = validatePullRequestBody({
    body: '## Linked issue\n\nRefs #192\n\n## Summary\n\nImplements the first bounded part; verification remains pending.',
    isDraft: true,
    owner,
    repo,
  });
  assert.deepEqual(result, {
    errors: [],
    warnings: [
      'Complete `Primary owner:` in `Summary`.',
      'Complete `Owned behavior:` in `Summary`.',
      'Complete `Non-goals:` in `Summary`.',
      'Complete `Scope changed since issue:` in `Summary`.',
      'Check the box in `Governance confirmation` after reading AGENT.md and the governance skill in full.',
      'Check at least one box in `Documentation sync check`.',
      'Check the box in `Impact statement` after confirming unrelated code is unaffected.',
    ],
    references: [192],
  });
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
  const body = readyBody();
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.deepEqual(result, { errors: [], warnings: [], references: [192] });
});

test('accepts a ready pull request without local evidence when a remote provider is active', () => {
  const body = readyBody({ localValidation: '- Remote provider: CircleCI' });
  const result = validatePullRequestBody({
    body,
    isDraft: false,
    owner,
    repo,
    requireLocalQualityEvidence: false,
  });
  assert.deepEqual(result, { errors: [], warnings: [], references: [192] });
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

test('matches declared owners without matching a login prefix', () => {
  assert.equal(loginIsDeclared('Lead: @jxu316-arch; support: @bdfa123', 'bdfa123'), true);
  assert.equal(loginIsDeclared('@jxu316-archived', 'jxu316-arch'), false);
});

test('reports deterministic changed-file intersections', () => {
  assert.deepEqual(
    changedPathOverlap(['docs/api.md', 'backend/app.py', 'docs/api.md'], ['docs/api.md', 'README.md']),
    ['docs/api.md'],
  );
});

test('requires applicable evidence for a high-risk PR', () => {
  const body = readyBody()
    .replace('Risk class: Standard', 'Risk class: External side effect')
    .replace('Policy fixtures cover owner matching.', 'None')
    .replace('None - pure validation.', 'None')
    .replace('None - pure validation.', 'None')
    .replace('None - pure validation.', 'None')
    .replace('None - no sensitive data.', 'None');
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('high-risk PR')));
});

test('requires a bounded governance window for protected actions', () => {
  const body = readyBody()
    .replace('Protected actions: None', 'Protected actions: Temporarily bypass required checks')
    .replace('Reason: Not required', 'Reason: Restore the required quality provider without accepting unverified feature code.')
    .replace('Operator: Not required', 'Operator: @Ysoseri1224')
    .replace('Allowed PRs: None', 'Allowed PRs: #341')
    .replace('Window starts: Not required', 'Window starts: 2026-08-27T01:00:00Z')
    .replace('Window expires: Not required', 'Window expires: 2026-08-27T01:30:00Z')
    .replace('Restoration evidence: Not required', 'Restoration evidence: Re-read ruleset #20630713 and verify required checks.');
  assert.deepEqual(
    validatePullRequestBody({ body, isDraft: false, owner, repo }).errors,
    [],
  );
});

test('rejects an open-ended governance exception', () => {
  const body = readyBody().replace('Protected actions: None', 'Protected actions: Repository maintenance');
  const errors = validatePullRequestBody({ body, isDraft: false, owner, repo }).errors;
  assert.ok(errors.some((error) => error.includes('@operator')));
  assert.ok(errors.some((error) => error.includes('Reason')));
  assert.ok(errors.some((error) => error.includes('#PR')));
  assert.ok(errors.some((error) => error.includes('restoration evidence')));
});

test('rejects a Ready PR whose author does not own the primary issue', async () => {
  const core = fakeCore();
  const result = await run({
    github: fakeGithub({ issueAssignees: ['bdfa123'] }),
    context: policyContext(),
    core,
  });
  assert.ok(result.errors.some((error) => error.includes('is not a declared owner')));
  assert.equal(core.failures.length, 1);
});

test('reports undeclared changed-file overlap as advisory only', async () => {
  const core = fakeCore();
  const result = await run({
    github: fakeGithub({
      openPulls: [
        { number: 341, user: { login: 'jxu316-arch' } },
        { number: 350, user: { login: 'bdfa123' } },
      ],
      files: {
        341: [{ filename: 'docs/api.md' }],
        350: [{ filename: 'docs/api.md' }],
      },
    }),
    context: policyContext(),
    core,
  });
  assert.deepEqual(result.errors, []);
  assert.ok(result.warnings.some((warning) => warning.includes('#350 (docs/api.md)')));
});

test('accepts declared overlap for independent human review', async () => {
  const core = fakeCore();
  const body = readyBody().replace(
    'Overlapping issues or PRs: None',
    'Overlapping issues or PRs: #350 shares docs/api.md; this PR owns policy wording only.',
  ).replace(
    'Owner agreement: Not required',
    'Owner agreement: @bdfa123 confirmed the documented split on #350.',
  );
  const result = await run({
    github: fakeGithub({
      openPulls: [
        { number: 341, user: { login: 'jxu316-arch' } },
        { number: 350, user: { login: 'bdfa123' } },
      ],
      files: {
        341: [{ filename: 'docs/api.md' }],
        350: [{ filename: 'docs/api.md' }],
      },
    }),
    context: policyContext(pullRequest(body)),
    core,
  });
  assert.deepEqual(result.errors, []);
});

test('does not turn cross-author path overlap into an ownership blocker', async () => {
  const core = fakeCore();
  const body = readyBody().replace(
    'Overlapping issues or PRs: None',
    'Overlapping issues or PRs: #350 shares docs/api.md.',
  ).replace('Owner agreement: Not required', 'Owner agreement: Pending');
  const result = await run({
    github: fakeGithub({
      openPulls: [
        { number: 341, user: { login: 'jxu316-arch' } },
        { number: 350, user: { login: 'bdfa123' } },
      ],
      files: {
        341: [{ filename: 'docs/api.md' }],
        350: [{ filename: 'docs/api.md' }],
      },
    }),
    context: policyContext(pullRequest(body)),
    core,
  });
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.warnings, []);
});

test('rejects an undeclared stacked base', async () => {
  const core = fakeCore();
  const pr = pullRequest();
  pr.base = { ref: 'feature/parent', sha: 'parent-sha' };
  const result = await run({ github: fakeGithub(), context: policyContext(pr), core });
  assert.ok(result.errors.some((error) => error.includes('stacked parent')));
});

test('rejects unresolved main movement on a path changed by the PR', async () => {
  const core = fakeCore();
  const result = await run({
    github: fakeGithub({
      files: { 341: [{ filename: 'docs/repo_rule.md' }] },
      baseFiles: [{ filename: 'docs/repo_rule.md' }],
    }),
    context: policyContext(),
    core,
  });
  assert.ok(result.errors.some((error) => error.includes('Main changed paths')));
});

test('rejects a ready pull request whose governance confirmation box is unchecked', () => {
  const body = readyBody().replace(
    '- [x] I have read AGENT.md and the governance skill in full. Version read: v1.0',
    '- [ ] I have read AGENT.md and the governance skill in full. Version read: v1.0',
  );
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('Governance confirmation')));
});

test('rejects a ready pull request that omits the governance skill version read', () => {
  const body = readyBody().replace(' Version read: v1.0', '');
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('version read (vX.Y)')));
});

test('rejects a ready pull request with no documentation sync box checked', () => {
  const body = readyBody().replace(
    '- [x] This PR contains no changes that require documentation updates',
    '- [ ] This PR contains no changes that require documentation updates',
  );
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('Documentation sync check')));
});

test('rejects a ready pull request whose impact statement box is unchecked', () => {
  const body = readyBody().replace(
    '- [x] I confirmed the changes do not affect unrelated code; any impact is described in the Summary',
    '- [ ] I confirmed the changes do not affect unrelated code; any impact is described in the Summary',
  );
  const result = validatePullRequestBody({ body, isDraft: false, owner, repo });
  assert.ok(result.errors.some((error) => error.includes('Impact statement')));
});

test('downgrades missing governance sections to warnings on a Draft pull request', () => {
  const result = validatePullRequestBody({
    body: '## Linked issue\n\nRefs #192\n\n## Summary\n\nImplements the first bounded part; verification remains pending.',
    isDraft: true,
    owner,
    repo,
  });
  assert.equal(result.errors.length, 0);
  assert.ok(result.warnings.some((warning) => warning.includes('Governance confirmation')));
  assert.ok(result.warnings.some((warning) => warning.includes('Documentation sync check')));
  assert.ok(result.warnings.some((warning) => warning.includes('Impact statement')));
});
