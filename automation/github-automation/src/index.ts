import { synchronizeReadyDrafts } from "./drafts";
import { GitHubClient } from "./github";
import { ISSUE_POLICY_ACTIONS, evaluateIssuePolicy } from "./issue-policy";
import { syncPullRequestKanban } from "./kanban";
import { evaluatePullRequestPolicy } from "./pr-policy";
import { reconcilePullRequestStatuses } from "./reconcile";
import type { GitHubQueueMessage, WorkerEnv } from "./types";
import { parseIssueEvent, parsePullRequestEvent } from "./validation";
import { handleWebhook } from "./webhook";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function processIssueEvent(message: GitHubQueueMessage, env: WorkerEnv): Promise<void> {
  const event = parseIssueEvent(message.payload);
  if (event.repository.fullName.toLowerCase() !== env.TARGET_REPOSITORY.toLowerCase()) {
    console.warn(JSON.stringify({
      event: "repository_ignored",
      deliveryId: message.deliveryId,
      repository: event.repository.fullName,
    }));
    return;
  }
  if (!ISSUE_POLICY_ACTIONS.includes(event.action)) return;

  const client = new GitHubClient(env.GITHUB_TOKEN);
  const policy = await evaluateIssuePolicy(event, client);
  console.log(JSON.stringify({
    event: "issue_processed",
    deliveryId: message.deliveryId,
    issue: event.issue.number,
    policyErrors: policy.errors.length,
  }));
}

async function processGitHubEvent(message: GitHubQueueMessage, env: WorkerEnv): Promise<void> {
  if (message.eventName === "issues") {
    await processIssueEvent(message, env);
    return;
  }
  if (message.eventName !== "pull_request") return;
  const event = parsePullRequestEvent(message.payload);
  if (event.repository.fullName.toLowerCase() !== env.TARGET_REPOSITORY.toLowerCase()) {
    console.warn(JSON.stringify({
      event: "repository_ignored",
      deliveryId: message.deliveryId,
      repository: event.repository.fullName,
    }));
    return;
  }

  const client = new GitHubClient(env.GITHUB_TOKEN);
  const policyActions = [
    "converted_to_draft",
    "edited",
    "opened",
    "ready_for_review",
    "reopened",
    "synchronize",
  ];
  const policy = policyActions.includes(event.action)
    ? await evaluatePullRequestPolicy(event, client)
    : { errors: [] };
  await syncPullRequestKanban(event, client, env);
  console.log(JSON.stringify({
    event: "pull_request_processed",
    deliveryId: message.deliveryId,
    pullRequest: event.pullRequest.number,
    policyErrors: policy.errors.length,
  }));
}

async function processQueueMessage(
  message: Message<GitHubQueueMessage>,
  env: WorkerEnv,
): Promise<void> {
  try {
    await processGitHubEvent(message.body, env);
    message.ack();
  } catch (error) {
    console.error(JSON.stringify({
      event: "github_event_failed",
      deliveryId: message.body.deliveryId,
      attempt: message.attempts,
      error: errorMessage(error),
    }));
    message.retry({ delaySeconds: Math.min(300, 30 * message.attempts) });
  }
}

export default {
  async fetch(request, env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ status: "ok" });
    }
    if (request.method === "POST" && url.pathname === "/webhooks/github") {
      try {
        return await handleWebhook(request, env);
      } catch (error) {
        console.error(JSON.stringify({
          event: "webhook_failed",
          error: errorMessage(error),
        }));
        return Response.json({ error: "Webhook processing failed." }, { status: 500 });
      }
    }
    return Response.json({ error: "Not found." }, { status: 404 });
  },

  async queue(batch, env): Promise<void> {
    await Promise.all(batch.messages.map((message) => processQueueMessage(message, env)));
  },

  async scheduled(controller, env): Promise<void> {
    const client = new GitHubClient(env.GITHUB_TOKEN);
    await synchronizeReadyDrafts(client, env, new Date(controller.scheduledTime));
    await reconcilePullRequestStatuses(client, env);
  },
} satisfies ExportedHandler<WorkerEnv, GitHubQueueMessage>;
