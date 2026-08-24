export type ProjectStatus = "In progress" | "In review" | "Done";

export interface PullRequestEvent {
  action: string;
  repository: {
    fullName: string;
  };
  pullRequest: {
    number: number;
    body: string;
    draft: boolean;
    merged: boolean;
    state: string;
    headSha: string;
    htmlUrl: string;
  };
  previousBody: string | null;
}

export interface GitHubQueueMessage {
  deliveryId: string;
  eventName: string;
  payload: unknown;
}

export type WorkerEnv = Env & {
  readonly GITHUB_TOKEN: string;
  readonly GITHUB_WEBHOOK_SECRET: string;
};

export type ProjectEnvironment = Pick<
  WorkerEnv,
  | "PROJECT_OWNER"
  | "PROJECT_NUMBER"
  | "PROJECT_ID"
  | "TARGET_REPOSITORY"
  | "TRACKING_FIELD"
  | "REPOSITORY_TRACKING_OPTION"
  | "DELIVERY_TRACKING_OPTION"
>;

export type JsonRecord = Record<string, unknown>;
