const REQUIRED_READY_SECTIONS = [
  'Summary',
  'Acceptance evidence',
  'Local validation',
  'Contract and data impact',
  'Ownership and overlap',
  'Base and delivery topology',
  'Failure-path analysis',
  'Dependencies and risks',
];

const HIGH_RISK_CLASSES = new Set([
  'Shared contract',
  'Persistence or concurrency',
  'External side effect',
  'Identity, authority, security, or privacy',
  'Repository governance or deployment',
]);

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

function isNoneValue(value) {
  return /^(?:none|not applicable|n\/a)(?:\s*[-:].*)?\.?$/i.test((value || '').trim());
}

function isPendingValue(value) {
  return /^(?:pending|tbd|to be determined)(?:\s*[-:].*)?\.?$/i.test((value || '').trim());
}

function checkedBoxes(content) {
  if (!content) return [];
  const matches = content.matchAll(/^[ \t]*[-*][ \t]*\[[xX]\][ \t]+\S.*$/gm);
  return [...matches].map((match) => match[0].trim());
}

function fieldContent(body, label) {
  const escapedLabel = escapeRegExp(label);
  const match = (body || '').match(
    new RegExp(
      `^###\\s+${escapedLabel}\\s*\\r?\\n([\\s\\S]*?)(?=^###\\s+|^##\\s+|(?![\\s\\S]))`,
      'im',
    ),
  );
  return match ? match[1].replace(/<!--[\s\S]*?-->/g, '').trim() : null;
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

/**
 * @typedef {Object} PullRequestPolicyInput
 * @property {string} body
 * @property {boolean} isDraft
 * @property {string} owner
 * @property {string} repo
 */

/** @param {PullRequestPolicyInput} input */
function validatePullRequestBody(input) {
  const { body, isDraft, owner, repo } = input;
  const errors = [];
  const warnings = [];
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

  const requiredScopeLabels = ['Primary owner', 'Owned behavior', 'Non-goals', 'Scope changed since issue'];
  for (const label of requiredScopeLabels) {
    if (!labelledValue(summary, label)) {
      const message = `Complete \`${label}:\` in \`Summary\`.`;
      (isDraft ? warnings : errors).push(message);
    }
  }

  const governanceConfirmation = sectionContent(body, 'Governance confirmation');
  if (checkedBoxes(governanceConfirmation).length === 0) {
    (isDraft ? warnings : errors).push(
      'Check the box in `Governance confirmation` after reading AGENT.md and the governance skill in full.',
    );
  } else if (!/\bv\d+\.\d+\b/.test(governanceConfirmation)) {
    (isDraft ? warnings : errors).push(
      'State the governance skill version read (vX.Y) in `Governance confirmation`.',
    );
  }

  const documentationSync = sectionContent(body, 'Documentation sync check');
  if (checkedBoxes(documentationSync).length === 0) {
    (isDraft ? warnings : errors).push(
      'Check at least one box in `Documentation sync check`.',
    );
  }

  const impactStatement = sectionContent(body, 'Impact statement');
  if (checkedBoxes(impactStatement).length === 0) {
    (isDraft ? warnings : errors).push(
      'Check the box in `Impact statement` after confirming unrelated code is unaffected.',
    );
  }

  if (!isDraft) {
    for (const heading of REQUIRED_READY_SECTIONS) {
      if (heading === 'Summary') continue;
      const content = sectionContent(body, heading);
      if (!hasMeaningfulContent(content)) {
        errors.push(`Complete the \`## ${heading}\` section before requesting review.`);
      }
    }

    const localValidation = sectionContent(body, 'Local validation') || '';
    for (const label of ['Command', 'Result']) {
      if (!labelledValue(localValidation, label)) {
        errors.push(
          `Complete \`${label}:\` in \`Local validation\` (use \`Not run - reason\` when applicable).`,
        );
      }
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


    const ownership = sectionContent(body, 'Ownership and overlap') || '';
    for (const label of [
      'Expected impact area',
      'Cross-owner impact',
      'Overlapping issues or PRs',
      'Owner agreement',
    ]) {
      if (!labelledValue(ownership, label)) {
        errors.push(`Complete \`${label}:\` in \`Ownership and overlap\`.`);
      }
    }

    const topology = sectionContent(body, 'Base and delivery topology') || '';
    for (const label of ['Base reviewed against', 'Stacked parent', 'Intended merge order', 'Main changes affecting this PR']) {
      if (!labelledValue(topology, label)) {
        errors.push(`Complete \`${label}:\` in \`Base and delivery topology\`.`);
      }
    }

    const failureAnalysis = sectionContent(body, 'Failure-path analysis') || '';
    const riskClass = labelledValue(failureAnalysis, 'Risk class');
    for (const label of [
      'Risk class',
      'Ownership or stale authority',
      'Retry, concurrency, or duplicate delivery',
      'Partial side effect or unknown outcome',
      'Recovery or reconciliation',
      'Sensitive-data or model-output exposure',
    ]) {
      if (!labelledValue(failureAnalysis, label)) {
        errors.push(`Complete \`${label}:\` in \`Failure-path analysis\` (use \`None - reason\` when inapplicable).`);
      }
    }
    if (riskClass && HIGH_RISK_CLASSES.has(riskClass)) {
      const evidenceLabels = [
        'Ownership or stale authority',
        'Retry, concurrency, or duplicate delivery',
        'Partial side effect or unknown outcome',
        'Recovery or reconciliation',
        'Sensitive-data or model-output exposure',
      ];
      if (evidenceLabels.every((label) => isNoneValue(labelledValue(failureAnalysis, label)))) {
        errors.push('A high-risk PR must identify at least one applicable failure path and its evidence.');
      }
    }

    const dependenciesAndRisks = sectionContent(body, 'Dependencies and risks') || '';
    for (const label of ['Dependencies', 'Remaining risks']) {
      if (!labelledValue(dependenciesAndRisks, label)) {
        errors.push(`Complete \`${label}:\` in \`Dependencies and risks\` (use \`None\` when absent).`);
      }
    }

    const governance = sectionContent(body, 'Governance exception') || '';
    const protectedActions = labelledValue(governance, 'Protected actions');
    if (!protectedActions) {
      errors.push('Complete `Protected actions:` in `Governance exception` (use `None` for ordinary PRs).');
    } else if (!isNoneValue(protectedActions)) {
      const operator = labelledValue(governance, 'Operator');
      const reason = labelledValue(governance, 'Reason');
      const allowedPulls = labelledValue(governance, 'Allowed PRs');
      const starts = labelledValue(governance, 'Window starts');
      const expires = labelledValue(governance, 'Window expires');
      const restoration = labelledValue(governance, 'Restoration evidence');
      if (!operator || !/@[A-Za-z0-9-]+/.test(operator)) {
        errors.push('A governance exception requires an `@operator`.');
      }
      if (!reason || /^not required\.?$/i.test(reason) || /^repository maintenance\.?$/i.test(reason)) {
        errors.push('A governance exception requires a specific `Reason`.');
      }
      if (!allowedPulls || !/#\d+\b/.test(allowedPulls)) {
        errors.push('A governance exception requires an exact `#PR` allowlist.');
      }
      if (!starts || Number.isNaN(Date.parse(starts))) {
        errors.push('A governance exception requires an ISO-8601 `Window starts` timestamp.');
      }
      if (!expires || Number.isNaN(Date.parse(expires))) {
        errors.push('A governance exception requires an ISO-8601 `Window expires` timestamp.');
      }
      if (starts && expires && !Number.isNaN(Date.parse(starts)) && !Number.isNaN(Date.parse(expires)) && Date.parse(expires) <= Date.parse(starts)) {
        errors.push('A governance exception must expire after it starts.');
      }
      if (!restoration || isNoneValue(restoration) || /^not required\.?$/i.test(restoration)) {
        errors.push('A governance exception requires concrete restoration evidence.');
      }
    }
  }

  return { errors, warnings, references };
}

function loginIsDeclared(value, login) {
  if (!value || !login) return false;
  return new RegExp(`(?:^|[^A-Za-z0-9-])@?${escapeRegExp(login)}(?:$|[^A-Za-z0-9-])`, 'i').test(value);
}

function overlapDeclaration(body) {
  return labelledValue(sectionContent(body, 'Ownership and overlap'), 'Overlapping issues or PRs');
}

function crossOwnerDeclaration(body) {
  const section = sectionContent(body, 'Ownership and overlap');
  return {
    impact: labelledValue(section, 'Cross-owner impact'),
    agreement: labelledValue(section, 'Owner agreement'),
  };
}

function baseDeclarations(body) {
  const section = sectionContent(body, 'Base and delivery topology');
  return {
    parent: labelledValue(section, 'Stacked parent'),
    mainImpact: labelledValue(section, 'Main changes affecting this PR'),
  };
}

function changedPathOverlap(left, right) {
  const rightSet = new Set(right);
  return [...new Set(left.filter((path) => rightSet.has(path)))].sort();
}

async function run({ github, context, core }) {
  const pullRequest = context.payload.pull_request;
  const { owner, repo } = context.repo;
  const { errors, warnings, references } = validatePullRequestBody({
    body: pullRequest.body || '',
    isDraft: pullRequest.draft,
    owner,
    repo,
  });

  const primaryIssueNumber = references[0];

  let primaryIssue = null;

  for (const issueNumber of references) {
    try {
      const response = await github.rest.issues.get({ owner, repo, issue_number: issueNumber });
      if (response.data.pull_request) {
        errors.push(`#${issueNumber} is a pull request, not a repository issue.`);
      } else if (issueNumber === primaryIssueNumber) {
        primaryIssue = response.data;
      }
    } catch (error) {
      if (error.status === 404) {
        errors.push(`#${issueNumber} is not an issue in ${owner}/${repo}.`);
      } else {
        throw error;
      }
    }
  }


  if (primaryIssue) {
    const author = pullRequest.user?.login || '';
    const assignees = (primaryIssue.assignees || []).map((assignee) => assignee.login).filter(Boolean);
    const issueOwner = fieldContent(primaryIssue.body || '', 'Owner or responsible contributor') || '';
    const authorOwnsIssue = assignees.some((login) => login.toLowerCase() === author.toLowerCase()) ||
      loginIsDeclared(issueOwner, author);
    if (!authorOwnsIssue) {
      const declaration = crossOwnerDeclaration(pullRequest.body || '');
      if (isNoneValue(declaration.impact) || isNoneValue(declaration.agreement) ||
          isPendingValue(declaration.agreement) || !declaration.agreement) {
        const message = `PR author @${author || 'unknown'} is not a declared owner of primary issue #${primaryIssueNumber}; record cross-owner impact and owner agreement.`;
        (pullRequest.draft ? warnings : errors).push(message);
      }
    }
  }

  if (github.rest.pulls?.listFiles && github.rest.pulls?.list) {
    const currentFiles = await github.paginate(github.rest.pulls.listFiles, {
      owner, repo, pull_number: pullRequest.number, per_page: 100,
    });
    const currentPaths = currentFiles.map((file) => file.filename);
    const openPulls = await github.paginate(github.rest.pulls.list, {
      owner, repo, state: 'open', per_page: 100,
    });
    const overlaps = [];
    for (const other of openPulls) {
      if (other.number === pullRequest.number) continue;
      const otherFiles = await github.paginate(github.rest.pulls.listFiles, {
        owner, repo, pull_number: other.number, per_page: 100,
      });
      const shared = changedPathOverlap(currentPaths, otherFiles.map((file) => file.filename));
      if (shared.length > 0) {
        overlaps.push({
          number: other.number,
          author: other.user?.login || '',
          paths: shared,
        });
      }
    }
    const declaredOverlap = overlapDeclaration(pullRequest.body || '');
    if (overlaps.length > 0 && (!declaredOverlap || isNoneValue(declaredOverlap))) {
      const detail = overlaps.map(({ number, paths }) => `#${number} (${paths.slice(0, 3).join(', ')})`).join('; ');
      warnings.push(
        `Changed-file overlap is advisory topology evidence, not an ownership blocker: ${detail}.`,
      );
    }

    const topology = baseDeclarations(pullRequest.body || '');
    if (pullRequest.base?.ref !== 'main' && (!topology.parent || isNoneValue(topology.parent))) {
      const message = `Declare the stacked parent for non-main base \`${pullRequest.base?.ref || 'unknown'}\`.`;
      (pullRequest.draft ? warnings : errors).push(message);
    }
    if (pullRequest.base?.ref === 'main' && github.rest.repos?.compareCommitsWithBasehead) {
      const comparison = await github.rest.repos.compareCommitsWithBasehead({
        owner,
        repo,
        basehead: `${pullRequest.head.sha}...${pullRequest.base.sha}`,
        per_page: 100,
      });
      const baseChangedPaths = (comparison.data.files || []).map((file) => file.filename);
      const baseOverlap = changedPathOverlap(currentPaths, baseChangedPaths);
      if (baseOverlap.length > 0 && (!topology.mainImpact || isNoneValue(topology.mainImpact))) {
        const message = `Main changed paths also modified by this PR: ${baseOverlap.slice(0, 8).join(', ')}. Update the base or explain the resolution.`;
        (pullRequest.draft ? warnings : errors).push(message);
      }
    }
  }

  for (const warning of warnings) core.warning(`PR policy advisory: ${warning}`);

  if (errors.length > 0) {
    core.setFailed(`Pull-request policy failed:\n- ${errors.join('\n- ')}`);
    return { errors, warnings, references };
  }

  core.info(`Pull-request policy passed with issue reference(s): ${references.join(', ')}.`);
  return { errors, warnings, references };
}

module.exports = {
  baseDeclarations,
  changedPathOverlap,
  checkedBoxes,
  crossOwnerDeclaration,
  fieldContent,
  issueReferences,
  isNoneValue,
  isPendingValue,
  labelledValue,
  loginIsDeclared,
  overlapDeclaration,
  run,
  sectionContent,
  validatePullRequestBody,
};
