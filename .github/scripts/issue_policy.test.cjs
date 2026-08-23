const assert = require('node:assert/strict');
const test = require('node:test');

const { fieldContent, validateIssueBody } = require('./issue_policy.cjs');

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

test('extracts a field without HTML comments', () => {
  assert.equal(fieldContent('### Deliverable\n<!-- prompt -->\nAdd a test\n### Dependencies\nNone', 'Deliverable'), 'Add a test');
});
