export interface PullRequestPolicyInput {
  body: string;
  isDraft: boolean;
  owner: string;
  repo: string;
}

export interface PullRequestPolicyResult {
  errors: string[];
  references: number[];
}

export function validatePullRequestBody(
  input: PullRequestPolicyInput,
): PullRequestPolicyResult;
