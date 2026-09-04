import { describe, expect, it } from "vitest";

import { reconciliationStatus } from "../src/reconcile";

describe("Kanban reconciliation status", () => {
  it("keeps the webhook status rules during scheduled reconciliation", () => {
    expect(reconciliationStatus({ draft: true, merged: false, state: "OPEN" })).toBe(
      "In progress",
    );
    expect(reconciliationStatus({ draft: false, merged: false, state: "OPEN" })).toBe(
      "In review",
    );
    expect(reconciliationStatus({ draft: false, merged: false, state: "CLOSED" })).toBeNull();
    expect(reconciliationStatus({ draft: false, merged: true, state: "MERGED" })).toBe("Done");
  });
});
