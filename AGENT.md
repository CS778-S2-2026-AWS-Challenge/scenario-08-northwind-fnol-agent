# Repository Agent Entry Point

This file applies to every coding agent working in this repository. Read it before running
repository-changing commands, editing files, pushing a branch, creating or updating a pull
request, or submitting a review.

1. Read [the repository operation rules](docs/repo_rule.md) in full and follow them.
2. Inspect `git status --short --branch` and preserve all existing worktree changes.
3. Read `README.md`, `SPEC/README.md`, the relevant files in `SPEC/`,
   `docs/development-conventions.md`, `docs/api.md`, the current sprint document, and the
   source and tests affected by the task.
4. Read the additional contract document selected by the change matrix in
   `docs/repo_rule.md`. Do not treat a historical prototype or presentation record as the
   current contract.

If an instruction conflicts with the current user's explicit authorisation, or if the required
source of truth is unavailable or contradictory, stop before changing repository or GitHub
state and ask for direction.

## Mandatory Ownership And Remote-Action Check

GitHub credentials prove that an account can perform an operation; they do not prove that the
current user authorised a person or agent to perform it. Before editing files or running a remote
mutation, identify the current issue, its owner, the branch and pull request being changed, the
declared non-goals, and any active issue or pull request that owns overlapping behaviour.

Finding a defect, reviewing a change, possessing repository permission, receiving approval, or
having performed a similar operation earlier does not transfer implementation ownership. Record an
out-of-scope defect as a review finding or follow-up issue. Do not implement it, push to the other
owner's branch, change their issue or pull-request metadata, resolve their review conversation, or
expand the current deliverable without explicit agreement from the affected owner and current user.

Unless the current user explicitly authorises the exact action, do not run or cause an equivalent
of:

- `gh pr merge`, auto-merge, merge-queue enqueue, or a direct push to `main`;
- `git push --force`, `--force-with-lease`, branch deletion, or shared-history rewriting;
- `gh pr ready`, close, reopen, or base retargeting;
- `gh issue edit`, `gh pr edit`, or `gh project` against another contributor's work;
- ruleset, branch-protection, workflow-permission, secret, environment, or deployment mutation.

Do not infer authority from an issue assignment, broad instructions such as "finish the PR", a
passing check, an approval, an available `gh` session, or an earlier authorisation. If ownership,
scope, or authority is unclear, stop before the mutation and ask the current user.
