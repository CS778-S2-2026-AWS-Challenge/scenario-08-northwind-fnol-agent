import type { GitHubClient } from "./github";
import { connectionNodes, loadProjectConfiguration, updateProjectStatus } from "./project";
import type { ProjectEnvironment, ProjectStatus } from "./types";
import { optionalString, requireInteger, requireRecord, requireString } from "./validation";

interface ReconciliationCandidate {
  itemId: string;
  issueState: string;
  status: ProjectStatus;
  priority: number;
}

const PULL_REQUEST_FRAGMENT = `
  fragment PullRequestReconciliation on PullRequest {
    isDraft
    merged
    state
    closingIssuesReferences(first: 50) {
      nodes {
        number
        state
        projectItems(first: 20) { nodes { id project { id } } }
      }
    }
  }
`;

const OPEN_PULL_REQUESTS_QUERY = `
  ${PULL_REQUEST_FRAGMENT}
  query OpenPullRequests($owner: String!, $name: String!, $after: String) {
    repository(owner: $owner, name: $name) {
      pullRequests(first: 100, after: $after, states: [OPEN], orderBy: {field: UPDATED_AT, direction: DESC}) {
        nodes { ...PullRequestReconciliation }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
`;

const RECENT_CLOSED_PULL_REQUESTS_QUERY = `
  ${PULL_REQUEST_FRAGMENT}
  query RecentClosedPullRequests($owner: String!, $name: String!) {
    repository(owner: $owner, name: $name) {
      pullRequests(first: 100, states: [CLOSED, MERGED], orderBy: {field: UPDATED_AT, direction: DESC}) {
        nodes { ...PullRequestReconciliation }
      }
    }
  }
`;

function splitRepository(repository: string): { owner: string; repo: string } {
  const [owner, repo] = repository.split("/");
  if (!owner || !repo) throw new Error(`Invalid repository name: ${repository}`);
  return { owner, repo };
}

function projectItemId(issue: Record<string, unknown>, projectId: string): string | null {
  for (const item of connectionNodes(issue.projectItems, "reconciliation issue.projectItems")) {
    const project = requireRecord(item.project, "reconciliation project item.project");
    if (project.id === projectId) return requireString(item.id, "reconciliation project item.id");
  }
  return null;
}

function addCandidates(
  pullRequests: readonly Record<string, unknown>[],
  projectId: string,
  candidates: Map<string, ReconciliationCandidate>,
): void {
  for (const pullRequest of pullRequests) {
    const draft = pullRequest.isDraft === true;
    const merged = pullRequest.merged === true;
    const state = optionalString(pullRequest.state) ?? "";
    const status = reconciliationStatus({ draft, merged, state });
    const priority = status === "Done" ? 3 : status === "In review" ? 2 : 1;

    for (const issue of connectionNodes(
      pullRequest.closingIssuesReferences,
      "reconciliation pullRequest.closingIssuesReferences",
    )) {
      const itemId = projectItemId(issue, projectId);
      if (!itemId) continue;
      const issueNumber = String(requireInteger(issue.number, "reconciliation issue.number"));
      const issueState = requireString(issue.state, "reconciliation issue.state");
      const existing = candidates.get(issueNumber);
      if (!existing || priority > existing.priority) {
        candidates.set(issueNumber, { itemId, issueState, status, priority });
      }
    }
  }
}

export function reconciliationStatus(input: {
  draft: boolean;
  merged: boolean;
  state: string;
}): ProjectStatus {
  if (input.merged) return "Done";
  if (input.state === "OPEN" && !input.draft) return "In review";
  return "In progress";
}

async function openPullRequests(
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<Record<string, unknown>[]> {
  const { owner, repo } = splitRepository(env.TARGET_REPOSITORY);
  const pullRequests: Record<string, unknown>[] = [];
  let after: string | null = null;
  do {
    const data = await client.graphql(OPEN_PULL_REQUESTS_QUERY, { owner, name: repo, after });
    const repository = requireRecord(data.repository, "open PR reconciliation.repository");
    const connection = requireRecord(repository.pullRequests, "open PR reconciliation.pullRequests");
    pullRequests.push(...connectionNodes(connection, "open PR reconciliation.pullRequests"));
    const pageInfo = requireRecord(connection.pageInfo, "open PR reconciliation.pageInfo");
    after = pageInfo.hasNextPage === true
      ? requireString(pageInfo.endCursor, "open PR reconciliation.pageInfo.endCursor")
      : null;
  } while (after !== null);
  return pullRequests;
}

async function recentClosedPullRequests(
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<Record<string, unknown>[]> {
  const { owner, repo } = splitRepository(env.TARGET_REPOSITORY);
  const data = await client.graphql(RECENT_CLOSED_PULL_REQUESTS_QUERY, { owner, name: repo });
  const repository = requireRecord(data.repository, "closed PR reconciliation.repository");
  return connectionNodes(repository.pullRequests, "closed PR reconciliation.pullRequests");
}

export async function reconcilePullRequestStatuses(
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<void> {
  const project = await loadProjectConfiguration(client, env);
  const [open, closed] = await Promise.all([
    openPullRequests(client, env),
    recentClosedPullRequests(client, env),
  ]);
  const candidates = new Map<string, ReconciliationCandidate>();
  addCandidates([...open, ...closed], project.id, candidates);

  for (const [issueNumber, candidate] of candidates) {
    await updateProjectStatus(client, project, candidate.itemId, candidate.status);
    console.log(JSON.stringify({
      event: "kanban_reconciled",
      issueNumber,
      issueState: candidate.issueState,
      status: candidate.status,
    }));
  }
}
