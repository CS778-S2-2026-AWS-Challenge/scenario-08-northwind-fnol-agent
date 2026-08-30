# §6 Review, merge, and protection

This file defines who can approve, who can merge, and what to do when `main`
breaks.

## 6.1 Review rules

- Review against the exact current head, the changed files, the issue's
  acceptance criteria, contract impact, and CI results. Do not approve based on
  the description alone.
- When asked to review, an agent may submit `Approve` / `Comment` /
  `Changes requested`. **Approval is the highest routine review action, not a
  merge permission.**
- `Changes requested` is for concrete blocking defects, unsafe boundaries,
  contract mismatches, false evidence claims, missing required tests, or
  unmet acceptance criteria; distinguish blockers from optional improvements.
  `main` moving ahead, pending CI, preference-only refactors, optional
  evidence, and adjacent independent improvements are not, by themselves,
  grounds for `Changes requested`.
- A blocking review finding must name the exact reviewed head, the
  authoritative document relied on, the observed behavior, the expected
  behavior, the user or system impact, why it blocks the current acceptance,
  and the risk category. Suggesting an implementation is optional and does not
  transfer implementation ownership to the reviewer.
- Review the whole risk family in the first practical round. Blockers found
  only after an early review are labeled `late-discovered`; a reviewer agent's
  repeated finding must not be repackaged as the author's repeated mistake.
- Reviewers must take explicitly declared stacked parents into account; do not
  demand that a child PR duplicate its parent's dependencies to "look
  independent".
- If an authority or scope disagreement persists after two rounds of blocking
  review, stop agent escalation and request a human ruling.

## 6.2 Merge conditions

- The current `main` rule requires one approval from someone other than the
  last pusher.
- Resolve all review threads before merging. The person or authorized workflow
  performing the merge confirms that required checks and approvals apply to
  the final head.
- Required checks apply to the PR's final head; they must not be bypassed
  because local checks passed.

## 6.3 CODEOWNERS

`.github/CODEOWNERS` declares review authority over critical paths. Changes to
these paths must be approved by the code owner before merging, including PRs
opened by agents:

```text
/docs/skills/             @Ysoseri1224
/docs/README.md           @Ysoseri1224
/docs/archive/            @Ysoseri1224
/.github/                 @Ysoseri1224
/AGENT.md                 @Ysoseri1224
/CLAUDE.md                @Ysoseri1224
/AGENTS.md                @Ysoseri1224
/SPEC/                    @Ysoseri1224
/scripts/                 @Ysoseri1224
/.githooks/               @Ysoseri1224
/deploy/                  @Ysoseri1224
/.circleci/               @Ysoseri1224
```

The contract documents (`docs/api.md`, `docs/persistence-schema.md`, and
similar) deliberately have **no** owner: they change frequently with API and
persistence PRs, and whole-directory ownership would make the maintainer a
review bottleneck for the entire repository. Ownership protects the rule body
(`/docs/skills/`, the sole current source of governance rules), the
directory index (`/docs/README.md`), and archive integrity (`/docs/archive/`);
contract documents are covered by normal review plus the path-coupling CI
check (see `ci-checks.md`).

This list takes effect only when branch protection or a ruleset enables
"Require review from Code Owners" (a sub-option of "Require pull request
reviews"). CODEOWNERS fails **silently** when its syntax is invalid or an
owner lacks write permission; verify once after enabling.

Evaluated in the same governance window as CODEOWNERS:

- **Require approval of the most recent reviewable push**: the last pusher
  cannot approve their own latest change, preventing single-identity
  self-push-self-approve ("a new commit dismisses previous approvals" is
  already current behavior, see `pr-workflow.md` section 5.5).
- Rulesets note: classic branch protection allows only one rule per branch. If
  different branches later need different policies, layer new rules with
  **rulesets** instead of adding more classic rules.

## 6.4 Broken-main protocol

When a merged PR is found to break `main` (red CI, behavioral regression, or a
broken contract):

1. Report immediately under the original PR and its linked issue (symptoms,
   reproduction steps, suspected cause). Never stay silent.
2. Prefer a **revert PR**: use `git revert` to produce a reverse commit, open a
   PR through the normal process, and request review (use the `revert:` commit
   type, see `pr-workflow.md` section 5.1). It is **forbidden** to push
   directly to `main`, force-push, or bypass review in the name of an
   "emergency fix" — the protected-operations list (§1.2) remains fully in
   force during incidents.
3. After the revert merges, redo the fix in a new issue and PR; do not reuse
   the reverted branch (§4.3).
4. If the breakage affects other people's in-flight work, leave a comment
   under the affected PRs (the notification duty within §1.3 boundaries).
