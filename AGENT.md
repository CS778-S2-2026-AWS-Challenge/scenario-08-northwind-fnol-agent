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
