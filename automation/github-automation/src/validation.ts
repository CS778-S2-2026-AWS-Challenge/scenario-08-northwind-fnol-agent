import type { IssueEvent, JsonRecord, PullRequestEvent } from "./types";

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function requireRecord(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) throw new Error(`${path} must be an object.`);
  return value;
}

export function requireString(value: unknown, path: string): string {
  if (typeof value !== "string") throw new Error(`${path} must be a string.`);
  return value;
}

export function requireBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean.`);
  return value;
}

export function requireInteger(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${path} must be an integer.`);
  }
  return value;
}

export function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function optionalRecord(value: unknown): JsonRecord | null {
  return isRecord(value) ? value : null;
}

export function requireArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${path} must be an array.`);
  return value;
}

export function parseIssueEvent(payload: unknown): IssueEvent {
  const event = requireRecord(payload, "payload");
  const repository = requireRecord(event.repository, "payload.repository");
  const issue = requireRecord(event.issue, "payload.issue");
  const user = requireRecord(issue.user, "payload.issue.user");

  return {
    action: requireString(event.action, "payload.action"),
    repository: {
      fullName: requireString(repository.full_name, "payload.repository.full_name"),
    },
    issue: {
      number: requireInteger(issue.number, "payload.issue.number"),
      body: optionalString(issue.body) ?? "",
      state: requireString(issue.state, "payload.issue.state"),
      creator: requireString(user.login, "payload.issue.user.login"),
      htmlUrl: requireString(issue.html_url, "payload.issue.html_url"),
    },
  };
}

export function parsePullRequestEvent(payload: unknown): PullRequestEvent {
  const event = requireRecord(payload, "payload");
  const repository = requireRecord(event.repository, "payload.repository");
  const pullRequest = requireRecord(event.pull_request, "payload.pull_request");
  const head = requireRecord(pullRequest.head, "payload.pull_request.head");
  const changes = isRecord(event.changes) ? event.changes : null;
  const bodyChange = changes && isRecord(changes.body) ? changes.body : null;

  return {
    action: requireString(event.action, "payload.action"),
    repository: {
      fullName: requireString(repository.full_name, "payload.repository.full_name"),
    },
    pullRequest: {
      number: requireInteger(pullRequest.number, "payload.pull_request.number"),
      body: optionalString(pullRequest.body) ?? "",
      draft: requireBoolean(pullRequest.draft, "payload.pull_request.draft"),
      merged: requireBoolean(pullRequest.merged, "payload.pull_request.merged"),
      state: requireString(pullRequest.state, "payload.pull_request.state"),
      headSha: requireString(head.sha, "payload.pull_request.head.sha"),
      htmlUrl: requireString(pullRequest.html_url, "payload.pull_request.html_url"),
    },
    previousBody: bodyChange ? optionalString(bodyChange.from) : null,
  };
}
