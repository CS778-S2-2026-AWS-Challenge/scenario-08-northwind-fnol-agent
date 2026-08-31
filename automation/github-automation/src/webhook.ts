import type { GitHubQueueMessage, WorkerEnv } from "./types";

const MAX_WEBHOOK_BYTES = 2 * 1024 * 1024;
const encoder = new TextEncoder();

function hexToBytes(hex: string): Uint8Array<ArrayBuffer> | null {
  if (!/^[0-9a-f]+$/i.test(hex) || hex.length % 2 !== 0) return null;
  const bytes = new Uint8Array(new ArrayBuffer(hex.length / 2));
  for (let index = 0; index < bytes.length; index += 1) {
    const byte = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
    if (!Number.isFinite(byte)) return null;
    bytes[index] = byte;
  }
  return bytes;
}

export async function verifyGitHubSignature(
  body: ArrayBuffer,
  signatureHeader: string,
  secret: string,
): Promise<boolean> {
  if (!signatureHeader.startsWith("sha256=")) return false;
  const signature = hexToBytes(signatureHeader.slice("sha256=".length));
  if (signature?.byteLength !== 32) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify("HMAC", key, signature, body);
}

function jsonResponse(body: Readonly<Record<string, unknown>>, status = 200): Response {
  return Response.json(body, { status });
}

export interface WebhookDependencies {
  secret: string;
  enqueue(message: GitHubQueueMessage): Promise<void>;
}

export async function handleWebhookRequest(
  request: Request,
  dependencies: WebhookDependencies,
): Promise<Response> {
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_WEBHOOK_BYTES) {
    return jsonResponse({ error: "Webhook payload is too large." }, 413);
  }

  const eventName = request.headers.get("x-github-event");
  const deliveryId = request.headers.get("x-github-delivery");
  const signature = request.headers.get("x-hub-signature-256");
  if (!eventName || !deliveryId || !signature) {
    return jsonResponse({ error: "Required GitHub webhook headers are missing." }, 400);
  }

  const body = await request.arrayBuffer();
  if (body.byteLength > MAX_WEBHOOK_BYTES) {
    return jsonResponse({ error: "Webhook payload is too large." }, 413);
  }
  if (!(await verifyGitHubSignature(body, signature, dependencies.secret))) {
    return jsonResponse({ error: "Webhook signature is invalid." }, 401);
  }

  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(body)) as unknown;
  } catch {
    return jsonResponse({ error: "Webhook payload is not valid JSON." }, 400);
  }

  if (eventName === "ping") {
    return jsonResponse({ status: "ok" });
  }
  if (eventName !== "pull_request" && eventName !== "issues") {
    return jsonResponse({ status: "ignored", event: eventName }, 202);
  }

  const message: GitHubQueueMessage = { deliveryId, eventName, payload };
  await dependencies.enqueue(message);
  return jsonResponse({ status: "accepted", deliveryId }, 202);
}

export async function handleWebhook(request: Request, env: WorkerEnv): Promise<Response> {
  return handleWebhookRequest(request, {
    secret: env.GITHUB_WEBHOOK_SECRET,
    enqueue: async (message) => {
      await env.GITHUB_EVENTS.send(message, { contentType: "json" });
    },
  });
}
