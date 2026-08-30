import { describe, expect, it } from "vitest";

import { GitHubClient } from "../src/github";
import { ISSUE_POLICY_MARKER, evaluateIssuePolicy } from "../src/issue-policy";
import type { IssueEvent } from "../src/types";
import { parseIssueEvent } from "../src/validation";

const MAINTAINER = "Ysoseri1224";

const validBody = `### Issue type
Regression validation

### Problem or reason
The integrated fallback path lacks one regression test.

### Deliverable
One pytest covering the fallback path.

### Acceptance criteria
- [ ] The regression test passes.

### Related issue or PR
None - standalone repository work.

### Dependencies
None

### Owned behavior
The fallback regression test only.

### Expected impact area
tests/

### Non-goals
No production code changes.

### Shared contracts
None

### Risk class
Standard

### Owner or responsible contributor
@someone-else
`;

function event(body: string, creator = "someone-else"): IssueEvent {
  return {
    action: "opened",
    repository: {
      fullName: "CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent",
    },
    issue: {
      number: 401,
      body,
      state: "open",
      creator,
      htmlUrl: "https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/401",
    },
  };
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

function requestBody(init: RequestInit | undefined): string {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON string request body.");
  return init.body;
}

function clientWithComments(
  existingComments: { body: string }[],
  calls: { url: string; init?: RequestInit }[],
): GitHubClient {
  const fetcher: typeof fetch = (input, init) => {
    const url = requestUrl(input);
    calls.push({ url, init });
    if (url.includes("/issues/401/comments") && (!init?.method || init.method === "GET")) {
      return Promise.resolve(Response.json(existingComments));
    }
    if (url.includes("/issues/401/comments") && init?.method === "POST") {
      return Promise.resolve(Response.json({ id: 1 }));
    }
    return Promise.resolve(new Response("not found", { status: 404 }));
  };
  return new GitHubClient("test-token", fetcher);
}

describe("Worker issue policy adapter", () => {
  it("accepts a maintainer issue with a complete body and posts no comment", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const client = clientWithComments([], calls);
    const approvedBody = validBody.replace("@someone-else", `@${MAINTAINER}`);

    const result = await evaluateIssuePolicy(event(approvedBody, MAINTAINER), client, MAINTAINER);

    expect(result.errors).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("comments once when a non-maintainer issue lacks a discussion approval", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const client = clientWithComments([], calls);

    const result = await evaluateIssuePolicy(event(validBody), client, MAINTAINER);

    expect(result.errors.some((error) => error.includes("Discussion approval"))).toBe(true);
    const postCall = calls.find((call) => call.init?.method === "POST");
    expect(postCall).toBeDefined();
    const body = JSON.parse(requestBody(postCall?.init)) as { body: string };
    expect(body.body).toContain(ISSUE_POLICY_MARKER);
    expect(body.body).toContain("Discussion approval");
  });

  it("does not repeat an existing policy comment", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const client = clientWithComments([{ body: `${ISSUE_POLICY_MARKER}\nEarlier finding.` }], calls);

    const result = await evaluateIssuePolicy(event(validBody), client, MAINTAINER);

    expect(result.errors.length).toBeGreaterThan(0);
    expect(calls.some((call) => call.init?.method === "POST")).toBe(false);
  });

  it("accepts a non-maintainer issue that records an approved discussion thread", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const client = clientWithComments([], calls);
    const approvedBody = `${validBody}
### Discussion approval
https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/discussions/12
`;

    const result = await evaluateIssuePolicy(event(approvedBody), client, MAINTAINER);

    expect(result.errors).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("parses a GitHub issues webhook payload", () => {
    const parsed = parseIssueEvent({
      action: "opened",
      repository: { full_name: "CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent" },
      issue: {
        number: 401,
        body: null,
        state: "open",
        user: { login: "someone-else" },
        html_url: "https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/401",
      },
    });
    expect(parsed.issue.number).toBe(401);
    expect(parsed.issue.body).toBe("");
    expect(parsed.issue.creator).toBe("someone-else");
  });
});
