# §7 Documentation and code change boundaries

This file defines which changes must update documentation in the same PR, and
which directories need extra scrutiny.

## 7.1 Shared contracts update in the same PR

Claim state, API schemas, agent actions, reason codes, visibility, persistence
revisions, fixture shapes, and claimant/staff projections are all shared
contracts.

| Change type | Must update in the **same PR** |
| --- | --- |
| API contract change | Routes and models, `docs/api.md`, shared domain fields, affected claimant/staff consumers, fixtures, contract tests |
| Persistence change | `docs/persistence-schema.md`, repository protocols and adapters, revision and ownership behavior, fixtures, tests |
| Fixture / test contract change | Follow `docs/fixtures_convention.md`; runtime demo data, static fixtures, executable assertions, test doubles, and validation evidence keep independent ownership and must not stand in for one another |
| Product scope change | Belongs in `SPEC/` |
| Time commitment change | Belongs in `sprint/` |
| Adding, replacing, moving, or archiving any document | Update `docs/README.md` |

Do not create private route-level enums, duplicated field names, or
representations that diverge across frontend, backend, agent, persistence,
fixtures, and tests. Engineering documents must not silently redefine SPEC or
sprint.

Make "does this need a documentation update" a mechanically checkable
condition rather than a matter of teammate diligence. Additional triggers:

| Change type | Documents to update |
| --- | --- |
| New environment variable or configuration item | `.env.example` + the relevant `README.md` section |
| New dependency (especially with setup steps) | `README.md` |
| Deployment process change | Documents under `deploy/` + `docs/runtime-deployment-profiles.md` |
| Breaking change (of any kind) | Explicit breaking-change declaration in the PR Summary + all affected documents |

**Changes that need no documentation update**: pure internal refactors (no
interface or behavior change), test-file changes, style or formatting
adjustments, and bug fixes (unless the fix changes externally visible
behavior).

## 7.2 The docs directory layers

- Current engineering documents live at the `docs/` root; target architecture
  and rationale in `docs/design/`; the current evidence ledger in
  `docs/status/`; research inputs in `docs/research/`.
- Sprint-day plans, task-level verification reports, demo runbooks,
  screenshots, and exact-commit evidence go in `docs/archive/sprint-N/`. Do
  **not** add `day*`, `d4-*`, task codes, or demo evidence files to the
  `docs/` root.
- Historical records must not override current specifications, APIs, data
  contracts, permission rules, or sprint commitments.

## 7.3 Directories that need extra scrutiny

After the agent finishes, inspect the PR diff and confirm nothing outside the
intended scope changed. Check `.github/`, `deploy/`, `.circleci/`, `scripts/`,
`.githooks/`, and dependency manifests (`pyproject.toml` and similar) with
particular care. These paths are also protected by CODEOWNERS (see
`review-merge.md` section 6.3).

**Dependency-introduction discipline**: any new dependency (pip / npm) must be
justified in the PR: its purpose and why existing dependencies cannot satisfy
it, the alternatives considered, its license, and its maintenance status
(latest release / activity). Prefer reusing existing dependencies and the
standard library. If the dependency has setup steps, update `README.md` in the
same PR (section 7.1).
