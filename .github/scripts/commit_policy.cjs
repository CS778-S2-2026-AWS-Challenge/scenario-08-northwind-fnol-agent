// Conventional Commits check for every commit in a pull request, plus breaking-change
// two-way consistency with the PR body. Merge commits are exempt.
// See docs/skills/repo-governance-for-novice/pr-workflow.md section 5.1 and ci-checks.md.
// The Cloudflare Worker runs this as part of the "Northwind PR policy" status.

const FIRST_LINE_PATTERN =
  /^(feat|fix|docs|chore|ci|test|refactor|perf|revert)(\((backend|frontend|docs|deploy|scripts|api|deps)\))?!?: .+/;
const BREAKING_FIRST_LINE = /^[a-z]+(\([a-z]+\))?!: /;
const BREAKING_FOOTER = /^BREAKING CHANGE:/m;
const BREAKING_HEADING = /^##+[ \t]+breaking change/im;
const BREAKING_LABEL = /^[ \t]*[-*]?[ \t]*breaking changes?:[ \t]*(.*)$/im;

function bodyDeclaresBreakingChange(body) {
  if (BREAKING_HEADING.test(body || '')) return true;
  const match = (body || '').match(BREAKING_LABEL);
  if (!match) return false;
  const value = match[1].trim();
  return value.length > 0 && !/^(none|not applicable|n\/a)\b/i.test(value);
}

/**
 * @param {{ commits: { sha: string, message: string, parentCount: number }[], body: string }} input
 * @returns {{ errors: string[] }}
 */
function validateCommits({ commits, body }) {
  const errors = [];
  let breakingCommits = 0;
  for (const commit of commits) {
    if (commit.parentCount > 1) continue;
    const firstLine = commit.message.split('\n', 1)[0];
    if (!FIRST_LINE_PATTERN.test(firstLine)) {
      errors.push(
        `Commit ${commit.sha.slice(0, 7)} "${firstLine}" does not match Conventional Commits ` +
          '(type(scope): description; see pr-workflow.md 5.1).',
      );
    }
    if (BREAKING_FIRST_LINE.test(firstLine) || BREAKING_FOOTER.test(commit.message)) {
      breakingCommits += 1;
    }
  }
  const declared = bodyDeclaresBreakingChange(body);
  if (breakingCommits > 0 && !declared) {
    errors.push('A commit marks a breaking change but the PR body has no breaking-change declaration.');
  }
  if (breakingCommits === 0 && declared) {
    errors.push('The PR body declares a breaking change but no commit carries ! or a BREAKING CHANGE footer.');
  }
  return { errors };
}

module.exports = { FIRST_LINE_PATTERN, validateCommits };
