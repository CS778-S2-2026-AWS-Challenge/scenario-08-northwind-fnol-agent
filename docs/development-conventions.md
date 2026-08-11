# Development Conventions

## Branches and Pull Requests

- Do not develop directly on `main`. Start from the latest remote `main`:

  ```powershell
  git switch main
  git pull --ff-only origin main
  git switch -c feature/short-topic
  ```

- Use a short-lived `feature/<topic>`, `fix/<topic>`, `docs/<topic>`, or `chore/<topic>` branch. Use one branch and pull request for one coherent outcome.
- Before requesting review, push the branch and open a pull request against `main`:

  ```powershell
  git push -u origin feature/short-topic
  gh pr create --base main
  ```

- The pull request description must identify the Kanban card, purpose, behaviour change, acceptance evidence, exact verification commands and results, contract or data impact, UI screenshots when relevant, and remaining risks.
- Before requesting review, run the repository baseline check from the repository root and record the exact command and result in the pull request:

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

Link a pull request with a closing reference such as `Closes #123`. A draft pull request keeps the linked card `In progress`; a pull request ready for review moves it to `In review`; closing without merge returns it to `In progress`; and merge moves it to `Done`.

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

## Quality Gate

Before merge, the relevant format, lint, type, unit, contract, build, and end-to-end checks must pass. The repository has a minimal CI workflow, but `main` does not yet require status checks; the pull request must record the exact local checks run and their results. A successful build alone does not demonstrate product correctness.

## Documentation

- Root documentation introduces the project; product requirements belong in the specification; sprint commitments belong in sprint plans; engineering details belong here.
- Prefer short, topic-specific documents and maintain directory indexes.
- State facts, decisions, hypotheses, prototype rules, and open questions separately.
