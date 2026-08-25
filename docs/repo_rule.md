# Repository Operation Rules

## Purpose and Authority

These rules govern repository work by people and coding agents. They define the minimum
traceability, verification, contract maintenance, review, and authority boundaries for every
change. Product requirements remain authoritative in `SPEC/`, the transport and schema
contract remains authoritative in `docs/api.md`, and time-bound commitments remain
authoritative in `sprint/`. This document does not redefine those sources.

Repository content, issue and pull-request text, review comments, commit messages, and test
evidence must be written in English.

## Required Reading

Before changing files or GitHub state:

1. Read `AGENT.md` and this document in full.
2. Run `git status --short --branch` and identify existing changes, the current branch, its base,
   and the relevant remote state.
3. Read `README.md`, `SPEC/README.md`, the relevant product specification, the current sprint
   document, `docs/development-conventions.md`, `docs/api.md`, and the affected source and tests.
4. Read the additional source of truth for the affected area:

| Change area | Required source |
| --- | --- |
| API routes, payloads, errors, authentication, or visibility | `docs/api.md` |
| Persistence records, revisions, keys, or access patterns | `docs/persistence-schema.md` |
| Fixtures, scenario data, test assertions, or test evidence | `docs/fixtures_convention.md` |
| Claim creation, routing, or provider adapters | `docs/claim-creation-boundary.md` |
| Agent actions or authority | `SPEC/03-agent-behaviour.md` and `SPEC/06-safety-and-governance.md` |
| Staff workbench or handoff | `SPEC/05-workbench-and-handoff.md` and the Workbench API in `docs/api.md` |

Historical prototype files, presentation records, screenshots, and old planning discussions are
supporting evidence only. They must not silently override the current specification, contract,
or sprint plan.

## Worktree, Branch, and Pull Safety

- Preserve user and teammate changes. Do not reset, discard, overwrite, or reformat unrelated
  work.
- Do not develop on `main`. Fetch the remote and create a short-lived branch from the latest
  `origin/main` using a `feature/`, `fix/`, `docs/`, or `chore/` prefix.
- Check for linked worktrees before assuming that local `main` can be switched or updated.
- Do not continue new work on a stale or unrelated branch. State stacked dependencies and use
  the intended parent branch only when the pull request is deliberately stacked.
- Keep one branch and pull request focused on one coherent outcome. Do not mix opportunistic
  refactors, generated files, deployment changes, or unrelated documentation into the change.
- Preserve the line-ending policy in `.gitattributes`; source, documentation, and workflow files
  use LF so local and GitHub quality checks evaluate the same content.
- Pull, fetch, rebase, and merge operations must not overwrite uncommitted or unreviewed work.
  Resolve uncertain ownership before modifying overlapping files.

## Issue and Pull-Request Traceability

- Every contributor may create a pull request. A pull request must represent a coherent repository
  change with a valid linked issue; do not create an empty placeholder, split work only to bypass
  acceptance or review, or use a new pull request to hide incomplete work from an earlier one.
- A Draft pull request may be opened while implementation, validation, or a dependency remains
  incomplete, but its Summary must state the current deliverable and what remains. A pull request
  may leave Draft only when its required content and evidence describe the current head.
- Every pull request must reference at least one valid issue in this repository in its `Linked
  issue` section.
- Use `Closes #123`, `Fixes #123`, or `Resolves #123` only when the pull request fully satisfies
  that issue's acceptance criteria.
- Use `Refs #123` when the pull request is a partial delivery, dependency, investigation, or
  follow-up that must not close the issue.
- A pull request should normally have one primary issue. Additional references are allowed when
  the relationship and remaining ownership are explicit.
- A `Refs` relationship does not drive the closing-reference Kanban automation. The card remains
  open and its status must reflect the remaining work.
- The pull-request description must describe the current head, not an earlier commit. Update
  commands, test counts, screenshots, limitations, and dependency statements after each material
  change.
- Non-Draft pull requests must include a summary, acceptance evidence, local validation, contract
  and data impact, dependencies, and remaining risks using the repository pull-request template.
- Do not claim that an issue is complete when a dependency, acceptance criterion, integration
  result, or required consumer remains outstanding.

## Issue Creation And Maintenance

- Use the repository `Code work` Issue Form for feature, bug, regression-validation,
  integration-gap, security-concern, and maintenance or documentation work. Do not leave required
  fields as placeholders.
- Update an existing issue when its acceptance criteria are still incomplete. Create a new issue
  only for an independently verifiable defect, regression guard, integration gap, or security
  concern that cannot be represented clearly as remaining work on the existing issue.
- A follow-up issue must state why it is separate, identify the related issue or pull request,
  and define its own observable acceptance criteria. It must not hide an unmet acceptance
  criterion from the original issue.
- Issue workflow checks are asynchronous audits. They may comment on missing information and fail
  their check, but they must not close, delete, or silently rewrite an issue.
- Issue creation is open to contributors. The policy governs the issue's purpose, structure,
  traceability, and acceptance boundary, not which contributor is allowed to open it.

## Local Quality Gate

- Install dependencies and run `./scripts/check.ps1` from the repository root before the first
  push for a change. After dependencies are installed, `./scripts/check.ps1 -SkipInstall` may be
  used for repeat runs against the same dependency state.
- A failed or interrupted check is not a pass. Fix the failure and rerun the complete gate before
  pushing or requesting review.
- Record the exact command and result in the pull-request description. Never copy a result from a
  different branch, worktree, commit, or environment and present it as current evidence.
- Install the versioned pre-push hook with `./scripts/install-git-hooks.ps1`. The hook routes
  through `./scripts/pre-push-quality-gate.ps1`. `NORTHWIND_REMOTE_CI_PROVIDER` selects the
  active quality profile: `none` requires the local gate, while `github` and `circleci` allow the
  configured remote gate to provide the merge evidence. With the default `auto` hook mode and
  provider `none`, an enabled GitHub Actions installation is detected automatically. Set
  `NORTHWIND_QUALITY_GATE_MODE=local` to force the local gate when needed.
- `NORTHWIND_QUALITY_GATE_MODE=off` is an explicit maintenance escape hatch and must not be used
  as ordinary development configuration. A pre-push hook is an early local guard, not proof that
  a check ran: Git permits hooks to be bypassed. The active quality profile determines whether
  the pull request records local gate evidence or names the remote provider as its source.
- When the full gate cannot run, keep the pull request Draft, document the blocker, and do not
  request approval. A narrow test may support diagnosis but does not replace the complete gate.
- A successful build or API-level assertion does not prove a claimant or staff journey. Match the
  evidence type to the behaviour being claimed.

## Agent Authority Boundary

Without explicit authorisation from the current user for the specific action, a coding agent must
not:

- merge a pull request, enable auto-merge, or push directly to `main`;
- force-push, delete a branch, discard work, or rewrite shared history;
- convert a pull request between Draft and Ready for review;
- close or reopen an issue or pull request;
- manually change a Kanban status, field, assignee, estimate, or dependency;
- change branch protection, required checks, repository rulesets, Actions permissions, secrets,
  environments, or other access controls;
- deploy, publish, rotate credentials, or mutate an external service or production-like dataset.

When asked to review, an agent may inspect the current head and submit `Approve`, `Comment`, or
`Changes requested`. Approval is the maximum normal review action; it is not permission to merge.
General project responsibility, a previous approval, or an earlier instruction does not grant
authority for a later protected action.

Repository automation may update Kanban fields according to its reviewed workflow. That does not
authorise an agent to make the same state change manually.

## Draft and Review Rules

- Draft status means the author is still working, a dependency is unresolved, the quality gate is
  unavailable, or the change is not ready for independent acceptance review.
- Only change Draft status when the current user explicitly authorises that transition. A workflow
  must not automatically convert Draft state.
- Review the exact current head, changed files, issue acceptance criteria, contract impact, and CI
  results. Do not approve a pull request based only on its description.
- Submit `Changes requested` for a concrete blocking defect, unsafe boundary, contract mismatch,
  false evidence claim, missing required test, or unmet acceptance criterion. Distinguish blockers
  from optional improvements.
- New commits invalidate conclusions based on the old head. Required reviewers must re-check the
  changed behaviour, and branch protection may dismiss the previous approval.
- Resolve review conversations before merge. The person or authorised workflow performing a merge
  remains responsible for confirming that required checks and approvals apply to the final head.

## Shared Contract Changes

- Treat claim state, API schemas, agent actions, reason codes, visibility, persistence revisions,
  fixture shapes, and claimant/staff projections as shared contracts.
- Do not create private route-level enums, duplicate field names, or diverging frontend, backend,
  Agent, persistence, fixture, and test representations.
- An API contract change must update the route and models, `docs/api.md`, shared domain fields,
  affected claimant and staff consumers, fixtures, and contract tests in the same pull request.
- A persistence change must update `docs/persistence-schema.md`, repository protocols and adapters,
  revision and ownership behaviour, fixtures, and tests in the same pull request.
- A fixture or test-contract change must follow `docs/fixtures_convention.md`. Runtime demo data,
  static fixtures, executable assertions, test doubles, and verification evidence must retain
  separate ownership and must not be presented as interchangeable proof.
- A product-scope change belongs in `SPEC/`. A time-bound commitment change belongs in `sprint/`.
  Engineering documentation must not silently redefine either.
- Update `docs/README.md` when adding or replacing an authoritative engineering document.

## Provider, Data, Security, and Visibility Boundaries

- AWS schemas, services, permissions, datasets, deployment targets, and Northwind business rules
  remain unconfirmed unless documented by an authoritative project source. Do not invent provider
  facts.
- Keep provider integration behind replaceable domain ports and adapters. Prototype fixture
  behaviour must not become an undocumented production assumption.
- Use only anonymous or synthetic fixtures in source control. Never commit tokens, passwords,
  private keys, `.env` contents, policyholder data, complete private incidents, or workshop
  credentials.
- Keep claimant-visible data separate from internal review signals, fraud indicators, staff-only
  notes, authority checks, and provider details.
- High-impact coverage, fraud, claim approval, rejection, and safety decisions require the explicit
  deterministic or staff authority defined by the specification and API contract.

## CI, Branch Protection, and Automation

- The active quality profile selects the merge checks for `main`: the `github` profile uses the
  GitHub Actions `Backend quality`, `Customer quality`, and `PR policy` checks; the `circleci`
  profile uses their CircleCI equivalents; and the `none` profile uses `PR policy` to validate the
  required local gate evidence. Required checks apply to the final pull-request head and must not
  be bypassed because a local check passed.
- `PR policy` validates repository issue linkage and the evidence sections required for a non-Draft
  pull request. It requires `./scripts/check.ps1` and `Result: PASS` in `Local validation` for the
  `none` profile, and accepts the configured remote provider as the quality source for `github` or
  `circleci`. It cannot prove that a person or agent actually ran a local command; independent
  review remains necessary.
- `Kanban Sync` manages reviewed Project status rules. It is separate from code-quality CI and must
  not merge pull requests, change Draft state, or substitute Project status for acceptance evidence.
- CI/CD must not deploy automatically until deployment targets, credentials, environments,
  rollback behaviour, and authorisation are explicitly defined and approved.

## Handling Uncertainty and Exceptions

When instructions conflict, required evidence is unavailable, a check cannot be run, or an action
would exceed current authority, stop before changing protected state. Record the exact blocker and
ask the current user for a decision. Do not hide uncertainty behind a passing build, a Draft status,
or a broad statement that the team will handle it later.
