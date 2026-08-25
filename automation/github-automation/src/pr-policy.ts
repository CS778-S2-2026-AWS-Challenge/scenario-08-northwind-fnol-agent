import { validatePullRequestBody } from "../../../.github/scripts/pr_policy.cjs";

import { GitHubApiError } from "./github";
import type { GitHubClient } from "./github";
import type { PullRequestEvent } from "./types";

function splitRepository(repository: string): { owner: string; repo: string } {
  const [owner, repo, ...extra] = repository.split("/");
  if (!owner || !repo || extra.length > 0) throw new Error(`Invalid repository name: ${repository}`);
  return { owner, repo };
}

function statusDescription(errors: readonly string[]): string {
  if (errors.length === 0) return "Pull-request policy passed.";
  const description = `PR policy failed: ${errors[0] ?? "Unknown policy error"}`;
  return description.length <= 140 ? description : `${description.slice(0, 137)}...`;
}

export async function evaluatePullRequestPolicy(
  event: PullRequestEvent,
  client: GitHubClient,
): Promise<{ errors: string[]; references: number[] }> {
  const { owner, repo } = splitRepository(event.repository.fullName);
  const result = validatePullRequestBody({
    body: event.pullRequest.body,
    isDraft: event.pullRequest.draft,
    owner,
    repo,
  });

  for (const issueNumber of result.references) {
    try {
      const issue = await client.getIssue(owner, repo, issueNumber);
      if (issue.pull_request !== undefined) {
        result.errors.push(`#${String(issueNumber)} is a pull request, not a repository issue.`);
      }
    } catch (error) {
      if (error instanceof GitHubApiError && error.status === 404) {
        result.errors.push(`#${String(issueNumber)} is not an issue in ${owner}/${repo}.`);
      } else {
        throw error;
      }
    }
  }

  await client.setCommitStatus({
    owner,
    repo,
    sha: event.pullRequest.headSha,
    state: result.errors.length === 0 ? "success" : "failure",
    description: statusDescription(result.errors),
    targetUrl: event.pullRequest.htmlUrl,
  });
  return result;
}
