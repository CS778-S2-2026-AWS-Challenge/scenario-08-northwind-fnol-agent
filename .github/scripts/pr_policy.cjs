const REQUIRED_READY_SECTIONS = [
  'Summary',
  'Acceptance evidence',
  'Local validation',
  'Contract and data impact',
  'Dependencies and risks',
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function sectionContent(body, heading) {
  const escapedHeading = escapeRegExp(heading);
  const match = body.match(
    new RegExp(
      `^##\\s+${escapedHeading}\\s*\\r?\\n([\\s\\S]*?)(?=^##\\s+|(?![\\s\\S]))`,
      'im',
    ),
  );
  return match ? match[1].replace(/<!--[\s\S]*?-->/g, '').trim() : null;
}

function hasMeaningfulContent(content) {
  return content !== null && /[A-Za-z0-9]/.test(content);
}

function labelledValue(content, label) {
  if (!content) return null;
  const escapedLabel = escapeRegExp(label);
  const match = content.match(
    new RegExp(`^[ \\t]*[-*]?[ \\t]*${escapedLabel}:[ \\t]*([^\\r\\n]+?)[ \\t]*$`, 'im'),
  );
  return match && /[A-Za-z0-9]/.test(match[1]) ? match[1] : null;
}

function issueReferences(content, owner, repo) {
  if (!content) return [];

  const keyword = '(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|references?)';
  const ownerPattern = escapeRegExp(owner);
  const repoPattern = escapeRegExp(repo);
  const patterns = [
    new RegExp(`\\b${keyword}\\s+#(\\d+)`, 'gi'),
    new RegExp(
      `\\b${keyword}\\s+https://github\\.com/${ownerPattern}/${repoPattern}/issues/(\\d+)`,
      'gi',
    ),
  ];
  const references = [];
  for (const pattern of patterns) {
    for (const match of content.matchAll(pattern)) references.push(Number(match[1]));
  }
  return [...new Set(references)];
}

function validatePullRequestBody({ body, isDraft, owner, repo }) {
  const errors = [];
  const linkedIssue = sectionContent(body, 'Linked issue');
  const references = issueReferences(linkedIssue, owner, repo);

  if (linkedIssue === null) errors.push('Add the `## Linked issue` section.');
  if (references.length === 0) {
    errors.push(
      'Reference a repository issue in `Linked issue` with Closes/Fixes/Resolves #n or Refs #n.',
    );
  }

  const summary = sectionContent(body, 'Summary');
  if (!hasMeaningfulContent(summary)) {
    errors.push('Complete the `## Summary` section when opening a pull request.');
  }

  if (!isDraft) {
    for (const heading of REQUIRED_READY_SECTIONS) {
      if (heading === 'Summary') continue;
      const content = sectionContent(body, heading);
      if (!hasMeaningfulContent(content)) {
        errors.push(`Complete the \`## ${heading}\` section before requesting review.`);
      }
    }

    const validation = sectionContent(body, 'Local validation') || '';
    if (!/[.\\/]scripts[\\/]check\.ps1(?:\s|`|$)/i.test(validation)) {
      errors.push('Record `./scripts/check.ps1` in `Local validation`.');
    }
    if (!/Result:\s*PASS\b/i.test(validation)) {
      errors.push('Record `Result: PASS` only after the complete local quality gate passes.');
    }

    const contractImpact = sectionContent(body, 'Contract and data impact') || '';
    for (const label of [
      'API contract',
      'Persistence schema',
      'Fixtures and tests',
      'Claimant and staff projections',
    ]) {
      if (!labelledValue(contractImpact, label)) {
        errors.push(`Complete \`${label}:\` in \`Contract and data impact\` (use \`None\` when unaffected).`);
      }
    }

    const dependenciesAndRisks = sectionContent(body, 'Dependencies and risks') || '';
    for (const label of ['Dependencies', 'Remaining risks']) {
      if (!labelledValue(dependenciesAndRisks, label)) {
        errors.push(`Complete \`${label}:\` in \`Dependencies and risks\` (use \`None\` when absent).`);
      }
    }
  }

  return { errors, references };
}

async function run({ github, context, core }) {
  const pullRequest = context.payload.pull_request;
  const { owner, repo } = context.repo;
  const { errors, references } = validatePullRequestBody({
    body: pullRequest.body || '',
    isDraft: pullRequest.draft,
    owner,
    repo,
  });

  for (const issueNumber of references) {
    try {
      const response = await github.rest.issues.get({ owner, repo, issue_number: issueNumber });
      if (response.data.pull_request) {
        errors.push(`#${issueNumber} is a pull request, not a repository issue.`);
      }
    } catch (error) {
      if (error.status === 404) {
        errors.push(`#${issueNumber} is not an issue in ${owner}/${repo}.`);
      } else {
        throw error;
      }
    }
  }

  if (errors.length > 0) {
    core.setFailed(`Pull-request policy failed:\n- ${errors.join('\n- ')}`);
    return;
  }

  core.info(`Pull-request policy passed with issue reference(s): ${references.join(', ')}.`);
}

module.exports = {
  issueReferences,
  labelledValue,
  run,
  sectionContent,
  validatePullRequestBody,
};
