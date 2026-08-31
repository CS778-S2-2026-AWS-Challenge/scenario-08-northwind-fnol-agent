# GitHub Automation Worker

This Cloudflare Worker provides an external runtime for repository automation alongside the
configured repository quality provider. It does not replace or remove `.github/workflows/`; those
files remain the reviewed GitHub-native implementation of the `github` quality profile.

## Responsibilities

- receive signed GitHub `pull_request` webhooks and enqueue them for asynchronous processing;
- run the shared `.github/scripts/pr_policy.cjs` validator and write the `Northwind PR policy`
  commit status to the exact pull-request head SHA;
- synchronize Project 12 only for GitHub closing references (`Closes`, `Fixes`, or `Resolves`);
- treat a Draft pull request as the explicit start signal and set its linked card to `In progress`;
- set a ready-for-review pull request to `In review`, an unmerged closed pull request to
  `In progress`, and a merged pull request to `Done`;
- every 15 minutes, convert valid repository-tracked `Ready` DraftIssues during Auckland working
  hours and reconcile missed pull-request webhook updates.

`Refs` records traceability for partial work but does not change Project status. The Worker never
merges a pull request, changes Draft state, assigns a contributor, or changes repository rulesets.

## Local Verification

Use Node.js 22 from this directory:

```powershell
npm ci
npm run check
npm run dry-run
```

For an authorised live synchronization check, expose a GitHub token only through the process
environment and wait for one Project status transition:

```powershell
$env:GITHUB_TOKEN = gh auth token
npm run verify:kanban -- -- --issue 305 --expected "In progress"
Remove-Item Env:GITHUB_TOKEN
```

The verifier reads Project 12 until the expected status appears or its 60-second timeout expires.
It does not mutate the Project and does not validate CircleCI, pull-request policy, webhook
delivery, or Queue operation as separate capabilities.

## Runtime Configuration

Non-secret Project and repository identifiers are versioned in `wrangler.jsonc`. Set these Worker
secrets interactively only after the Cloudflare resources and deployment are authorised:

```powershell
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put GITHUB_WEBHOOK_SECRET
```

`GITHUB_TOKEN` must be able to read the repository, write commit statuses, read organisation
metadata, and update Project 12. `GITHUB_WEBHOOK_SECRET` must match the secret configured on the
GitHub repository webhook. Never place either value in source, `wrangler.jsonc`, command arguments,
or logs.

The deployed Worker requires the `northwind-github-events` Queue and a repository webhook pointing
to `POST /webhooks/github`. Subscribe the webhook to pull-request events. Deployment, Queue
creation, secret injection, webhook registration, and ruleset changes are external mutations and
must be separately authorised.
