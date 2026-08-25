import type { GitHubClient } from "./github";
import type { ProjectEnvironment, ProjectStatus } from "./types";
import { optionalRecord, requireArray, requireRecord, requireString } from "./validation";

interface SelectField {
  id: string;
  options: ReadonlyMap<string, string>;
}

export interface ProjectConfiguration {
  id: string;
  status: SelectField;
  tracking: SelectField;
  size: SelectField;
  estimateFieldId: string;
  startDateFieldId: string;
  targetDateFieldId: string;
}

const PROJECT_CONFIGURATION_QUERY = `
  query ProjectConfiguration($owner: String!, $number: Int!) {
    organization(login: $owner) {
      projectV2(number: $number) {
        id
        fields(first: 50) {
          nodes {
            ... on ProjectV2Field { id name }
            ... on ProjectV2SingleSelectField { id name options { id name } }
          }
        }
      }
    }
  }
`;

function fieldByName(fields: readonly Record<string, unknown>[], name: string): Record<string, unknown> {
  const matches = fields.filter((field) => field.name === name);
  if (matches.length !== 1) throw new Error(`Expected exactly one Project field named '${name}'.`);
  return matches[0] ?? {};
}

function selectField(fields: readonly Record<string, unknown>[], name: string): SelectField {
  const field = fieldByName(fields, name);
  const options = new Map<string, string>();
  for (const rawOption of requireArray(field.options, `Project field ${name}.options`)) {
    const option = requireRecord(rawOption, `Project field ${name} option`);
    options.set(
      requireString(option.name, `Project field ${name} option.name`),
      requireString(option.id, `Project field ${name} option.id`),
    );
  }
  return { id: requireString(field.id, `Project field ${name}.id`), options };
}

function ordinaryFieldId(fields: readonly Record<string, unknown>[], name: string): string {
  return requireString(fieldByName(fields, name).id, `Project field ${name}.id`);
}

export async function loadProjectConfiguration(
  client: GitHubClient,
  env: ProjectEnvironment,
): Promise<ProjectConfiguration> {
  const data = await client.graphql(PROJECT_CONFIGURATION_QUERY, {
    owner: env.PROJECT_OWNER,
    number: Number(env.PROJECT_NUMBER),
  });
  const organization = requireRecord(data.organization, "Project configuration.organization");
  const project = requireRecord(organization.projectV2, "Project configuration.projectV2");
  const fieldsConnection = requireRecord(project.fields, "Project configuration.fields");
  const fields = requireArray(fieldsConnection.nodes, "Project configuration.fields.nodes").map(
    (field, index) => requireRecord(field, `Project configuration field ${String(index)}`),
  );
  const id = requireString(project.id, "Project configuration.id");
  if (id !== env.PROJECT_ID) {
    throw new Error(`Project ${env.PROJECT_NUMBER} resolved to ${id}, not configured ID ${env.PROJECT_ID}.`);
  }

  const configuration: ProjectConfiguration = {
    id,
    status: selectField(fields, "Status"),
    tracking: selectField(fields, env.TRACKING_FIELD),
    size: selectField(fields, "Size"),
    estimateFieldId: ordinaryFieldId(fields, "Estimate"),
    startDateFieldId: ordinaryFieldId(fields, "Start date"),
    targetDateFieldId: ordinaryFieldId(fields, "Target date"),
  };

  for (const option of [env.REPOSITORY_TRACKING_OPTION, env.DELIVERY_TRACKING_OPTION]) {
    if (!configuration.tracking.options.has(option)) {
      throw new Error(`Tracking option '${option}' is missing.`);
    }
  }
  return configuration;
}

const UPDATE_SINGLE_SELECT_MUTATION = `
  mutation UpdateSingleSelect(
    $projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!
  ) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $projectId,
      itemId: $itemId,
      fieldId: $fieldId,
      value: { singleSelectOptionId: $optionId }
    }) { projectV2Item { id } }
  }
`;

const UPDATE_NUMBER_MUTATION = `
  mutation UpdateNumber($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: Float!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $projectId,
      itemId: $itemId,
      fieldId: $fieldId,
      value: { number: $value }
    }) { projectV2Item { id } }
  }
`;

const UPDATE_DATE_MUTATION = `
  mutation UpdateDate($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: Date!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $projectId,
      itemId: $itemId,
      fieldId: $fieldId,
      value: { date: $value }
    }) { projectV2Item { id } }
  }
`;

export async function updateSingleSelect(
  client: GitHubClient,
  project: ProjectConfiguration,
  itemId: string,
  field: SelectField,
  optionName: string,
): Promise<void> {
  const optionId = field.options.get(optionName);
  if (!optionId) throw new Error(`Project option '${optionName}' is missing.`);
  await client.graphql(UPDATE_SINGLE_SELECT_MUTATION, {
    projectId: project.id,
    itemId,
    fieldId: field.id,
    optionId,
  });
}

export async function updateProjectStatus(
  client: GitHubClient,
  project: ProjectConfiguration,
  itemId: string,
  status: ProjectStatus,
): Promise<void> {
  await updateSingleSelect(client, project, itemId, project.status, status);
}

export async function updateProjectNumber(
  client: GitHubClient,
  projectId: string,
  itemId: string,
  fieldId: string,
  value: number,
): Promise<void> {
  await client.graphql(UPDATE_NUMBER_MUTATION, { projectId, itemId, fieldId, value });
}

export async function updateProjectDate(
  client: GitHubClient,
  projectId: string,
  itemId: string,
  fieldId: string,
  value: string,
): Promise<void> {
  await client.graphql(UPDATE_DATE_MUTATION, { projectId, itemId, fieldId, value });
}

export function connectionNodes(value: unknown, path: string): Record<string, unknown>[] {
  const connection = requireRecord(value, path);
  return requireArray(connection.nodes, `${path}.nodes`)
    .map((node) => optionalRecord(node))
    .filter((node): node is Record<string, unknown> => node !== null);
}
