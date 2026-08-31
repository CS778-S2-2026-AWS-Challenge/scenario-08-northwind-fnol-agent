const policy = require('../.github/scripts/pr_policy.cjs');

const DEFAULT_API_URL = 'https://api.github.com';

function parsePullRequestNumber(value) {
  if (!value) return null;
  const match = value.split(',')[0].trim().match(/\/pull\/(\d+)(?:\/|$)/);
  return match ? Number(match[1]) : null;
}

function pullRequestNumbers(value) {
  if (!value) return [];
  return [
    ...new Set(
      value
        .split(',')
        .map((pullRequest) => parsePullRequestNumber(pullRequest.trim()))
        .filter((number) => number !== null),
    ),
  ];
}

async function githubRequest({ apiUrl, token, path, fetchImpl = fetch }) {
  const response = await fetchImpl(`${apiUrl}${path}`, {
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'northwind-circleci-pr-policy',
    },
  });
  if (!response.ok) {
    const error = new Error(`GitHub API request failed with HTTP ${response.status}.`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function findPullRequestNumber({
  apiUrl,
  token,
  owner,
  repo,
  sha,
  pullRequestUrls,
  fetchImpl = fetch,
}) {
  const directNumbers = pullRequestNumbers(pullRequestUrls);
  if (directNumbers.length > 1) {
    throw new Error('CircleCI supplied multiple pull requests; PR policy cannot choose one safely.');
  }
  if (directNumbers.length === 1) return directNumbers[0];

  const candidates = await githubRequest({
    apiUrl,
    token,
    path: `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/commits/${encodeURIComponent(sha)}/pulls`,
    fetchImpl,
  });
  const matching = candidates.filter((pullRequest) => pullRequest.head?.sha === sha);
  if (matching.length === 0) return null;
  if (matching.length > 1) {
    throw new Error(`Commit ${sha} belongs to multiple pull requests; PR policy cannot choose one safely.`);
  }
  return matching[0].number;
}

async function run({ env = process.env, fetchImpl = fetch, policyImpl = policy } = {}) {
  const owner = env.CIRCLE_PROJECT_USERNAME;
  const repo = env.CIRCLE_PROJECT_REPONAME;
  const sha = env.CIRCLE_SHA1;
  const token = env.GITHUB_TOKEN;
  const apiUrl = env.GITHUB_API_URL || DEFAULT_API_URL;

  if (!owner || !repo || !sha) {
    throw new Error('CircleCI repository and commit environment variables are required.');
  }
  if (!token) {
    throw new Error('GITHUB_TOKEN is required for private-repository PR policy validation.');
  }

  const pullNumber = await findPullRequestNumber({
    apiUrl,
    token,
    owner,
    repo,
    sha,
    pullRequestUrls: env.CIRCLE_PULL_REQUEST || env.CIRCLE_PULL_REQUESTS,
    fetchImpl,
  });
  if (!pullNumber) {
    console.log(`Commit ${sha} is not attached to a pull request; PR policy is not applicable.`);
    return;
  }

  const pullRequest = await githubRequest({
    apiUrl,
    token,
    path: `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/pulls/${pullNumber}`,
    fetchImpl,
  });
  if (pullRequest.head?.sha !== sha) {
    throw new Error(`Pull request #${pullNumber} does not point to CircleCI commit ${sha}.`);
  }

  const github = {
    paginate: async (method, parameters) => {
      const records = [];
      for (let page = 1; page <= 10; page += 1) {
        const response = await method({ ...parameters, page, per_page: 100 });
        const pageRecords = response.data;
        if (!Array.isArray(pageRecords)) throw new Error('Expected a paginated GitHub array response.');
        records.push(...pageRecords);
        if (pageRecords.length < 100) break;
      }
      return records;
    },
    rest: {
      issues: {
        get: async ({ owner: issueOwner, repo: issueRepo, issue_number: issueNumber }) => ({
          data: await githubRequest({
            apiUrl,
            token,
            path: `/repos/${encodeURIComponent(issueOwner)}/${encodeURIComponent(issueRepo)}/issues/${issueNumber}`,
            fetchImpl,
          }),
        }),
      },
      pulls: {
        list: async ({ owner: pullOwner, repo: pullRepo, state, per_page: perPage, page }) => ({
          data: await githubRequest({
            apiUrl,
            token,
            path: `/repos/${encodeURIComponent(pullOwner)}/${encodeURIComponent(pullRepo)}/pulls?state=${encodeURIComponent(state)}&per_page=${perPage}&page=${page}`,
            fetchImpl,
          }),
        }),
        listFiles: async ({ owner: pullOwner, repo: pullRepo, pull_number: pullNumber, per_page: perPage, page }) => ({
          data: await githubRequest({
            apiUrl,
            token,
            path: `/repos/${encodeURIComponent(pullOwner)}/${encodeURIComponent(pullRepo)}/pulls/${pullNumber}/files?per_page=${perPage}&page=${page}`,
            fetchImpl,
          }),
        }),
      },
      repos: {
        compareCommitsWithBasehead: async ({ owner: compareOwner, repo: compareRepo, basehead }) => ({
          data: await githubRequest({
            apiUrl,
            token,
            path: `/repos/${encodeURIComponent(compareOwner)}/${encodeURIComponent(compareRepo)}/compare/${encodeURIComponent(basehead)}`,
            fetchImpl,
          }),
        }),
      },
    },
  };
  const core = {
    info: (message) => console.log(message),
    warning: (message) => console.warn(message),
    setFailed: (message) => {
      console.error(message);
      process.exitCode = 1;
    },
  };

  await policyImpl.run({
    github,
    context: { payload: { pull_request: pullRequest }, repo: { owner, repo } },
    core,
  });
}

if (require.main === module) {
  run().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = {
  findPullRequestNumber,
  githubRequest,
  parsePullRequestNumber,
  pullRequestNumbers,
  run,
};
