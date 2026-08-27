const assert = require('node:assert/strict');
const test = require('node:test');

const {
  findPullRequestNumber,
  parsePullRequestNumber,
  pullRequestNumbers,
  run,
} = require('./run-pr-policy.cjs');

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test('parses CircleCI pull-request URLs', () => {
  assert.equal(parsePullRequestNumber('https://github.com/example/repo/pull/42'), 42);
  assert.equal(parsePullRequestNumber(''), null);
  assert.deepEqual(
    pullRequestNumbers(
      'https://github.com/example/repo/pull/42,https://github.com/example/repo/pull/43',
    ),
    [42, 43],
  );
});

test('finds the pull request whose head matches the CircleCI commit', async () => {
  const number = await findPullRequestNumber({
    apiUrl: 'https://api.github.test',
    token: 'test-token',
    owner: 'example',
    repo: 'repo',
    sha: 'abc123',
    fetchImpl: async () => response([
      { number: 10, head: { sha: 'other' } },
      { number: 11, head: { sha: 'abc123' } },
    ]),
  });
  assert.equal(number, 11);
});

test('rejects multiple pull-request URLs rather than validating an arbitrary one', async () => {
  await assert.rejects(
    findPullRequestNumber({
      apiUrl: 'https://api.github.test',
      token: 'test-token',
      owner: 'example',
      repo: 'repo',
      sha: 'abc123',
      pullRequestUrls:
        'https://github.com/example/repo/pull/42,https://github.com/example/repo/pull/43',
      fetchImpl: async () => { throw new Error('GitHub API should not be called.'); },
    }),
    /multiple pull requests/,
  );
});

test('skips policy validation for a commit with no pull request', async () => {
  let policyCalled = false;
  await run({
    env: {
      CIRCLE_PROJECT_USERNAME: 'example',
      CIRCLE_PROJECT_REPONAME: 'repo',
      CIRCLE_SHA1: 'abc123',
      GITHUB_TOKEN: 'test-token',
    },
    fetchImpl: async () => response([]),
    policyImpl: { run: async () => { policyCalled = true; } },
  });
  assert.equal(policyCalled, false);
});

test('validates the pull request at the exact CircleCI commit', async () => {
  let receivedContext;
  let receivedQualityMode;
  const fetchImpl = async (url) => {
    if (url.endsWith('/commits/abc123/pulls')) {
      return response([{ number: 42, head: { sha: 'abc123' } }]);
    }
    if (url.endsWith('/pulls/42')) {
      return response({ number: 42, body: 'body', draft: false, head: { sha: 'abc123' } });
    }
    throw new Error(`Unexpected URL: ${url}`);
  };

  await run({
    env: {
      CIRCLE_PROJECT_USERNAME: 'example',
      CIRCLE_PROJECT_REPONAME: 'repo',
      CIRCLE_SHA1: 'abc123',
      GITHUB_TOKEN: 'test-token',
    },
    fetchImpl,
    policyImpl: {
      run: async ({ context, requireLocalQualityEvidence }) => {
        receivedContext = context;
        receivedQualityMode = requireLocalQualityEvidence;
      },
    },
  });

  assert.equal(receivedContext.repo.owner, 'example');
  assert.equal(receivedContext.repo.repo, 'repo');
  assert.equal(receivedContext.payload.pull_request.number, 42);
  assert.equal(receivedQualityMode, false);
});

test('rejects a pull-request URL that does not point to the current commit', async () => {
  await assert.rejects(
    run({
      env: {
        CIRCLE_PROJECT_USERNAME: 'example',
        CIRCLE_PROJECT_REPONAME: 'repo',
        CIRCLE_PULL_REQUEST: 'https://github.com/example/repo/pull/42',
        CIRCLE_SHA1: 'abc123',
        GITHUB_TOKEN: 'test-token',
      },
      fetchImpl: async () => response({ number: 42, head: { sha: 'stale' } }),
      policyImpl: { run: async () => {} },
    }),
    /does not point to CircleCI commit/,
  );
});
