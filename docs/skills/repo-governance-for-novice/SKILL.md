---
name: repo-governance-for-novice
description: Repository governance for the Northwind FNOL repository (scenario-08). Required before ANY repository operation — editing files, pushing, branching, opening or updating a pull request, reviewing, creating or commenting on issues, merging, or running any gh command. Defines authority boundaries, required reading, task entry, branching, commit and PR rules, review and merge, documentation sync, credentials, CI checks, and frontend and backend design standards.
---

# Northwind FNOL repository governance

Version: v1.4 · 2026-09-13

This version line is incremented whenever a rule changes substantively. The
"Governance confirmation" section of the PR template cites the version you read
(see `pr-workflow.md`, section 5.4), so audits can tell which edition of the
rules an agent followed.

## General principles

The rule text in this skill is self-contained. You only need to access an
external resource when a clause **explicitly marks it MUST-READ**. The single
MUST-READ resource in this entire skill is the W3C ARIA Authoring Practices
Guide (APG), see `frontend-design.md` section 11.2. After reading a MUST-READ
resource, record a short decision note in the PR description (which pattern
requirements you adopted, any deviations, and why); no prior confirmation step
is required. If a resource cannot be accessed, state plainly that it is
unreachable and stop relying on it — never fabricate its content from memory.

**Terminology.** Two roles appear throughout this skill and are not
interchangeable:

- **Current user**: the human driving this agent session. The source of
  per-operation authorization (see `authority-boundary.md`).
- **Maintainer**: @Ysoseri1224. The sole decision-maker for the Kanban board,
  governance rulings, and one-time design decisions. This is the only place in
  the rule text where the maintainer's handle is defined; every other rule
  refers to "the maintainer" (quoted repository configuration, such as the
  CODEOWNERS block, keeps the literal handle).

**Sole current source.** Once this skill takes effect, it is the only current
source of governance rules. In this repository it lives at
`docs/skills/repo-governance-for-novice/`. The former governance documents
(`docs/repo_rule.md` and `docs/development-conventions.md`) are moved into
`docs/archive/governance/` and are never revised again; they remain historical
reference only. `AGENT.md` is kept as the entry point and rewritten as an
index pointing to this skill. Where an archived document disagrees with this
skill, this skill prevails without exception.

**Citation integrity.** Every file path, line number, issue or PR number, and
document section you cite in a PR, issue, comment, or Discussion must be
verified with tools (reading the file, `gh` queries, and so on) before you cite
it. If you cannot verify a reference, do not cite it. Never fabricate citations
from memory or by guessing.

The citation-integrity rule does not apply to the links inside the
**References** section at the end of some skill files. References record
provenance only, for consultation when a rule is disputed; the rule text in
this skill is authoritative and self-contained, and you should not fetch those
links during normal work.

**Stop and ask.** When an instruction conflicts with the current user's
explicit authorization, or when the factual sources you need are unavailable
or contradict each other, stop before changing the repository or GitHub state
and ask for direction. Do not hide uncertainty behind a passing build, a Draft
status, or a vague statement that "the team will handle it later".

**Language.** Repository content, issue and PR text, review comments, commit
messages, and test evidence must be written in English.

## File index

| File | Scope |
| --- | --- |
| `authority-boundary.md` | §1 What the agent may and may not change; operations that require explicit authorization |
| `before-work.md` | §2 Required reading, branch synchronization, validation, context management |
| `issue-kanban.md` | §3 Task entry: responsibilities of issues, Kanban, and technical-alignment Discussions |
| `branching.md` | §4 Branch creation, naming, discipline, and parallel development |
| `pr-workflow.md` | §5 Commits, PR structure, validation, PR template, requesting review |
| `review-merge.md` | §6 Review rules, merge conditions, CODEOWNERS, broken-main protocol |
| `docs-contract.md` | §7 Which changes must update which documents; directories needing extra scrutiny |
| `credentials-risk.md` | §8 Credentials, high-risk operations, data visibility |
| `docs-standards.md` | §9 Documentation types, English writing style, API documentation policy |
| `ci-checks.md` | §10 Mechanical CI checks and how new checks attach to the quality profiles |
| `frontend-design.md` | §11 Frontend design standards (tokens, interaction, accessibility, typography, visuals) |
| `backend-design.md` | §12 Backend design standards (API design, architecture, data modeling, code style) |

## Scenario quick reference

- **Starting a new task**: read `before-work.md`, then `issue-kanban.md`, then
  `branching.md`.
- **Before committing or opening a PR**: read `pr-workflow.md`,
  `docs-contract.md`, and `ci-checks.md`.
- **Asked to review a PR**: read `review-merge.md`.
- **Touching frontend code**: read `frontend-design.md` first.
- **Touching backend code**: read `backend-design.md` first.
- **Anything involving credentials, deployment, force-push, settings, or other
  protected operations**: read `authority-boundary.md` and
  `credentials-risk.md` before acting.

## Adapting this skill to another repository

This skill is written for the Northwind FNOL repository, but its structure is
reusable. To port it, edit these anchors:

- The maintainer handle in the Terminology block above (its single definition
  point in rule text).
- The quoted CODEOWNERS block in `review-merge.md` section 6.3.
- The Kanban project URL in `issue-kanban.md` section 3.1.
- Repository-specific paths and commands: the contract documents
  (`docs/api.md` and others), focused local checks, and the remote CI check names in
  `ci-checks.md`.
- The stack descriptions and stack-bound rules in `frontend-design.md` and
  `backend-design.md`.
