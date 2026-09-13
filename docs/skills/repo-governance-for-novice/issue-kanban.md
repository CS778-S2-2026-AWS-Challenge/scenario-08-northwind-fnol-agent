# §3 Task entry: issues, Kanban, and PRs

This file defines what issues, the Kanban board, and PRs are each responsible
for, and how they are linked.

## 3.1 Responsibilities

- **Kanban (GitHub Project 12,
  https://github.com/orgs/CS778-S2-2026-AWS-Challenge/projects/12)**: the
  shared source of truth for assignment, dependencies, progress, and acceptance
  status. Maintained exclusively by the maintainer; read-only for all agents
  (§1.2). Status transitions are driven only by repository automation via
  closing references.
- **Issue**: carries features, bugs, regression verification, integration
  gaps, security concerns, and maintenance or documentation work, using the
  `Code work` Issue Form. Required fields must not be left as placeholders.
  Every issue must declare the behavior it owns, the expected impact area,
  non-goals, affected shared contracts, dependencies, and risk level.
- **Task-definition record**: task definition, decomposition, boundary changes,
  and handoffs must leave a durable written record before implementation begins.
  An Issue body or comment is sufficient for ordinary work; governance, design,
  architecture, API, and cross-owner decisions must update the applicable
  current document.
- **PR**: one coherent repository change plus one valid linked issue. Do not
  open empty placeholder PRs, split work to evade acceptance or review, or use
  a new PR to conceal the unfinished work of an old one.

## 3.2 Linking rules

- Every PR must reference at least one valid issue of this repository in its
  `Linked issue` section.
- Use `Closes #123` / `Fixes #123` / `Resolves #123` only when the PR fully
  satisfies the issue's acceptance criteria.
- Use `Refs #123` for partial delivery, dependencies, investigation, or
  follow-ups; it must not close the issue.
- For an intentionally collaborative Issue with multiple assignees, any
  assignee may, without maintainer approval, ask another assignee in the Issue
  comments to complete an explicitly bounded remaining slice; the completing
  assignee's PR may use `Closes #123` when that PR, together with prior
  `Refs #123` deliveries, satisfies the Issue's full acceptance criteria.
- A `Refs` relationship does not drive closing-reference Kanban automation; the
  card stays open and its status must reflect the remaining work.
- Do not claim an issue is complete while dependencies, acceptance criteria,
  integration results, or required consumers remain unfinished.

## 3.3 Issue creation

The agent may create a new issue directly through the appropriate Issue Form.
There is no maintainer-approval gate for issue creation. Required fields still
must be complete and must state the owned behavior, impact area, non-goals,
shared contracts, dependencies, risk level, and observable acceptance criteria.
When acceptance criteria are unfinished, update the existing issue instead of
opening a duplicate. A follow-up issue must explain its relationship to the
original issue and define its own boundary.

GitHub Discussions are for technical discussion and requirements alignment,
not issue-creation approval. Use a Discussion when a design choice, API field,
permission, visibility rule, or cross-owner dependency needs agreement. For
example, a frontend owner may ask `@liyang6620` to provide a backend field and
document the required request/response and visibility semantics. The issue may
be created before or after that discussion; the discussion link is evidence of
alignment, not an authorization gate.

A PR carrying new task requirements may use `Refs` against an existing issue.
The Kanban board remains maintained exclusively by the maintainer.

**Discussion categories**: use `Design` for technical and product-contract
alignment and `Q&A` for other questions or uncertainty reports. Agents must not
use Discussions as an approval queue for ordinary issue creation.

## 3.4 Kanban workflow

Status definitions:

| Status | When to use |
| --- | --- |
| `Backlog` | Planned, but dependencies, required inputs, or capacity are not ready. |
| `Ready` | All listed dependencies are `Done`, required inputs are available, and the assignee can start. |
| `In progress` | The assignee is producing the deliverable, or a pull request has entered Draft state. |
| `In review` | The deliverable is accessible via a PR or the agreed shared location, verification is recorded, and others can check it against the acceptance criteria. |
| `Done` | Every acceptance criterion has evidence, required review is complete, and the repository change is merged (or the non-code deliverable is accepted at the agreed location). |

- A Draft PR with a closing reference is the explicit start-of-work signal and
  moves the linked card to `In progress`; do not move statuses manually. PR
  ready for review → `In review`; closed without merging → back to
  `In progress`; merged → `Done`.
- Record dependencies in a `## Dependencies` section of the card body (write
  `- None` when there are none). A card must not enter `Ready` until every
  card it depends on is `Done`.
- When blocked, do not change status; add a `## Blocked` section (Blocked by /
  Needed to continue / Follow-up owner / Since) and remove it once inputs are
  ready. Do not substitute vague phrases like "waiting for the team" for
  concrete dependencies.
- Before a card moves to `In review`, add a `Delivery evidence` section to the
  card body: link the PR or deliverable and map every acceptance criterion to a
  result, screenshot, test output, or documentation section. Acceptance boxes
  may be checked only after the evidence exists.
