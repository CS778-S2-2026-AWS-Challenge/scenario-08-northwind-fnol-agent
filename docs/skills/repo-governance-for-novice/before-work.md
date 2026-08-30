# §2 Before you start

This file defines which branch to synchronize, which files you must read, and
how to decide whether the current branch is usable.

## 2.1 Required reading

Before any substantive repository change, complete the following in order:

1. Read `AGENT.md` and every chapter file of this skill in full.
2. Run `git status --short --branch` to identify existing changes, the current
   branch, its base, and the relevant remote state, and preserve all existing
   worktree changes.
3. Read `README.md`, `SPEC/README.md`, the relevant product specifications, the
   current sprint documents, `docs/api.md`, and the source code and tests your
   task touches.
4. Read the README of every directory level involved (`docs/README.md` and
   other directory indexes).
5. Read the contract documents for your change area according to this matrix:

| Change area | Required sources |
| --- | --- |
| API routes, payloads, errors, authentication, or visibility | `docs/api.md` |
| Persistence records, revisions, keys, or access patterns | `docs/persistence-schema.md` |
| Fixtures, scenario data, test assertions, or test evidence | `docs/fixtures_convention.md` |
| Claim creation, routing, or provider adapters | `docs/claim-creation-boundary.md` |
| Agent behavior or permissions | `SPEC/03-agent-behaviour.md` and `SPEC/06-safety-and-governance.md` |
| Staff workbench or handoff | `SPEC/05-workbench-and-handoff.md` and the Workbench API in `docs/api.md` |

Historical prototype files, demo records, screenshots, and old planning
discussions are auxiliary evidence only. They must not silently override the
current specifications, contracts, or sprint plan.

## 2.2 Branch synchronization

Fetch `origin` before starting implementation, before the first push, and
before requesting review. Do not develop on or pull into local `main`; create a
short-lived branch from the latest `origin/main` (see `branching.md`). Before
switching or updating local `main`, check for associated worktrees.

## 2.3 Local quality gate

Before the first push, install dependencies from the repository root and run
`./scripts/check.ps1` (once dependencies are ready, rerun with `-SkipInstall`).
A failed or interrupted check is not a pass; fix the problem and rerun the full
gate before pushing or requesting review. Install the versioned pre-push hook
with `./scripts/install-git-hooks.ps1`.

`NORTHWIND_REMOTE_CI_PROVIDER` selects the quality profile (`none` / `github` /
`circleci`). `NORTHWIND_QUALITY_GATE_MODE=off` is an explicit maintenance
escape hatch and must not be used as an everyday development configuration.
When the full quality gate cannot run, keep the PR as Draft, record the
blocking reason, and do not request approval.

## 2.4 Context management

Manage context deliberately. If subagent capability is available, assign
different tasks to different subagents.

Subagents inherit exactly the same authority boundaries as the main agent
(§1). Splitting work across subagents must not be used to bypass authorization
checks.
