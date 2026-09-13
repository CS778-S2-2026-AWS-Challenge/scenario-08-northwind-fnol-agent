export interface IssueBodyResult {
  errors: string[];
  fields: Record<string, string | null>;
}

export declare function fieldContent(body: string, label: string): string | null;

export declare function validateIssueBody(input: { body: string }): IssueBodyResult;
