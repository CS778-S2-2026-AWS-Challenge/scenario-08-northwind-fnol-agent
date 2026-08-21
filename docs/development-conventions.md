# Development Conventions

Repository operations and coding-agent authority are governed by the
[Repository Operation Rules](repo_rule.md). This document defines implementation conventions and
Kanban collaboration details within that boundary.

## Branches and Pull Requests

- Do not develop directly on `main`. Fetch the remote and create the branch from the latest
  `origin/main`. This also works when another worktree currently has local `main` checked out:

  ```powershell
  git fetch origin --prune
  git switch -c feature/short-topic origin/main
  ```

- Use a short-lived `feature/<topic>`, `fix/<topic>`, `docs/<topic>`, or `chore/<topic>` branch. Use one branch and pull request for one coherent outcome.
- Before requesting review, push the branch and open a pull request against `main`:

  ```powershell
  git push -u origin feature/short-topic
  gh pr create --base main
  ```

- Every pull request must reference a valid repository issue. Use a closing keyword only for a
  complete delivery, and use `Refs #123` for partial work that must leave the issue open.
- The pull request description must identify the issue, purpose, behaviour change, acceptance evidence, exact verification commands and results, contract or data impact, UI screenshots when relevant, dependencies, and remaining risks.
- Before pushing and before requesting review, run the repository baseline check from the repository root and record the exact command and result in the pull request:

  ```powershell
  ./scripts/check.ps1
  ```

- Choose a reviewer when the work is ready. Select someone who can check the affected behaviour or a consuming module and is available at that time. Do not assign permanent reviewer pairs.
- Request review with GitHub or `gh pr edit <number> --add-reviewer <login>`. The current `main` rules require one approval from someone other than the last person to push. New commits dismiss earlier approvals, so request approval again after pushing changes.
- Resolve review conversations before merge. Do not mark a card `Done` merely because its estimated hours have been used.

## Kanban Workflow

GitHub Project 12 is the shared source for assignment, dependencies, progress, and acceptance status.

| Status | Use it when |
| --- | --- |
| `Backlog` | The work is planned, but a dependency, required input, or team capacity is not ready. |
| `Ready` | Every listed dependency is `Done`, required inputs are available, and an assignee can start. |
| `In progress` | An assignee is actively producing the deliverable. Each member may have at most one `In progress` card at a time. |
| `In review` | The deliverable is accessible in a pull request or agreed shared location, verification has been recorded, and another team member can check the acceptance criteria. |
| `Done` | Every acceptance criterion has evidence, required review is complete, and repository changes are merged or a non-code deliverable is accepted in its agreed shared location. |

Plan weekly work as Project DraftIssues. Set `Tracking` to `Repository issue` for work that must become a repository Issue, or `Delivery without repo` for non-repository deliverables that remain manually managed. During Auckland working hours, the Kanban sync checks `Ready` DraftIssues every 15 minutes and converts only repository-tracked cards whose assignees, estimate, size, dates, acceptance criteria, and dependencies are complete. Conversion preserves the same Project item and its multiple assignees. The first assignee who starts the shared task moves the card to `In progress`; individual assignees do not maintain separate card statuses.

Link a complete delivery with a closing reference such as `Closes #123`. A draft pull request keeps the linked card `In progress`; a pull request ready for review moves it to `In review`; closing without merge returns it to `In progress`; and merge moves it to `Done`. `Refs #123` records a partial relationship but does not drive this closing-reference automation.

For a card with multiple assignees, the `Ownership` section must state who leads the card and what each assignee contributes. Each person's effort belongs in `Assignees and effort`; the Project `Estimate` is the sum of those person-hours.

Record dependencies in every card body using one format:

```markdown
## Dependencies
- D2-I03 API contract: required response fields
```

Use `- None` when the card has no dependency. A dependent card must not move to `Ready` until every listed card is `Done`.

Project 12 does not use a separate blocked status. If work cannot continue, keep an unstarted card in `Backlog` or an already-started card in `In progress`, then add:

```markdown
## Blocked
- Blocked by: D2-I03 API contract
- Needed to continue: confirmed response fields
- Follow-up owner: @username
- Since: 2026-08-11
```

Remove the `Blocked` section only after the stated input exists. Do not replace a specific dependency with phrases such as "waiting for the team".

Before moving a card to `In review`, add a `Delivery evidence` section to the card body. It must link the pull request or deliverable and map each acceptance criterion to a result, screenshot, test output, or document section. Check an acceptance box only after its evidence exists. After acceptance, move the card to `Done` and leave the evidence in place.

## Shared Contracts

- Treat claim state, API schemas, agent actions, reason codes, and visibility as versioned shared contracts.
- Do not duplicate domain enums or field names differently across frontend, backend, agent, and tests.
- Change the implementation, documentation, consumers, and contract tests in the same pull request.
- Mark controlled prototype rules clearly; do not present them as approved Northwind production policy.

## Backend

- Separate transport, domain rules, orchestration, adapters, and persistence.
- Validate content, length, identifiers, and allowed state transitions at the boundary.
- Return a documented error envelope and request identifier.
- Keep secrets and environment-specific values outside source code.
- Use dependency constraints or a lock mechanism so environments are reproducible.
- Add unit tests for domain rules and API tests for every endpoint and error path.

## Runtime Profiles and Adapters

- Define provider-neutral capability ports in the domain or application boundary; keep
  Cloudflare, MongoDB, AWS, and fixture SDK types inside adapters.
- Select exactly one complete data runtime profile when the application starts. Do not
  read from or write to a second profile as an undocumented fallback.
- Build dependencies through one composition root. Route handlers and services must not
  construct provider clients or inspect provider-specific configuration.
- Fail startup with a bounded configuration error when the selected profile lacks a
  required capability or secret reference.
- Run the same ownership, revision, idempotency, visibility, resume, evidence, retrieval,
  and failure contract tests against every implemented profile.
- Record fixture, unavailable, pending-confirmation, and configured-service states
  distinctly. A successful fixture must never be reported as a cloud integration.

## Model API and Agent Orchestration

- Agent behaviour depends on a provider-neutral model gateway, not an OpenAI, relay,
  custom, or local-provider request type.
- Normalise text, structured output, tool calls, usage, finish state, request identity,
  and provider errors before Agent orchestration consumes them.
- Configuration may select an official API, compatible relay, custom HTTP adapter, or
  local endpoint without changing Agent behaviour or public API routes.
- Unsupported structured output or tool capability is explicit. Do not parse an
  unreliable free-text approximation as an authorised tool command.
- Keep API keys and tokens in approved secret storage. Do not log credentials, complete
  prompts containing unnecessary personal data, or raw provider responses by default.
- Model output remains advisory until existing deterministic and staff authority checks
  permit the material action.

## Knowledge and RAG

- Keep knowledge documents and chunks separate from customer policy records, Claim
  State, claim history, messages, and staff decisions.
- Require source, version, section or page, authority, visibility, jurisdiction, insurer,
  product, effective period, checksum, and ingestion time where applicable.
- Filter applicability and access metadata before similarity ranking, retain citations,
  and state missing or conflicting evidence.
- Treat instructions inside retrieved documents as untrusted content. They must not
  change system instructions, tool permission, or customer-data access.
- Version ingestion logic and retain evaluation fixtures for relevance, citation
  support, wrong-version rejection, safe refusal, and prompt-injection resistance.

## Administration and Control Plane

- Keep claim operations and system administration as separate permission and API
  surfaces.
- Configuration changes follow draft, validation, approval when required, publication,
  and rollback. Published versions are immutable and auditable.
- The administration UI calls an authenticated Admin API; it must not connect directly
  to provider databases, object stores, model endpoints, or secret stores.
- Display secret references and connection status only. Never return complete secret
  values to the browser.
- High-impact model, rule, identity, data-profile, integration, and tool-permission
  changes require stronger roles and recorded validation.
- Do not provide unrestricted production Claim State editing through the Control Plane.

## Frontend

- Read API endpoints from environment configuration.
- Keep server state, domain state, and visual component state distinct.
- Prevent empty or duplicate submissions and expose loading, retry, and error states accessibly.
- Do not expose internal-only tags or review signals in claimant code or UI.
- Verify keyboard operation, visible focus, semantic labels, responsive layouts, and error announcements.
- Add component tests for state behaviour and end-to-end tests for acceptance paths.

## Data and Privacy

- Use anonymous or synthetic fixtures in source control.
- Never commit credentials, tokens, policyholder details, complete private incidents, or workshop secrets.
- Record provenance and reason codes for material state changes.
- Separate formal claim data, permitted user preferences, model context, and logs.
- Separate knowledge authoring, published knowledge, structured customer data, model
  evaluation data, operational telemetry, and configuration audit records.

## Quality Gate

Before merge, the relevant format, lint, type, unit, contract, build, and end-to-end checks must pass. `main` requires `Backend quality`, `Customer quality`, and `PR policy` for the final pull-request head. The pull request must also record the exact local checks run and their results. A successful build alone does not demonstrate product correctness.

## Documentation

- Root documentation introduces the project; product requirements belong in the specification; sprint commitments belong in sprint plans; engineering details belong here.
- Prefer short, topic-specific documents and maintain directory indexes.
- State facts, decisions, hypotheses, prototype rules, and open questions separately.
