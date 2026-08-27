const REQUIRED_CHANGE_REQUEST_FIELDS = [
  'Exact head',
  'Authority',
  'Observed behavior',
  'Expected behavior',
  'Impact',
  'Why this blocks current acceptance',
  'Risk family',
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function labelledValue(body, label) {
  const match = (body || '').match(
    new RegExp(`^[ \\t]*[-*]?[ \\t]*${escapeRegExp(label)}:[ \\t]*([^\\r\\n]+?)[ \\t]*$`, 'im'),
  );
  return match && /[A-Za-z0-9]/.test(match[1]) ? match[1].trim() : null;
}

function validateReview({ review, pullRequest }) {
  if ((review.state || '').toLowerCase() !== 'changes_requested') return { errors: [] };

  const errors = [];
  for (const label of REQUIRED_CHANGE_REQUEST_FIELDS) {
    if (!labelledValue(review.body || '', label)) {
      errors.push(`Complete \`${label}:\` for Changes Requested.`);
    }
  }

  if (!review.commit_id || review.commit_id !== pullRequest.head.sha) {
    errors.push(`Changes Requested must target the current PR head ${pullRequest.head.sha}.`);
  }
  const declaredHead = labelledValue(review.body || '', 'Exact head');
  if (declaredHead && !pullRequest.head.sha.startsWith(declaredHead) && !declaredHead.startsWith(pullRequest.head.sha)) {
    errors.push('`Exact head` does not match the current PR head.');
  }

  return { errors };
}

async function run({ context, core }) {
  const result = validateReview({
    review: context.payload.review,
    pullRequest: context.payload.pull_request,
  });
  if (result.errors.length > 0) {
    core.setFailed(`Review policy failed:\n- ${result.errors.join('\n- ')}`);
    return;
  }
  core.info('Review policy passed. Advisory comments and approvals do not require blocker fields.');
}

module.exports = {
  labelledValue,
  run,
  validateReview,
};
