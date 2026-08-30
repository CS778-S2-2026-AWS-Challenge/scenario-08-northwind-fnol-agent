#!/usr/bin/env bash
# Conventional Commits format check for every commit in a pull request, plus
# breaking-change two-way consistency with the PR body. Merge commits are
# exempt. See docs/skills/repo-governance-for-novice/pr-workflow.md section 5.1
# and ci-checks.md.
#
# Usage: check_commit_format.sh <owner/repo> <pr-number>
# Requires GH_TOKEN or GITHUB_TOKEN with read access, curl, and jq.
set -euo pipefail

repo_slug="${1:?usage: check_commit_format.sh <owner/repo> <pr-number>}"
pr_number="${2:?usage: check_commit_format.sh <owner/repo> <pr-number>}"
token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
if [ -z "${token}" ]; then
  echo "GH_TOKEN or GITHUB_TOKEN is required." >&2
  exit 1
fi

api="https://api.github.com/repos/${repo_slug}"
auth=(-H "Authorization: Bearer ${token}" -H "Accept: application/vnd.github+json")

first_line_pattern='^(feat|fix|docs|chore|ci|test|refactor|perf|revert)(\((backend|frontend|docs|deploy|scripts|api|deps)\))?!?: .+'

pr_body=$(curl -sf "${auth[@]}" "${api}/pulls/${pr_number}" | jq -r '.body // ""')

failures=0
breaking_commits=0
page=1
while :; do
  commits=$(curl -sf "${auth[@]}" "${api}/pulls/${pr_number}/commits?per_page=100&page=${page}")
  count=$(printf '%s' "${commits}" | jq 'length')
  [ "${count}" -eq 0 ] && break
  while IFS= read -r encoded; do
    sha=$(printf '%s' "${encoded}" | jq -r '.sha[0:7]')
    parents=$(printf '%s' "${encoded}" | jq '.parents | length')
    message=$(printf '%s' "${encoded}" | jq -r '.commit.message')
    first_line=${message%%$'\n'*}
    if [ "${parents}" -gt 1 ]; then
      echo "SKIP  ${sha}  merge commit (exempt)"
      continue
    fi
    if printf '%s' "${first_line}" | grep -Eq "${first_line_pattern}"; then
      echo "OK    ${sha}  ${first_line}"
    else
      echo "FAIL  ${sha}  ${first_line}"
      failures=$((failures + 1))
    fi
    if printf '%s' "${first_line}" | grep -Eq '^[a-z]+(\([a-z]+\))?!: ' ||
      printf '%s\n' "${message}" | grep -q '^BREAKING CHANGE:'; then
      breaking_commits=$((breaking_commits + 1))
    fi
  done < <(printf '%s' "${commits}" | jq -c '.[]')
  [ "${count}" -lt 100 ] && break
  page=$((page + 1))
done

if [ "${failures}" -gt 0 ]; then
  echo ""
  echo "Commit message first lines must match:"
  echo "  ${first_line_pattern}"
  echo "Merge commits are exempt. See docs/skills/repo-governance-for-novice/pr-workflow.md 5.1."
  exit 1
fi

# The PR body declares a breaking change via a heading (## Breaking change) or
# a labelled line (Breaking change: <non-None value>).
body_declares_breaking=0
if printf '%s\n' "${pr_body}" | grep -Eiq '^##+[ \t]+breaking change'; then
  body_declares_breaking=1
else
  declaration=$(printf '%s\n' "${pr_body}" |
    grep -Ei '^[ \t]*[-*]?[ \t]*breaking changes?:' | head -n 1 || true)
  if [ -n "${declaration}" ]; then
    value=$(printf '%s' "${declaration}" | sed -E 's/^[ \t]*[-*]?[ \t]*[Bb]reaking [Cc]hanges?:[ \t]*//')
    if [ -n "${value}" ] && ! printf '%s' "${value}" | grep -Eiq '^(none|not applicable|n/a)\b'; then
      body_declares_breaking=1
    fi
  fi
fi

if [ "${breaking_commits}" -gt 0 ] && [ "${body_declares_breaking}" -eq 0 ]; then
  echo "Breaking-change commits found (! or a BREAKING CHANGE footer) but the PR body carries no breaking-change declaration."
  exit 1
fi
if [ "${breaking_commits}" -eq 0 ] && [ "${body_declares_breaking}" -eq 1 ]; then
  echo "The PR body declares a breaking change but no commit carries ! or a BREAKING CHANGE footer."
  exit 1
fi

echo "Commit message format check passed (${breaking_commits} breaking-change commit(s))."
