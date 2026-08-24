import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const DEFAULT_REPOSITORY =
  "CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent";
const DEFAULT_PROJECT_NUMBER = 12;
const DEFAULT_TIMEOUT_SECONDS = 60;
const DEFAULT_INTERVAL_SECONDS = 2;

function positiveInteger(value, name) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer.`);
  }
  return parsed;
}

export function parseArguments(argv, environment = process.env) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name?.startsWith("--") || value === undefined) {
      throw new Error("Arguments must use --name value pairs.");
    }
    values.set(name, value);
  }

  const issue = values.get("--issue");
  const expected = values.get("--expected")?.trim();
  if (!issue) throw new Error("--issue is required.");
  if (!expected) throw new Error("--expected is required.");

  const repository = values.get("--repository") ?? environment.GITHUB_REPOSITORY ?? DEFAULT_REPOSITORY;
  const [owner, repo, ...extra] = repository.split("/");
  if (!owner || !repo || extra.length > 0) {
    throw new Error("--repository must use owner/name format.");
  }

  return {
    token: environment.GITHUB_TOKEN,
    owner,
    repo,
    issueNumber: positiveInteger(issue, "--issue"),
    expected,
    projectNumber: positiveInteger(
      values.get("--project") ?? String(DEFAULT_PROJECT_NUMBER),
      "--project",
    ),
    timeoutMs:
      positiveInteger(
        values.get("--timeout-seconds") ?? String(DEFAULT_TIMEOUT_SECONDS),
        "--timeout-seconds",
      ) * 1000,
    intervalMs:
      positiveInteger(
        values.get("--interval-seconds") ?? String(DEFAULT_INTERVAL_SECONDS),
        "--interval-seconds",
      ) * 1000,
  };
}

export function extractProjectStatus(payload, projectNumber) {
  const nodes = payload?.data?.repository?.issue?.projectItems?.nodes;
  if (!Array.isArray(nodes)) {
    throw new Error("GitHub response is missing Issue Project items.");
  }
  const matches = nodes.filter((node) => node?.project?.number === projectNumber);
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one Project ${projectNumber} item for the Issue.`);
  }
  const status = matches[0]?.fieldValueByName?.name;
  if (typeof status !== "string" || status.length === 0) {
    throw new Error(`Project ${projectNumber} item has no Status value.`);
  }
  return status;
}

export async function readProjectStatus({ token, owner, repo, issueNumber, projectNumber, fetcher = fetch }) {
  if (!token) throw new Error("GITHUB_TOKEN is required in the process environment.");
  const response = await fetcher("https://api.github.com/graphql", {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "northwind-kanban-verifier",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({
      query: `
        query IssueProjectStatus($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            issue(number: $number) {
              projectItems(first: 20) {
                nodes {
                  project { number }
                  fieldValueByName(name: "Status") {
                    ... on ProjectV2ItemFieldSingleSelectValue { name }
                  }
                }
              }
            }
          }
        }
      `,
      variables: { owner, repo, number: issueNumber },
    }),
  });
  const payload = await response.json();
  if (!response.ok || (Array.isArray(payload?.errors) && payload.errors.length > 0)) {
    throw new Error(`GitHub GraphQL request failed with HTTP ${response.status}.`);
  }
  return extractProjectStatus(payload, projectNumber);
}

export async function waitForExpectedStatus({
  expected,
  timeoutMs,
  intervalMs,
  readStatus,
  now = Date.now,
  sleep = (milliseconds) => new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds)),
}) {
  const deadline = now() + timeoutMs;
  let attempts = 0;
  let actual;
  do {
    attempts += 1;
    actual = await readStatus();
    if (actual === expected) return { actual, attempts };
    if (now() >= deadline) break;
    await sleep(intervalMs);
  } while (now() <= deadline);
  throw new Error(`Timed out waiting for '${expected}'; current status is '${actual}'.`);
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const result = await waitForExpectedStatus({
    expected: options.expected,
    timeoutMs: options.timeoutMs,
    intervalMs: options.intervalMs,
    readStatus: () => readProjectStatus(options),
  });
  console.log(JSON.stringify({
    result: "PASS",
    issue: options.issueNumber,
    project: options.projectNumber,
    expected: options.expected,
    actual: result.actual,
    attempts: result.attempts,
  }));
}

const entryUrl = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === entryUrl) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
