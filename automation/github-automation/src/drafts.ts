import type { GitHubClient } from "./github";
import {
  connectionNodes,
  loadProjectConfiguration,
  updateProjectDate,
  updateProjectNumber,
  updateSingleSelect,
} from "./project";
import type { ProjectEnvironment } from "./types";
import {
  optionalRecord,
  optionalString,
  requireArray,
  requireInteger,
  requireRecord,
  requireString,
} from "./validation";

export interface ProjectItemSnapshot {
  id: string;
  contentId: string;
  contentType: "DraftIssue" | "Issue" | "Other";
  issueNumber: number | null;
  title: string;
  body: string;
  assignees: string[];
  status: string | null;
  tracking: string | null;
  size: string | null;
  estimate: number | null;
  startDate: string | null;
  targetDate: string | null;
}

const PROJECT_ITEM_FRAGMENT = `
  fragment ProjectItemFields on ProjectV2Item {
    id
    content {
      __typename
      ... on DraftIssue {
        id
        title
        body
        assignees(first: 20) { nodes { login } }
      }
      ... on Issue {
        id
        number
        title
        body
        assignees(first: 20) { nodes { login } }
      }
    }
    fieldValues(first: 30) {
      nodes {
        ... on ProjectV2ItemFieldSingleSelectValue {
          name
          field { ... on ProjectV2FieldCommon { name } }
        }
        ... on ProjectV2ItemFieldNumberValue {
          number
          field { ... on ProjectV2FieldCommon { name } }
        }
        ... on ProjectV2ItemFieldDateValue {
          date
          field { ... on ProjectV2FieldCommon { name } }
        }
      }
    }
  }
`;

const PROJECT_ITEMS_QUERY = `
  ${PROJECT_ITEM_FRAGMENT}
  query ProjectItems($owner: String!, $number: Int!, $after: String) {
    organization(login: $owner) {
      projectV2(number: $number) {
        items(first: 100, after: $after) {
          nodes { ...ProjectItemFields }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
`;

const PROJECT_ITEM_QUERY = `
  ${PROJECT_ITEM_FRAGMENT}
  query ProjectItem($itemId: ID!) {
    node(id: $itemId) { ...ProjectItemFields }
  }
`;

const REPOSITORY_ID_QUERY = `
  query RepositoryId($owner: String!, $name: String!) {
    repository(owner: $owner, name: $name) { id }
  }
`;

const UPDATE_DRAFT_MUTATION = `
  mutation UpdateDraft($draftIssueId: ID!, $body: String!) {
    updateProjectV2DraftIssue(input: { draftIssueId: $draftIssueId, body: $body }) {
      draftIssue { id }
    }
  }
`;

const CONVERT_DRAFT_MUTATION = `
  mutation ConvertDraft($itemId: ID!, $repositoryId: ID!) {
    convertProjectV2DraftIssueItemToIssue(input: {
      itemId: $itemId,
      repositoryId: $repositoryId
    }) {
      item { id content { ... on Issue { number url } } }
    }
  }
`;

function fieldValues(item: Record<string, unknown>): Map<string, string | number> {
  const values = new Map<string, string | number>();
  for (const value of connectionNodes(item.fieldValues, "Project item.fieldValues")) {
    const field = optionalRecord(value.field);
    const fieldName = field ? optionalString(field.name) : null;
    if (!fieldName) continue;
    if (typeof value.name === "string") values.set(fieldName, value.name);
    else if (typeof value.number === "number") values.set(fieldName, value.number);
    else if (typeof value.date === "string") values.set(fieldName, value.date);
  }
  return values;
}

function assigneeLogins(content: Record<string, unknown>): string[] {
  const assignees = optionalRecord(content.assignees);
  if (!assignees) return [];
  return connectionNodes(assignees, "Project item.assignees")
    .map((node) => optionalString(node.login))
    .filter((login): login is string => login !== null)
    .sort();
}

export function parseProjectItem(value: unknown): ProjectItemSnapshot {
  const item = requireRecord(value, "Project item");
  const content = requireRecord(item.content, "Project item.content");
  const typename = requireString(content.__typename, "Project item.content.__typename");
  const values = fieldValues(item);
  const numberValue = content.number;

  return {
    id: requireString(item.id, "Project item.id"),
    contentId: requireString(content.id, "Project item.content.id"),
    contentType: typename === "DraftIssue" ? "DraftIssue" : typename === "Issue" ? "Issue" : "Other",
    issueNumber: typeof numberValue === "number" && Number.isInteger(numberValue) ? numberValue : null,
    title: optionalString(content.title) ?? "",
    body: optionalString(content.body) ?? "",
    assignees: assigneeLogins(content),
    status: typeof values.get("Status") === "string" ? String(values.get("Status")) : null,
    tracking: typeof values.get("Tracking") === "string" ? String(values.get("Tracking")) : null,
    size: typeof values.get("Size") === "string" ? String(values.get("Size")) : null,
    estimate: typeof values.get("Estimate") === "number" ? Number(values.get("Estimate")) : null,
    startDate: typeof values.get("Start date") === "string" ? String(values.get("Start date")) : null,
    targetDate: typeof values.get("Target date") === "string" ? String(values.get("Target date")) : null,
  };
}

async function loadProjectItems(
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<ProjectItemSnapshot[]> {
  const items: ProjectItemSnapshot[] = [];
  let after: string | null = null;
  do {
    const data = await client.graphql(PROJECT_ITEMS_QUERY, {
      owner: env.PROJECT_OWNER,
      number: Number(env.PROJECT_NUMBER),
      after,
    });
    const organization = requireRecord(data.organization, "Project items.organization");
    const project = requireRecord(organization.projectV2, "Project items.projectV2");
    const connection = requireRecord(project.items, "Project items.connection");
    for (const node of requireArray(connection.nodes, "Project items.nodes")) {
      if (node !== null) items.push(parseProjectItem(node));
    }
    const pageInfo = requireRecord(connection.pageInfo, "Project items.pageInfo");
    const hasNextPage = pageInfo.hasNextPage === true;
    after = hasNextPage ? requireString(pageInfo.endCursor, "Project items.pageInfo.endCursor") : null;
  } while (after !== null);
  return items;
}

async function reloadProjectItem(client: GitHubClient, itemId: string): Promise<ProjectItemSnapshot | null> {
  const data = await client.graphql(PROJECT_ITEM_QUERY, { itemId });
  return data.node === null ? null : parseProjectItem(data.node);
}

function section(body: string, heading: string): string | null {
  const match = new RegExp(
    `^## ${heading}\\s*$\\r?\\n([\\s\\S]*?)(?=^## |$(?![\\s\\S]))`,
    "im",
  ).exec(body);
  return match?.[1]?.trim() ?? null;
}

function dependencyIds(body: string): { ids: string[]; errors: string[] } {
  const dependencies = section(body, "Dependencies");
  if (dependencies === null) return { ids: [], errors: ["Dependencies section"] };
  const ids = [...dependencies.matchAll(/(?:AM|PM|D\d+)-[A-Z]\d{2}/g)].map((match) => match[0]);
  const uniqueIds = [...new Set(ids)].sort();
  const errors: string[] = [];
  if (/\bthrough\b/i.test(dependencies)) errors.push("explicit dependency IDs instead of a range");
  if (uniqueIds.length === 0 && !/^\s*-\s*None\.?\s*$/im.test(dependencies)) {
    errors.push("Dependencies entries or '- None'");
  }
  return { ids: uniqueIds, errors };
}

export function validateReadyDraft(
  item: ProjectItemSnapshot,
  projectItems: readonly ProjectItemSnapshot[],
  repositoryTrackingOption: string,
): string[] {
  const errors: string[] = [];
  if (item.assignees.length < 1) errors.push("at least one Assignee");
  if (item.estimate === null) errors.push("Estimate");
  if (item.size === null) errors.push("Size");
  if (item.tracking !== repositoryTrackingOption) errors.push(`Tracking ${repositoryTrackingOption}`);
  if (item.startDate === null) errors.push("Start date");
  if (item.targetDate === null) errors.push("Target date");
  if (section(item.body, "Acceptance") === null) errors.push("Acceptance section");

  const expectedSizes = new Map<number, string>([
    [1, "XS"],
    [2, "S"],
    [3, "M"],
    [4, "L"],
    [5, "XL"],
    [6, "XL"],
  ]);
  if (item.estimate !== null) {
    const expectedSize = expectedSizes.get(item.estimate);
    if (!expectedSize) errors.push("supported Estimate from 1 to 6 hours");
    else if (item.size !== expectedSize) {
      errors.push(`Size ${expectedSize} for Estimate ${String(item.estimate)}h`);
    }
  }

  const dependencies = dependencyIds(item.body);
  errors.push(...dependencies.errors);
  for (const dependencyId of dependencies.ids) {
    const matches = projectItems.filter(
      (candidate) => candidate.title === dependencyId || candidate.title.startsWith(`${dependencyId} `),
    );
    if (matches.length !== 1) errors.push(`one Project card for dependency ${dependencyId}`);
    else if (matches[0]?.status !== "Done") errors.push(`dependency ${dependencyId} to be Done`);
  }
  return errors;
}

export function isAucklandWorkingTime(date: Date): boolean {
  const parts = new Intl.DateTimeFormat("en-NZ", {
    timeZone: "Pacific/Auckland",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const value = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((part) => part.type === type)?.value ?? "";
  const weekday = value("weekday");
  const time = Number(`${value("hour")}${value("minute")}`);
  return !["Sat", "Sun"].includes(weekday) && time >= 1000 && time < 1800;
}

function withPlannedWorkWindow(item: ProjectItemSnapshot): { body: string; changed: boolean } {
  if (!item.startDate) throw new Error(`${item.title} has no Start date.`);
  const headings = item.body.match(/^## Planned work window\s*$/gim) ?? [];
  if (headings.length > 1) throw new Error(`${item.title} has duplicate Planned work window sections.`);
  const expectedDate = new RegExp(`^- Date: ${item.startDate.replaceAll("-", "\\-")}\\s*$`, "m");
  const expectedTime = /^- Time: 10:00-18:00 Pacific\/Auckland\s*$/m;
  if (headings.length === 1) {
    if (!expectedDate.test(item.body) || !expectedTime.test(item.body)) {
      throw new Error(`${item.title} has a Planned work window that does not match its Start date.`);
    }
    return { body: item.body, changed: false };
  }
  const body = `${item.body.trimEnd()}\n\n## Planned work window\n- Date: ${item.startDate}\n- Time: 10:00-18:00 Pacific/Auckland`;
  return { body, changed: true };
}

async function repositoryId(client: GitHubClient, repository: string): Promise<string> {
  const [owner, name] = repository.split("/");
  if (!owner || !name) throw new Error(`Invalid repository name: ${repository}`);
  const data = await client.graphql(REPOSITORY_ID_QUERY, { owner, name });
  const repositoryNode = requireRecord(data.repository, "repository ID response.repository");
  return requireString(repositoryNode.id, "repository ID response.repository.id");
}

async function convertDraft(
  client: GitHubClient,
  env: ProjectEnvironment,
  item: ProjectItemSnapshot,
  allItems: readonly ProjectItemSnapshot[],
): Promise<void> {
  const current = await reloadProjectItem(client, item.id);
  if (current?.contentType !== "DraftIssue") return;
  if (current.status !== "Ready" || current.tracking !== env.REPOSITORY_TRACKING_OPTION) return;
  const errors = validateReadyDraft(current, allItems, env.REPOSITORY_TRACKING_OPTION);
  if (errors.length > 0) throw new Error(`${current.title} is no longer valid: ${errors.join(", ")}.`);

  const workWindow = withPlannedWorkWindow(current);
  if (workWindow.changed) {
    await client.graphql(UPDATE_DRAFT_MUTATION, {
      draftIssueId: current.contentId,
      body: workWindow.body,
    });
  }

  const targetRepositoryId = await repositoryId(client, env.TARGET_REPOSITORY);
  const conversion = await client.graphql(CONVERT_DRAFT_MUTATION, {
    itemId: current.id,
    repositoryId: targetRepositoryId,
  });
  const converted = requireRecord(conversion.convertProjectV2DraftIssueItemToIssue, "draft conversion");
  const convertedItem = requireRecord(converted.item, "draft conversion.item");
  const issue = requireRecord(convertedItem.content, "draft conversion.item.content");
  const issueNumber = requireInteger(issue.number, "draft conversion issue.number");

  const project = await loadProjectConfiguration(client, env);
  await updateSingleSelect(client, project, current.id, project.tracking, env.REPOSITORY_TRACKING_OPTION);
  if (!current.size) throw new Error(`${current.title} has no Size after validation.`);
  await updateSingleSelect(client, project, current.id, project.size, current.size);
  if (current.estimate === null || !current.startDate || !current.targetDate) {
    throw new Error(`${current.title} lost required fields after validation.`);
  }
  await updateProjectNumber(client, project.id, current.id, project.estimateFieldId, current.estimate);
  await updateProjectDate(client, project.id, current.id, project.startDateFieldId, current.startDate);
  await updateProjectDate(client, project.id, current.id, project.targetDateFieldId, current.targetDate);

  const verified = await reloadProjectItem(client, current.id);
  if (
    verified?.contentType !== "Issue" ||
    verified.issueNumber !== issueNumber ||
    verified.tracking !== current.tracking ||
    verified.size !== current.size ||
    verified.estimate !== current.estimate ||
    verified.startDate !== current.startDate ||
    verified.targetDate !== current.targetDate ||
    verified.assignees.join(",") !== current.assignees.join(",")
  ) {
    throw new Error(
      `Converted Issue #${String(issueNumber)} did not preserve its Project fields and assignees.`,
    );
  }

  console.log(JSON.stringify({ event: "draft_converted", issueNumber, itemId: current.id }));
}

export async function synchronizeReadyDrafts(
  client: GitHubClient,
  env: ProjectEnvironment,
  now: Date,
): Promise<void> {
  if (!isAucklandWorkingTime(now)) {
    console.log(JSON.stringify({ event: "draft_sync_skipped", reason: "outside_auckland_work_window" }));
    return;
  }

  const items = await loadProjectItems(client, env);
  const candidates = items.filter(
    (item) =>
      item.contentType === "DraftIssue" &&
      item.status === "Ready" &&
      item.tracking === env.REPOSITORY_TRACKING_OPTION,
  );
  const invalid: string[] = [];
  for (const candidate of candidates) {
    const errors = validateReadyDraft(candidate, items, env.REPOSITORY_TRACKING_OPTION);
    if (errors.length > 0) {
      invalid.push(`${candidate.title}: ${errors.join(", ")}`);
      console.warn(JSON.stringify({ event: "draft_not_converted", title: candidate.title, errors }));
      continue;
    }
    await convertDraft(client, env, candidate, items);
  }
  if (invalid.length > 0) {
    throw new Error(`Ready DraftIssue validation failed: ${invalid.join("; ")}`);
  }
}
