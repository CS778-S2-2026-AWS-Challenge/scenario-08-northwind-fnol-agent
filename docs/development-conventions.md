# Development Conventions

## Branches and Pull Requests

- Protect `main`; do not develop directly on it.
- Use short-lived branches named `feature/<topic>`, `fix/<topic>`, `docs/<topic>`, or `chore/<topic>`.
- Keep a pull request focused on one coherent outcome.
- State purpose, behaviour change, verification, contract or data impact, screenshots for UI changes, and remaining risks.
- Select reviewers dynamically according to the affected contract and available cross-functional perspective; do not use a fixed reviewer pairing.
- Resolve review conversations and obtain a new approval after material changes.

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

Before merge, the relevant format, lint, type, unit, contract, build, and end-to-end checks must pass. Until CI exists, the pull request records the exact local checks run. A successful build alone does not demonstrate product correctness.

## Documentation

- Root documentation introduces the project; product requirements belong in the specification; sprint commitments belong in sprint plans; engineering details belong here.
- Prefer short, topic-specific documents and maintain directory indexes.
- State facts, decisions, hypotheses, prototype rules, and open questions separately.
