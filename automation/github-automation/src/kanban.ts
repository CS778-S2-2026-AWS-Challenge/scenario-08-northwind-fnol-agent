import type { GitHubClient } from "./github";
import { connectionNodes, loadProjectConfiguration, updateProjectStatus } from "./project";
import type { ProjectEnvironment, ProjectStatus, PullRequestEvent } from "./types";
import { requireInteger, requireRecord, requireString } from "./validation";

interface LinkedProjectItem {
  issueNumber: number;
  issueState: string;
  issueUrl: string;
  itemId: string;
}

const CLOSING_ISSUES_QUERY = `
  query ClosingIssues($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        closingIssuesReferences(first: 50) {
          nodes {
            number
            state
            url
            projectItems(first: 20) { nodes { id project { id } } }
          }
        }
      }
    }
  }
`;

const ISSUE_PROJECT_ITEM_QUERY = `
  query IssueProjectItem($owner: String!, $name: String!, $number: Int!) {
    repository(owner: $owner, name: $name) {
      issue(number: $number) {
        number
        state
        url
        projectItems(first: 20) { nodes { id project { id } } }
      }
    }
  }
`;

function splitRepository(repository: string): { owner: string; repo: string } {
  const [owner, repo, ...extra] = repository.split("/");
  if (!owner || !repo || extra.length > 0) throw new Error(`Invalid repository name: ${repository}`);
  return { owner, repo };
}

export function statusForPullRequest(event: PullRequestEvent): ProjectStatus | null {
  switch (event.action) {
    case "closed":
      // Closing a PR without merging does not prove that work is in progress.
      // Preserve the card's current planning status until another active signal.
      return event.pullRequest.merged ? "Done" : null;
    case "converted_to_draft":
      return "In progress";
    case "ready_for_review":
      return "In review";
    case "edited":
    case "opened":
    case "reopened":
    case "synchronize":
      return event.pullRequest.draft ? "In progress" : "In review";
    default:
      return null;
  }
}

export function closingIssueNumbers(body: string, targetRepository: string): number[] {
  const pattern = /\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\s*:?\s+(#\d+|[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+#\d+|https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/issues\/\d+)/gi;
  const expected = targetRepository.toLowerCase();
  const numbers = new Set<number>();

  for (const match of body.matchAll(pattern)) {
    const reference = match[1];
    if (!reference) continue;
    if (reference.startsWith("#")) {
      numbers.add(Number(reference.slice(1)));
      continue;
    }
    if (reference.toLowerCase().startsWith("https://")) {
      const parts = reference.split("/");
      if (`${String(parts[3])}/${String(parts[4])}`.toLowerCase() === expected) {
        numbers.add(Number(parts.at(-1)));
      }
      continue;
    }
    const separator = reference.lastIndexOf("#");
    if (separator > 0 && reference.slice(0, separator).toLowerCase() === expected) {
      numbers.add(Number(reference.slice(separator + 1)));
    }
  }
  return [...numbers].sort((left, right) => left - right);
}

function parseIssueNode(issue: Record<string, unknown>, projectId: string): LinkedProjectItem | null {
  const projectItems = connectionNodes(issue.projectItems, "issue.projectItems");
  const projectItem = projectItems.find((item) => {
    const project = requireRecord(item.project, "issue.projectItems.project");
    return project.id === projectId;
  });
  if (!projectItem) return null;
  return {
    issueNumber: requireInteger(issue.number, "issue.number"),
    issueState: requireString(issue.state, "issue.state"),
    issueUrl: requireString(issue.url, "issue.url"),
    itemId: requireString(projectItem.id, "issue.projectItem.id"),
  };
}

async function currentLinkedItems(
  event: PullRequestEvent,
  client: GitHubClient,
  projectId: string,
): Promise<LinkedProjectItem[]> {
  const { owner, repo } = splitRepository(event.repository.fullName);
  const data = await client.graphql(CLOSING_ISSUES_QUERY, {
    owner,
    name: repo,
    number: event.pullRequest.number,
  });
  const repository = requireRecord(data.repository, "closing issues.repository");
  const pullRequest = requireRecord(repository.pullRequest, "closing issues.pullRequest");
  return connectionNodes(pullRequest.closingIssuesReferences, "closing issues.references")
    .map((issue) => parseIssueNode(issue, projectId))
    .filter((item): item is LinkedProjectItem => item !== null);
}

async function issueProjectItem(
  issueNumber: number,
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<LinkedProjectItem | null> {
  const { owner, repo } = splitRepository(env.TARGET_REPOSITORY);
  const data = await client.graphql(ISSUE_PROJECT_ITEM_QUERY, {
    owner,
    name: repo,
    number: issueNumber,
  });
  const repository = requireRecord(data.repository, "issue lookup.repository");
  const issue = requireRecord(repository.issue, "issue lookup.issue");
  return parseIssueNode(issue, env.PROJECT_ID);
}

export async function syncPullRequestKanban(
  event: PullRequestEvent,
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<void> {
  const targetStatus = statusForPullRequest(event);
  if (targetStatus === null) return;

  const project = await loadProjectConfiguration(client, env);
  const linkedItems = await currentLinkedItems(event, client, project.id);
  for (const linkedItem of linkedItems) {
    await updateProjectStatus(client, project, linkedItem.itemId, targetStatus);
  }

  if (event.action !== "edited" || event.previousBody === null) return;
  const currentNumbers = new Set(linkedItems.map((item) => item.issueNumber));
  const removedNumbers = closingIssueNumbers(event.previousBody, env.TARGET_REPOSITORY).filter(
    (number) => !currentNumbers.has(number),
  );
  for (const issueNumber of removedNumbers) {
    const item = await issueProjectItem(issueNumber, client, env);
    if (item === null) continue;
    await updateProjectStatus(
      client,
      project,
      item.itemId,
      item.issueState === "CLOSED" ? "Done" : "In progress",
    );
  }
}
