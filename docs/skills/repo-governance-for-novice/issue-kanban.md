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
- A `Refs` relationship does not drive closing-reference Kanban automation; the
  card stays open and its status must reflect the remaining work.
- Do not claim an issue is complete while dependencies, acceptance criteria,
  integration results, or required consumers remain unfinished.

## 3.3 Issue creation

The agent **may** create new issues, but must first post in GitHub Discussions
and explain to the maintainer: why no existing issue can carry the work (it must
not be expressible as remaining work), the proposed issue title, and the owned
behavior and acceptance boundary. Only **after the maintainer's explicit
agreement** may the agent create the issue. Before agreement, creation is
forbidden.

When creating, all structural constraints still apply: use the `Code work`
Issue Form, leave no required field as a placeholder, and declare the owned
behavior, impact area, non-goals, shared contracts, dependencies, and risk
level. When acceptance criteria are unfinished, update the existing issue
instead of opening a new one. A follow-up issue must explain why it stands
alone, link the original issue or PR, and define its own observable acceptance
criteria — an agent's follow-up goes through the same Discussions approval
flow. While waiting for approval, leave a review finding or comment under the
original issue or PR per §1.3; the current delivery is not blocked.

A PR carrying new task requirements may use `Refs` against an existing issue.

The Kanban board is maintained exclusively by the maintainer. GitHub Discussions
(enabled 2026-08-29) is the approval entry point for issue creation.

**Approval flow** (deliberately lightweight — fixed format plus the existing
audit workflow, no new automation):

1. The agent posts in the `Issue requests` category of Discussions, with the
   title format `[issue-request] <proposed issue title>` and a body of exactly
   three parts: why no existing issue can carry the work / the proposed owned
   behavior and acceptance boundary / related issues or PRs.
2. Wait for the maintainer to reply in the thread with explicit agreement
   (containing the word "approve" or "approved"). Before agreement, creation is
   forbidden.
3. After agreement, the agent creates the issue and fills the `Discussion
   approval` field in the issue body with the URL of that Discussion thread
   (the `Code work` Issue Form includes this field).
4. Mechanical check, attached to the **existing** Issue policy audit workflow
   (whose mandate is "may comment, may fail the check, must not close or
   rewrite issues"): an issue whose creator is not the maintainer and which lacks
   a `Discussion approval` link fails the check and receives a comment.
5. Optional hardening (not urgent): the audit verifies via GraphQL that the
   linked thread actually contains an approval reply from the maintainer.

**Discussions category governance**: categories are defined once —
`Issue requests` (issue-creation approval, above), `Design` (design discussion
and tonality consultation, see `frontend-design.md` section 11.7), and `Q&A`
(all other questions and uncertainty reports). Agent posts must go into the
matching category; agents must not create new categories.

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
