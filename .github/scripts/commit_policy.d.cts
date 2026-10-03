export interface PolicyCommit {
  sha: string;
  message: string;
  parentCount: number;
}

export const FIRST_LINE_PATTERN: RegExp;

export function validateCommits(input: { commits: PolicyCommit[]; body: string }): {
  errors: string[];
};
