const REQUIRED_FIELDS = [
  'Issue type',
  'Problem or reason',
  'Deliverable',
  'Acceptance criteria',
  'Related issue or PR',
  'Dependencies',
  'Owned behavior',
  'Expected impact area',
  'Non-goals',
  'Shared contracts',
  'Risk class',
  'Owner or responsible contributor',
];

const ISSUE_TYPES = new Set([
  'Feature',
  'Bug',
  'Regression validation',
  'Integration gap',
  'Security concern',
  'Maintenance or documentation',
]);

const RISK_CLASSES = new Set([
  'Standard',
  'Shared contract',
  'Persistence or concurrency',
  'External side effect',
  'Identity, authority, security, or privacy',
  'Repository governance or deployment',
]);

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function fieldContent(body, label) {
  const escapedLabel = escapeRegExp(label);
  const match = body.match(
    new RegExp(
      `^###\\s+${escapedLabel}\\s*\\r?\\n([\\s\\S]*?)(?=^###\\s+|^##\\s+|(?![\\s\\S]))`,
      'im',
    ),
  );
  if (!match) return null;
  return match[1].replace(/<!--[\s\S]*?-->/g, '').trim();
}

function hasMeaningfulContent(value) {
  if (!value) return false;
  const withoutChecklist = value.replace(/[-*]\s*\[[ xX]\]/g, '').trim();
  return /[A-Za-z0-9]/.test(withoutChecklist) && !/^\.\.\.$/.test(withoutChecklist);
}

function isNone(value) {
  return /^none(?:\s*[-–:].*)?$/i.test(value.trim());
}

function hasRepositoryReference(value) {
  return /(?:^|\s)#\d+\b/.test(value) ||
    /https:\/\/github\.com\/[^\s/]+\/[^\s/]+\/(?:issues|pull)\/\d+\b/i.test(value);
}

function validateIssueBody({ body }) {
  const errors = [];
  const fields = Object.fromEntries(REQUIRED_FIELDS.map((label) => [label, fieldContent(body || '', label)]));

  for (const label of REQUIRED_FIELDS) {
    if (!hasMeaningfulContent(fields[label])) {
      errors.push(`Complete the \`### ${label}\` field.`);
    }
  }

  if (hasMeaningfulContent(fields['Issue type']) && !ISSUE_TYPES.has(fields['Issue type'])) {
    errors.push(`Choose one of: ${[...ISSUE_TYPES].join(', ')}.`);
  }

  if (hasMeaningfulContent(fields['Risk class']) && !RISK_CLASSES.has(fields['Risk class'])) {
    errors.push(`Choose one risk class: ${[...RISK_CLASSES].join(', ')}.`);
  }

  if (hasMeaningfulContent(fields['Related issue or PR']) &&
      !isNone(fields['Related issue or PR']) &&
      !hasRepositoryReference(fields['Related issue or PR'])) {
    errors.push('Related issue or PR must contain a repository reference or state None.');
  }

  return { errors, fields };
}

function validateDiscussionApproval({ body, creator, maintainer }) {
  const errors = [];
  if (!maintainer || (creator || '').toLowerCase() === maintainer.toLowerCase()) {
    return { errors };
  }
  const approval = fieldContent(body || '', 'Discussion approval');
  const threadUrl = /https:\/\/github\.com\/[^\s/]+\/[^\s/]+\/discussions\/\d+\b/i;
  if (!approval || !threadUrl.test(approval)) {
    errors.push(
      'Issues created by contributors other than the maintainer require prior approval: ' +
        'post in the `Issue requests` Discussions category, wait for the maintainer\'s ' +
        'explicit approval reply, and record the thread URL in `### Discussion approval`.',
    );
  }
  return { errors };
}

module.exports = {
  fieldContent,
  validateDiscussionApproval,
  validateIssueBody,
};
