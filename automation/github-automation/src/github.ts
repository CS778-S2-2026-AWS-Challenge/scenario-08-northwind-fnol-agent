import { isRecord, requireRecord } from "./validation";

const GITHUB_API_VERSION = "2022-11-28";

export class GitHubApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "GitHubApiError";
  }
}

type Fetcher = typeof fetch;

export class GitHubClient {
  constructor(
    private readonly token: string,
    private readonly fetcher: Fetcher = fetch,
  ) {}

  async getIssue(owner: string, repo: string, issueNumber: number): Promise<Record<string, unknown>> {
    return this.restJson(`/repos/${owner}/${repo}/issues/${String(issueNumber)}`);
  }

  async setCommitStatus(input: {
    owner: string;
    repo: string;
    sha: string;
    state: "error" | "failure" | "pending" | "success";
    description: string;
    targetUrl: string;
  }): Promise<void> {
    await this.restJson(`/repos/${input.owner}/${input.repo}/statuses/${input.sha}`, {
      method: "POST",
      body: JSON.stringify({
        state: input.state,
        description: input.description,
        target_url: input.targetUrl,
        context: "PR policy",
      }),
    });
  }

  async graphql(query: string, variables: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>> {
    const response = await this.request("https://api.github.com/graphql", {
      method: "POST",
      body: JSON.stringify({ query, variables }),
    });
    const payload: unknown = await response.json();
    const root = requireRecord(payload, "GitHub GraphQL response");
    if (Array.isArray(root.errors) && root.errors.length > 0) {
      const messages = root.errors
        .map((error) => (isRecord(error) && typeof error.message === "string" ? error.message : "Unknown GraphQL error"))
        .join("; ");
      throw new GitHubApiError(`GitHub GraphQL failed: ${messages}`, response.status);
    }
    return requireRecord(root.data, "GitHub GraphQL response.data");
  }

  private async restJson(
    path: string,
    init: RequestInit = {},
  ): Promise<Record<string, unknown>> {
    const response = await this.request(`https://api.github.com${path}`, init);
    if (response.status === 204) return {};
    const payload: unknown = await response.json();
    return requireRecord(payload, `GitHub REST response for ${path}`);
  }

  private async request(url: string, init: RequestInit): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/vnd.github+json");
    headers.set("Authorization", `Bearer ${this.token}`);
    headers.set("Content-Type", "application/json");
    headers.set("User-Agent", "northwind-github-automation");
    headers.set("X-GitHub-Api-Version", GITHUB_API_VERSION);

    const response = await this.fetcher(url, { ...init, headers });
    if (!response.ok) {
      const message = (await response.text()).slice(0, 500);
      throw new GitHubApiError(
        `GitHub API ${String(response.status)} for ${new URL(url).pathname}: ${message}`,
        response.status,
      );
    }
    return response;
  }
}
