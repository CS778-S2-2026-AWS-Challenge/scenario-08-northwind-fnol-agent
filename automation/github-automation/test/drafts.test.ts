import { describe, expect, it } from "vitest";

import {
  isAucklandWorkingTime,
  type ProjectItemSnapshot,
  validateReadyDraft,
} from "../src/drafts";

function draft(overrides: Partial<ProjectItemSnapshot> = {}): ProjectItemSnapshot {
  return {
    id: "PVTI_draft",
    contentId: "DI_draft",
    contentType: "DraftIssue",
    issueNumber: null,
    title: "D2-I01 Collaboration rules",
    body: "## Acceptance\n- Rules are checkable.\n\n## Dependencies\n- None",
    assignees: ["Ysoseri1224"],
    status: "Ready",
    tracking: "Repository issue",
    size: "M",
    estimate: 3,
    startDate: "2026-08-25",
    targetDate: "2026-08-25",
    ...overrides,
  };
}

describe("Ready DraftIssue validation", () => {
  it("accepts a complete repository-tracked card", () => {
    const item = draft();
    expect(validateReadyDraft(item, [item], "Repository issue")).toEqual([]);
  });

  it("requires completed explicit dependencies and the estimate-to-size mapping", () => {
    const dependency = draft({
      id: "dependency",
      title: "D2-I03 API contract",
      status: "In progress",
    });
    const item = draft({
      size: "S",
      body: "## Acceptance\n- Rules are checkable.\n\n## Dependencies\n- D2-I03 API contract",
    });

    expect(validateReadyDraft(item, [item, dependency], "Repository issue")).toEqual([
      "Size M for Estimate 3h",
      "dependency D2-I03 to be Done",
    ]);
  });
});

describe("Auckland work window", () => {
  it("runs on a weekday between 10:00 and 18:00 local time", () => {
    expect(isAucklandWorkingTime(new Date("2026-08-25T00:00:00Z"))).toBe(true);
    expect(isAucklandWorkingTime(new Date("2026-08-25T06:00:00Z"))).toBe(false);
    expect(isAucklandWorkingTime(new Date("2026-08-22T00:00:00Z"))).toBe(false);
  });
});
