const assert = require('node:assert/strict');
const test = require('node:test');

const { fieldContent, validateDiscussionApproval, validateIssueBody } = require('./issue_policy.cjs');

const validBody = `### Issue type
Regression validation

### Problem or reason
The integrated fallback path lacks one regression test.

### Deliverable
Add a focused API test.

### Acceptance criteria
- [ ] The fallback response is asserted.

### Related issue or PR
Refs #134

### Dependencies
None

### Owned behavior
Fallback response regression evidence.

### Expected impact area
Backend API tests.

### Non-goals
No route or UI changes.

### Shared contracts
None

### Risk class
Standard

### Owner or responsible contributor
@jxu316-arch`;

test('accepts a complete structured code issue', () => {
  const result = validateIssueBody({ body: validBody });
  assert.deepEqual(result.errors, []);
  assert.equal(result.fields['Issue type'], 'Regression validation');
});

test('accepts standalone work with no related issue or dependency', () => {
  const body = validBody
    .replace('Refs #134', 'None')
    .replace('Regression validation', 'Maintenance or documentation');
  assert.deepEqual(validateIssueBody({ body }).errors, []);
});

test('accepts full repository issue and pull request URLs', () => {
  const body = validBody
    .replace('Refs #134', 'https://github.com/example/repository/issues/134')
    .replace('None\n\n### Owner', 'https://github.com/example/repository/pull/120\n\n### Owner');
  assert.deepEqual(validateIssueBody({ body }).errors, []);
});

test('accepts a contract document as a dependency', () => {
  const body = validBody.replace('### Dependencies\nNone', '### Dependencies\n`docs/api.md` response contract');
  assert.deepEqual(validateIssueBody({ body }).errors, []);
});

test('rejects missing fields and placeholders', () => {
  const result = validateIssueBody({
    body: `### Issue type
Feature

### Problem or reason
...

### Deliverable

### Acceptance criteria
-

### Related issue or PR
maybe related

### Dependencies
waiting

### Owner or responsible contributor
`,
  });
  assert.ok(result.errors.some((error) => error.includes('Problem or reason')));
  assert.ok(result.errors.some((error) => error.includes('Deliverable')));
  assert.ok(result.errors.some((error) => error.includes('Owner or responsible contributor')));
  assert.ok(result.errors.some((error) => error.includes('Related issue or PR')));
});

test('rejects an unsupported issue type', () => {
  const result = validateIssueBody({ body: validBody.replace('Regression validation', 'Question') });
  assert.ok(result.errors.some((error) => error.includes('Choose one of')));
});

test('rejects missing ownership boundaries and an unsupported risk class', () => {
  const body = validBody
    .replace('Fallback response regression evidence.', '')
    .replace('Standard\n\n### Owner', 'Unbounded\n\n### Owner');
  const errors = validateIssueBody({ body }).errors;
  assert.ok(errors.some((error) => error.includes('Owned behavior')));
  assert.ok(errors.some((error) => error.includes('risk class')));
});

test('extracts a field without HTML comments', () => {
  assert.equal(fieldContent('### Deliverable\n<!-- prompt -->\nAdd a test\n### Dependencies\nNone', 'Deliverable'), 'Add a test');
});

test('skips discussion approval for issues created by the maintainer', () => {
  const result = validateDiscussionApproval({
    body: validBody,
    creator: 'Ysoseri1224',
    maintainer: 'Ysoseri1224',
  });
  assert.deepEqual(result.errors, []);
});

test('rejects a non-maintainer issue without a discussion approval link', () => {
  const result = validateDiscussionApproval({
    body: validBody,
    creator: 'someone-else',
    maintainer: 'Ysoseri1224',
  });
  assert.equal(result.errors.length, 1);
  assert.ok(result.errors[0].includes('Discussion approval'));
});

test('accepts a non-maintainer issue with an approved discussion thread URL', () => {
  const body = `${validBody}\n### Discussion approval\nhttps://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/discussions/12\n`;
  const result = validateDiscussionApproval({
    body,
    creator: 'someone-else',
    maintainer: 'Ysoseri1224',
  });
  assert.deepEqual(result.errors, []);
});

test('rejects a non-maintainer discussion approval field without a thread URL', () => {
  const body = `${validBody}\n### Discussion approval\nNone - I prefer not to ask.\n`;
  const result = validateDiscussionApproval({
    body,
    creator: 'someone-else',
    maintainer: 'Ysoseri1224',
  });
  assert.equal(result.errors.length, 1);
});
