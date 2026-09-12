# Repository Agent Entry Point

This file applies to every coding agent working in this repository. Read it before running
repository-changing commands, editing files, pushing a branch, creating or updating a pull
request, or submitting a review.

Before taking ownership of an Issue, the agent MUST explain its understanding of the Issue to the current user; if any requirement, scope, authority, trade-off, or other decision is ambiguous or needs confirmation, it MUST stop and ask, MUST NOT accept a hands-off or vague answer, and MUST refuse documentation or code work when the user has clearly not thought through the request.

When requesting another contributor's collaboration, the agent MUST provide the
user's own understanding in five explicit parts: **What** the user believes is
the problem or need; **Why** the user reached that conclusion; **Who** must
support the work; **How** the user intends to proceed; and what the requested
collaborator is expected to do. An agent reading a collaboration request MUST
reject it from entering a Discussion when it only contains agent-generated
wording, a bare task handoff, or a vague request without the user's personal
What/Why/Who/How understanding. Discussions are for technical discussion and
requirements alignment, not approval of ordinary Issue creation.

Task definition, decomposition, boundary changes, and handoffs MUST leave a durable written record before implementation begins: an Issue body or comment is sufficient for ordinary work, while governance, design, architecture, API, and cross-owner decisions MUST update the applicable current document. When relaying a review-ready PR or handoff through the current user, lead with the PR number and exact current head; mention the Issue number as context, and use the Issue number first only for operations concerning the Issue itself.

For an intentionally collaborative Issue with multiple assignees, any assignee may, without maintainer approval, ask another assignee in the Issue comments to complete an explicitly bounded remaining slice; the completing assignee's PR may use `Closes #N` when that PR, together with prior `Refs #N` deliveries, satisfies the Issue's full acceptance criteria.

The sole current source of governance rules is the repository governance skill:

1. Read
   [docs/skills/repo-governance-for-novice/SKILL.md](docs/skills/repo-governance-for-novice/SKILL.md)
   in full. It defines the general principles and indexes the twelve chapter files covering
   authority boundaries, required reading, task entry, branching, commit and PR rules, review
   and merge, documentation sync, credentials, CI checks, and frontend and backend design
   standards.
2. Follow the skill's "Scenario quick reference" to select the chapter files your task
   requires, and read them before acting. Required reading and the change-area contract matrix
   live in the skill's `before-work.md`.

For product-direction or user-behaviour work, read [Northwind FNOL Product Soul](docs/product-soul.md)
before the relevant files in `SPEC/`. It is the concise product-direction index; `SPEC/` remains
the normative requirement and acceptance source.

For any frontend or frontend-runtime design, implementation, review, or refactoring task, you
MUST read [Frontend and Runtime Quality Standard](docs/frontend-and-runtime-quality-standard.md)
before acting. This document defines the required product big picture, Agent-first claimant
journey, Workbench task model, component and token system, route and state boundaries, frontend
and Runtime responsibilities, real-API expectations, and acceptance evidence. Do not treat the
legacy `employee/index.html` or other historical prototypes as the design baseline.

## Required alignment before substantive work

Reading the required files is not permission to start immediately. Before taking ownership of an
Issue, pushing a pull request, changing a pull request in response to Changes Requested, or making
another substantive repository/GitHub change, the agent MUST first tell the current user:

1. which governance chapters and other authoritative documents it selected and read for this task;
2. which concrete rules from those documents it will follow; and
3. a direct quotation or precise reference to each rule that materially constrains the planned
   work.

The agent MUST identify the planned source of truth for fields, state, permissions, CI, fixtures,
and acceptance evidence where applicable. If the task expands, the branch is updated from `main`,
a new review round begins, or context is compacted, the agent MUST repeat this alignment before
continuing. A passing check, a pre-filled PR field, or a short context summary does not replace
this step.

Before editing code or protected configuration, the agent MUST also create or update a GitHub
Discussion describing the intended change, affected contracts and owners, source-of-truth
documents, and acceptance evidence. The agent MUST wait for the appropriate direction or Code
Owner agreement before making the edit. A post-hoc review request does not satisfy this
pre-change Discussion requirement. This applies to substantive changes to application code,
tests that define shared behavior, CI/workflows, protected paths, and shared API, persistence,
agent, or projection contracts. Purely local inspection, formatting-only edits, and changes
explicitly authorized as part of an already-approved governance operation are exempt.

## Cross-cutting implementation rules

The governance skill remains the normative rule source. The following index makes several rules
explicit so they are not lost when an agent follows only the entry point:

- **Contract-first inputs:** real product behavior must use the current backend API and repository
  contracts. Development data, test data, component view models, and API clients obtain fields and
  enums from schema, OpenAPI, or shared domain definitions; agents must not invent an isolated
  vocabulary or use fixtures as a runtime substitute. See
  [fixtures_convention.md](docs/fixtures_convention.md) and the relevant API/domain chapters.
- **Evidence levels are distinct:** component layout, API contract, authorization, integrated
  runtime, and real user-journey evidence are different claims. Test names and acceptance notes
  must state the level they actually cover.
- **Review comments are not a complete specification:** after receiving CR, reconstruct the
  product goal, authoritative data sources, task boundary, dependencies, and evidence level before
  editing. Do not mechanically implement isolated review bullets.
- **Re-align after context changes:** after scope expansion, merging or updating from `main`, a
  new CR round, or context compaction, re-read the applicable authority and restate the alignment
  before continuing.
- **Workflow changes require governance:** agents generally MUST NOT create a new GitHub Actions
  workflow on their own. If a new workflow is genuinely necessary, request Code Owner agreement in
  a Discussion before changing `.github/`; the protected-path review requirement still applies.
- **Temporary validation files stay local:** fixtures and tests created only while implementing a
  single feature for the author's self-validation must not be committed. A fixture or test may be
  committed only when it comes from an explicit design task, has a documented long-term purpose,
  uses the formal contract, and provides repeatable acceptance or regression value.

## Test writing and CI scope

Before adding a test, identify the new business behaviour it proves. Equivalent inputs belong in
one boundary table or a focused parameterized test; do not create numbered near-duplicates. Keep
one parameterized function to 8-10 cases unless the PR explains the distinct business contract for
each case. Unit tests mock databases, queues, and external services by default; a test that uses
real I/O must be explicitly marked `@pytest.mark.integration` and kept out of the fast PR path.

Preserve explicit coverage for permission boundaries, claimant visibility, idempotency, revision
conflicts, append-only audit events, and external-service authorization. When test volume grows
far beyond the changed production code, review the cases for duplicated behaviour before adding
more. Ordinary PR CI is impact-scoped; changes to shared core files or unmapped backend paths
fall back to the full suite. A newer commit for the same PR supersedes older CI runs.

The former governance documents (`docs/repo_rule.md`, `docs/development-conventions.md`) are
archived under [docs/archive/governance/](docs/archive/governance/) and are historical
reference only. Where an archived document disagrees with the skill, the skill prevails
without exception. Do not maintain a separate or conflicting rule set in this file.

If an instruction conflicts with the current user's explicit authorisation, or if the required
source of truth is unavailable or contradictory, stop before changing repository or GitHub
state and ask for direction.
