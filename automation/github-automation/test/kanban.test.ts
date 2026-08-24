import { describe, expect, it } from "vitest";

import { GitHubClient } from "../src/github";
import { closingIssueNumbers, statusForPullRequest, syncPullRequestKanban } from "../src/kanban";
import type { ProjectEnvironment, PullRequestEvent } from "../src/types";
import { requireRecord, requireString } from "../src/validation";

const repository = "CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent";
const projectEnvironment = {
  PROJECT_OWNER: "CS778-S2-2026-AWS-Challenge",
  PROJECT_NUMBER: "12",
  PROJECT_ID: "PVT_kwDOEp1gU84BfaGk",
  TARGET_REPOSITORY: repository,
  TRACKING_FIELD: "Tracking",
  REPOSITORY_TRACKING_OPTION: "Repository issue",
  DELIVERY_TRACKING_OPTION: "Delivery without repo",
} satisfies ProjectEnvironment;

function pullRequestEvent(action: string, draft: boolean, merged = false): PullRequestEvent {
  return {
    action,
    repository: { fullName: repository },
    pullRequest: {
      number: 300,
      body: "",
      draft,
      merged,
      state: action === "closed" ? "closed" : "open",
      headSha: "abc123",
      htmlUrl: "https://github.com/example/repo/pull/300",
    },
    previousBody: null,
  };
}

describe("Kanban pull-request status rules", () => {
  it("uses a Draft pull request as the explicit start signal", () => {
    expect(statusForPullRequest(pullRequestEvent("opened", true))).toBe("In progress");
    expect(statusForPullRequest(pullRequestEvent("converted_to_draft", true))).toBe("In progress");
  });

  it("uses review readiness, closure, and merge without changing Draft state", () => {
    expect(statusForPullRequest(pullRequestEvent("ready_for_review", false))).toBe("In review");
    expect(statusForPullRequest(pullRequestEvent("closed", false))).toBe("In progress");
    expect(statusForPullRequest(pullRequestEvent("closed", false, true))).toBe("Done");
  });

  it("extracts only closing references for the target repository", () => {
    const body = `Refs #10
Closes #11
Fixes ${repository}#12
Resolves https://github.com/${repository}/issues/13
Closes example/other#14`;

    expect(closingIssueNumbers(body, repository)).toEqual([11, 12, 13]);
  });

  it("writes In progress for the closing Issue of an opened Draft pull request", async () => {
    const selectedOptions: string[] = [];
    const fetcher: typeof fetch = (_input, init) => {
      if (typeof init?.body !== "string") throw new Error("Expected a GraphQL request body.");
      const payload: unknown = JSON.parse(init.body);
      const request = requireRecord(payload, "test GraphQL request");
      const query = requireString(request.query, "test GraphQL query");
      const variables = requireRecord(request.variables, "test GraphQL variables");

      if (query.includes("ProjectConfiguration")) {
        return Promise.resolve(Response.json({ data: { organization: { projectV2: {
          id: "PVT_kwDOEp1gU84BfaGk",
          fields: { nodes: [
            { id: "status", name: "Status", options: [
              { id: "status-progress", name: "In progress" },
              { id: "status-review", name: "In review" },
              { id: "status-done", name: "Done" },
            ] },
            { id: "tracking", name: "Tracking", options: [
              { id: "tracking-repo", name: "Repository issue" },
              { id: "tracking-delivery", name: "Delivery without repo" },
            ] },
            { id: "size", name: "Size", options: [{ id: "size-m", name: "M" }] },
            { id: "estimate", name: "Estimate" },
            { id: "start", name: "Start date" },
            { id: "target", name: "Target date" },
          ] },
        } } } }));
      }
      if (query.includes("ClosingIssues")) {
        return Promise.resolve(Response.json({ data: { repository: { pullRequest: {
          closingIssuesReferences: { nodes: [{
            number: 101,
            state: "OPEN",
            url: "https://github.com/example/repo/issues/101",
            projectItems: { nodes: [{
              id: "PVTI_101",
              project: { id: "PVT_kwDOEp1gU84BfaGk" },
            }] },
          }] },
        } } } }));
      }
      if (query.includes("UpdateSingleSelect")) {
        selectedOptions.push(requireString(variables.optionId, "test optionId"));
        return Promise.resolve(Response.json({ data: {
          updateProjectV2ItemFieldValue: { projectV2Item: { id: "PVTI_101" } },
        } }));
      }
      throw new Error("Unexpected GraphQL operation.");
    };

    await syncPullRequestKanban(
      pullRequestEvent("opened", true),
      new GitHubClient("test-token", fetcher),
      projectEnvironment,
    );

    expect(selectedOptions).toEqual(["status-progress"]);
  });
});
