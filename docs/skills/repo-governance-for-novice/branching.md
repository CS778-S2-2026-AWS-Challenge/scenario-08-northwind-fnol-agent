# §4 Branching and parallel development

This file defines branch naming, whether one task allows multiple agents, and
how to reduce conflicts.

## 4.1 Create a branch

Do not develop on `main`. Fetch the remote, then create a short-lived branch
from the latest `origin/main`:

```powershell
git fetch origin --prune
git switch -c feature/short-topic origin/main
```

This method also works when another worktree occupies local `main`.

## 4.2 Branch naming

Use short-lived branches with the prefixes `feature/<topic>`, `fix/<topic>`,
`docs/<topic>`, or `chore/<topic>`.

## 4.3 Branch discipline

- Protect the current user's and teammates' changes. Do not reset, discard,
  overwrite, or reformat unrelated work. Pull, fetch, rebase, and merge must
  not overwrite uncommitted or unreviewed work; when overlapping files have
  unclear ownership, clarify first, then act.
- One branch and one PR carry exactly one coherent result. Do not mix in
  drive-by refactors, generated files, deployment changes, or unrelated
  documentation.
- Do not continue new work on stale or unrelated branches; do not reuse the
  branch of a merged or closed PR.
- When stacking intentionally, declare the parent PR and the merge order.
  Undeclared non-main bases and accidental branch chains are unacceptable.
- Follow the line-ending policy in `.gitattributes`; use LF for source code,
  documentation, and workflow files.

## 4.4 Parallel development and conflict prevention

Multiple agents and subagents are a **context-management tool**, not a unit of
ownership. The unit of ownership is always the issue plus its branch (§1.3,
§3).

- Within a single task, subagents may split sub-work (research, tests, and
  review each to its own subagent). Subagents inherit the main agent's full
  authority boundaries (§1.2); splitting must not bypass authorization checks.
- Work on different features should happen in **separate sessions**, each with
  its own issue and branch. Do not mix changes for multiple issues in one
  context — one branch and one PR carry one coherent result.
- Reduce conflicts through boundaries, not coordination: split parallel work
  along independently acceptable boundaries (the issue's non-goals and impact
  area fields). When your change paths overlap another person's active PR,
  apply the overlap rule at the end of this section; when ownership is unclear,
  clarify first (§4.3).

`main` moving ahead is, by itself, only a signal. It becomes a blocker — and
the branch must be updated — only when `main` overlaps the PR's change paths,
or has changed a dependency, shared contract, schema, migration, package
dependency, or build configuration that the PR declares.
