# §5 Commits and pull requests

This file defines commit messages, PR titles and bodies, review requests, and
what to do when CI fails.

## 5.1 Commits

Write commit messages in English. Adopt **Conventional Commits v1.0.0**. Its
value here is a readable commit history; it is not coupled to SemVer or
changelog generation (neither is adopted), but the structured history keeps the
option open to generate a full changelog offline at any future point with tools
such as git-cliff.

Rules:

- **Format**: `<type>[(scope)][!]: <description>`, with optional body and
  footer each separated by a blank line. The colon and space between type and
  description are mandatory; the type is always lowercase.
- **Type allowlist** (8): `feat` `fix` `docs` `chore` `ci` `test` `refactor`
  `perf`. Mind the word-form mapping: the branch prefix is `feature/`, but the
  commit type must be `feat` (the specification mandates that form). `style`
  is not available (redundant under ruff auto-formatting; use `chore`).
- **Scope is optional**; when used, it must come from the enumeration
  `backend` `frontend` `docs` `deploy` `scripts` `api` `deps`. Omit the scope
  for cross-directory changes.
- **Breaking-change two-way consistency**: any commit carrying `!` or an
  uppercase `BREAKING CHANGE:` footer ⇔ the PR Summary must contain an
  explicit breaking-change declaration section (see `docs-contract.md`
  section 7.1). Missing either side is an inconsistency.
- **Reverts**: use the `revert:` type, and list the reverted commit SHAs in a
  `Refs:` footer.
- **One commit does one kind of thing**: when a change matches multiple types,
  split it into multiple commits.
- **Self-check before pushing**: verify each commit message against the rules
  (regex in `ci-checks.md`) before pushing; do not rely on after-the-fact
  rebase rewrites.

## 5.2 PR types and structure

Do not create stacked PRs unless necessary; when stacking is genuinely needed,
declare the parent PR and the merge order. Do not use non-standard PR types
such as "replay" PRs.

- A PR must name one primary issue and describe the behavior it owns,
  non-goals, expected impact area, shared contracts, dependencies, and
  overlapping in-flight work. Touching a file does not mean owning every
  behavior implemented in it.
- A Draft PR may be opened while implementation, verification, or dependencies
  are unfinished, but its Summary must state the current deliverable and the
  remaining work. Leave Draft only when the required content and evidence
  describe the current head.
- The PR description must describe the current head, not an earlier commit.
  After every substantive change, update the commands, test counts,
  screenshots, limitations, and dependency notes.
- A non-Draft PR must include, per the repository PR template: summary,
  acceptance evidence, local validation, contract and data impact,
  dependencies, and remaining risks.

Confirm that your changes do not affect unrelated code. If they do, state the
impact explicitly in the PR.

**PR size budget**: a soft cap of 400 changed lines per PR (additions plus
deletions; lockfiles, generated snapshots, and `docs/archive/` moves are
exempt). Above the cap, the Summary must explain why the PR cannot be split.
An oversized PR that could have been split but was not is a legitimate reason
for `Changes requested` (see `review-merge.md` section 6.1).

## 5.3 Quality gate and CI failures

Run the full local quality gate before pushing and record the exact command and
result in the PR description (`./scripts/check.ps1` + `Result: PASS`). Never
present results from another branch, worktree, commit, or environment as
current evidence. After pushing, monitor CI progress; if any check fails,
**rework immediately** — fix and rerun the full gate rather than waiting for
review to point it out.

A successful build or API-level assertion does not prove a claimant or staff
user journey; the type of evidence must match the behavior being claimed.

## 5.4 PR template additions (merged into the existing template, not replacing it)

Add the following on top of the existing template (Linked issue / Summary /
Local validation / Contract and data impact / Governance exception):

```markdown
## Governance confirmation
- [ ] I have read AGENT.md and the governance skill in full (state the version
      read, vX.Y). (PR policy requires this box to be checked; during the
      transition period before the governance PR lands, this means AGENT.md
      and docs/repo_rule.md.)

## Documentation sync check
- [ ] This PR contains no changes that require documentation updates
- [ ] Updated docs/api.md (API contract changes)
- [ ] Updated docs/persistence-schema.md (persistence changes)
- [ ] Updated docs/README.md (documents added, replaced, moved, or archived)

## Impact statement
- [ ] I confirmed the changes do not affect unrelated code; any impact is
      described in the Summary
```

PR policy adds a "read AGENT.md" field whose value must be true to pass.
Like the existing local-validation evidence, a checked box cannot prove that
someone actually ran the commands; its role is a mandatory reminder, and
independent review remains the last line of defense.

## 5.5 Requesting review

When the work is ready, choose a reviewer who can check the affected behavior
or consuming modules and who is available at the time; do not form fixed
reviewer pairs. Request via GitHub or
`gh pr edit <number> --add-reviewer <login>`. A new commit dismisses previous
approvals; re-request review after pushing.
