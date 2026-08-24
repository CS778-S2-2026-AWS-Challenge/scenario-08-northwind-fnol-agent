import { describe, expect, it } from "vitest";

import type { GitHubQueueMessage } from "../src/types";
import { handleWebhookRequest, verifyGitHubSignature } from "../src/webhook";

async function signature(body: string, secret: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const bytes = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(body)));
  return `sha256=${[...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

describe("GitHub webhook", () => {
  it("verifies a valid SHA-256 HMAC and rejects a changed body", async () => {
    const body = new TextEncoder().encode('{"action":"opened"}').buffer;
    const header = await signature('{"action":"opened"}', "test-secret");

    await expect(verifyGitHubSignature(body, header, "test-secret")).resolves.toBe(true);
    await expect(
      verifyGitHubSignature(new TextEncoder().encode("changed").buffer, header, "test-secret"),
    ).resolves.toBe(false);
  });

  it("queues a signed pull_request event", async () => {
    const payload = '{"action":"opened"}';
    const queued: GitHubQueueMessage[] = [];
    const request = new Request("https://worker.example/webhooks/github", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-1",
        "x-hub-signature-256": await signature(payload, "test-secret"),
      },
      body: payload,
    });

    const response = await handleWebhookRequest(request, {
      secret: "test-secret",
      enqueue: (message) => {
        queued.push(message);
        return Promise.resolve();
      },
    });

    expect(response.status).toBe(202);
    expect(queued).toEqual([
      {
        deliveryId: "delivery-1",
        eventName: "pull_request",
        payload: { action: "opened" },
      },
    ]);
  });

  it("rejects an invalid signature without queueing", async () => {
    let queued = false;
    const response = await handleWebhookRequest(
      new Request("https://worker.example/webhooks/github", {
        method: "POST",
        headers: {
          "x-github-event": "pull_request",
          "x-github-delivery": "delivery-2",
          "x-hub-signature-256": `sha256=${"0".repeat(64)}`,
        },
        body: "{}",
      }),
      {
        secret: "test-secret",
        enqueue: () => {
          queued = true;
          return Promise.resolve();
        },
      },
    );

    expect(response.status).toBe(401);
    expect(queued).toBe(false);
  });
});
