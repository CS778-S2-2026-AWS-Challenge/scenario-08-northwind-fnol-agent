const { isNoneValue, labelledValue, sectionContent } = require('./pr_policy.cjs');

function referencedPullRequests(value) {
  if (!value) return [];
  return [...new Set([...value.matchAll(/#(\d+)\b/g)].map((match) => Number(match[1])))];
}

function governanceWindow(body) {
  const section = sectionContent(body || '', 'Governance exception');
  return {
    actions: labelledValue(section, 'Protected actions'),
    reason: labelledValue(section, 'Reason'),
    operator: labelledValue(section, 'Operator'),
    allowedPulls: referencedPullRequests(labelledValue(section, 'Allowed PRs')),
    starts: labelledValue(section, 'Window starts'),
    expires: labelledValue(section, 'Window expires'),
    restoration: labelledValue(section, 'Restoration evidence'),
  };
}

function windowMatches({ body, pullNumber, actor, operation, occurredAt }) {
  const window = governanceWindow(body);
  const reasons = [];
  if (!window.actions || isNoneValue(window.actions) || !new RegExp(`\\b${operation}\\b`, 'i').test(window.actions)) {
    reasons.push(`Protected actions does not allow ${operation}.`);
  }
  if (!window.operator || !window.operator.toLowerCase().includes(`@${actor.toLowerCase()}`)) {
    reasons.push(`Operator does not match @${actor}.`);
  }
  if (!window.reason || /^not required\.?$/i.test(window.reason) || /^repository maintenance\.?$/i.test(window.reason)) {
    reasons.push('Reason is missing or too broad.');
  }
  if (!window.allowedPulls.includes(pullNumber)) {
    reasons.push(`Allowed PRs does not include #${pullNumber}.`);
  }
  const starts = Date.parse(window.starts || '');
  const expires = Date.parse(window.expires || '');
  const occurred = Date.parse(occurredAt);
  if ([starts, expires, occurred].some(Number.isNaN) || occurred < starts || occurred > expires) {
    reasons.push('The operation is outside a valid governance-window time range.');
  }
  if (!window.restoration || isNoneValue(window.restoration) || /^not required\.?$/i.test(window.restoration)) {
    reasons.push('Restoration evidence is not defined.');
  }
  return { matches: reasons.length === 0, reasons, window };
}

function auditPullRequestEvent({ action, pullRequest, actor, occurredAt, nonFastForward = false }) {
  if (action === 'synchronize' && nonFastForward) {
    return {
      classification: 'non_fast_forward_pr_update',
      incident: true,
      reasons: ['The previous PR head is not an ancestor of the new head.'],
    };
  }
  if (action === 'closed' && pullRequest.merged) {
    const match = windowMatches({
      body: pullRequest.body || '',
      pullNumber: pullRequest.number,
      actor,
      operation: 'merge',
      occurredAt,
    });
    if (match.matches) {
      return { classification: 'governance_window_merge', incident: false, reasons: [] };
    }
    if ((pullRequest.user?.login || '').toLowerCase() === actor.toLowerCase()) {
      return {
        classification: 'self_merge_without_matching_governance_window',
        incident: true,
        reasons: match.reasons,
      };
    }
    return { classification: 'non_author_merge', incident: false, reasons: [] };
  }

  if (['ready_for_review', 'converted_to_draft', 'reopened', 'edited', 'closed'].includes(action)) {
    return {
      classification: `protected_pr_state_observed:${action}`,
      incident: false,
      reasons: ['The account actor is recorded; GitHub cannot establish whether a human authorised the action.'],
    };
  }

  return { classification: 'not_applicable', incident: false, reasons: [] };
}

async function run({ github, context, core }) {
  const pullRequest = context.payload.pull_request;
  const actor = context.actor;
  let nonFastForward = false;
  if (context.payload.action === 'synchronize' && context.payload.before && pullRequest.head?.sha) {
    const comparison = await github.rest.repos.compareCommitsWithBasehead({
      ...context.repo,
      basehead: `${context.payload.before}...${pullRequest.head.sha}`,
    });
    nonFastForward = !['ahead', 'identical'].includes(comparison.data.status);
  }
  const result = auditPullRequestEvent({
    action: context.payload.action,
    pullRequest,
    actor,
    occurredAt: pullRequest.merged_at || new Date().toISOString(),
    nonFastForward,
  });
  core.info(JSON.stringify({
    event: 'governance_audit',
    pullRequest: pullRequest.number,
    actor,
    ...result,
  }));
  if (!result.incident) return result;

  const marker = '<!-- governance-audit -->';
  const body = `${marker}\nGovernance audit incident: **${result.classification}**.\n\n` +
    `GitHub records account \`@${actor}\` as the actor for this protected PR operation. ` +
    'This audit identifies the account action; it cannot determine whether a human or agent initiated it.\n\n' +
    result.reasons.map((reason) => `- ${reason}`).join('\n');
  const comments = await github.rest.issues.listComments({
    ...context.repo,
    issue_number: pullRequest.number,
    per_page: 100,
  });
  if (!comments.data.some((comment) => (comment.body || '').includes(marker))) {
    await github.rest.issues.createComment({
      ...context.repo,
      issue_number: pullRequest.number,
      body,
    });
  }
  core.setFailed(`Governance incident: ${result.classification}`);
  return result;
}

module.exports = {
  auditPullRequestEvent,
  governanceWindow,
  referencedPullRequests,
  run,
  windowMatches,
};
