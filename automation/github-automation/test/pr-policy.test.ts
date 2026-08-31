import { describe, expect, it } from "vitest";

import { GitHubClient, PR_POLICY_STATUS_CONTEXT } from "../src/github";
import { evaluatePullRequestPolicy } from "../src/pr-policy";
import type { PullRequestEvent } from "../src/types";

function event(body: string): PullRequestEvent {
  return {
    action: "opened",
    repository: {
      fullName: "CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent",
    },
    pullRequest: {
      number: 301,
      body,
      draft: true,
      merged: false,
      state: "open",
      headSha: "head-sha-301",
      htmlUrl: "https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/pull/301",
    },
    previousBody: null,
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

describe("Worker PR policy adapter", () => {
  it("writes success to the exact pull-request head", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetcher: typeof fetch = (input, init) => {
      const url = requestUrl(input);
      calls.push({ url, init });
      if (url.endsWith("/issues/101")) return Promise.resolve(Response.json({ number: 101 }));
      if (url.endsWith("/statuses/head-sha-301")) return Promise.resolve(Response.json({ id: 1 }));
      return Promise.resolve(new Response("not found", { status: 404 }));
    };
    const client = new GitHubClient("test-token", fetcher);

    const result = await evaluatePullRequestPolicy(
      event("## Linked issue\n\nRefs #101\n\n## Summary\n\nImplements the bounded automation."),
      client,
    );

    expect(result.errors).toEqual([]);
    const statusCall = calls.find((call) => call.url.endsWith("/statuses/head-sha-301"));
    expect(statusCall).toBeDefined();
    expect(JSON.parse(requestBody(statusCall?.init)) as unknown).toMatchObject({
      state: "success",
      context: PR_POLICY_STATUS_CONTEXT,
    });
  });

  it("writes failure instead of retrying a missing linked issue", async () => {
    let statusBody: Record<string, unknown> | null = null;
    const fetcher: typeof fetch = (input, init) => {
      const url = requestUrl(input);
      if (url.endsWith("/issues/999")) {
        return Promise.resolve(new Response("missing", { status: 404 }));
      }
      if (url.endsWith("/statuses/head-sha-301")) {
        statusBody = JSON.parse(requestBody(init)) as Record<string, unknown>;
        return Promise.resolve(Response.json({ id: 2 }));
      }
      return Promise.resolve(new Response("not found", { status: 404 }));
    };

    const result = await evaluatePullRequestPolicy(
      event("## Linked issue\n\nRefs #999\n\n## Summary\n\nChecks a missing issue."),
      new GitHubClient("test-token", fetcher),
    );

    expect(result.errors).toContain(
      "#999 is not an issue in CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent.",
    );
    expect(statusBody).toMatchObject({ state: "failure", context: PR_POLICY_STATUS_CONTEXT });
  });
});
