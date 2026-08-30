import {
  validateDiscussionApproval,
  validateIssueBody,
} from "../../../.github/scripts/issue_policy.cjs";

import type { GitHubClient } from "./github";
import type { IssueEvent } from "./types";

export const ISSUE_POLICY_MARKER = "<!-- issue-policy -->";
export const ISSUE_POLICY_ACTIONS = ["opened", "edited", "reopened"];

function splitRepository(repository: string): { owner: string; repo: string } {
  const [owner, repo, ...extra] = repository.split("/");
  if (!owner || !repo || extra.length > 0) throw new Error(`Invalid repository name: ${repository}`);
  return { owner, repo };
}

export async function evaluateIssuePolicy(
  event: IssueEvent,
  client: GitHubClient,
  maintainer: string,
): Promise<{ errors: string[] }> {
  const { owner, repo } = splitRepository(event.repository.fullName);
  const result = validateIssueBody({ body: event.issue.body });
  const approval = validateDiscussionApproval({
    body: event.issue.body,
    creator: event.issue.creator,
    maintainer,
  });
  const errors = [...result.errors, ...approval.errors];
  if (errors.length === 0) return { errors };

  const comments = await client.listIssueComments(owner, repo, event.issue.number);
  const alreadyNotified = comments.some(
    (comment) => typeof comment.body === "string" && comment.body.includes(ISSUE_POLICY_MARKER),
  );
  if (!alreadyNotified) {
    const lines = errors.map((error) => `- ${error}`).join("\n");
    await client.createIssueComment(
      owner,
      repo,
      event.issue.number,
      `${ISSUE_POLICY_MARKER}\nThe issue policy check found:\n${lines}\n\n` +
        "Update this issue using the **Code work** form. This check does not close or delete issues.",
    );
  }
  return { errors };
}
