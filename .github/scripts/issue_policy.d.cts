export interface IssueBodyResult {
  errors: string[];
  fields: Record<string, string | null>;
}

export interface DiscussionApprovalInput {
  body: string;
  creator: string;
  maintainer: string;
}

export declare function fieldContent(body: string, label: string): string | null;

export declare function validateIssueBody(input: { body: string }): IssueBodyResult;

export declare function validateDiscussionApproval(
  input: DiscussionApprovalInput,
): { errors: string[] };
