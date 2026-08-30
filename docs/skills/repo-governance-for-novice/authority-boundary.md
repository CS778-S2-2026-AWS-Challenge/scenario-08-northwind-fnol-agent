# §1 Authority and boundaries

This file defines what the agent may change, what it may not change, and which
operations require confirmation from the current user.

## 1.1 Credentials are not authorization

GitHub credentials only prove that an account **can** perform an operation.
They never prove that the current user **authorized** a person or an agent to
perform it. Before editing files or performing any remote change, confirm: the
current issue and its owner, the branch and PR being modified, the declared
non-goals, and any active issue or PR that owns overlapping behavior.

Do not infer authorization from any of the following: an issue being assigned
to you, a broad instruction such as "get the PR done", passing CI, a received
approval, an available `gh` login session, or a previous authorization.
Authorization is **per-operation**; one authorization does not carry over to
the next protected operation.

## 1.2 Protected operations

Without the current user's explicit authorization for the specific operation,
the agent must not perform any of the following — through `gh`, Git, the API,
a browser, `workflow-dispatch`, or any automated equivalent:

- Merge a PR, enable auto-merge, enter a merge queue, or push directly to `main`.
- Force-push (including `--force-with-lease`), delete branches, discard work,
  or rewrite shared history.
- Convert a PR between Draft and Ready for review.
- Close or reopen an issue or PR, or change a PR base.
- Manually change Kanban status, fields, assignees, estimates, or dependencies.
- Run `gh issue edit`, `gh pr edit`, or `gh project` against another
  contributor's work.
- Modify branch protection, required checks, repository rulesets, Actions
  permissions, secrets, environments, or other access controls.
- Deploy, release, rotate credentials, or change external services or
  production-like datasets.

Repository automation may update Kanban fields according to its reviewed
workflows; this does not authorize the agent to make the same changes manually.

The agent must not make any manual modification to the Kanban board, but it
**must read** the Kanban board.

## 1.3 Ownership boundaries

Finding a defect, reviewing a change, holding repository permissions, receiving
an approval, or having performed a similar operation earlier — none of these
transfer implementation ownership. Record out-of-scope defects as review
findings or follow-up issues; do not implement them, push to another person's
branch, modify another person's issue or PR metadata, resolve another person's
review threads, or expand the current deliverable without the explicit consent
of both the affected owner and the current user.

Do not interfere with issues that are not assigned to you. If your code depends
on such an issue, leave a comment under that issue (its corresponding PR may
not exist yet).

An issue's assignee and its `Owner or responsible contributor` field define who
drives its implementation. When there are multiple owners, a lead and each
person's bounded responsibility must be declared.

When ownership or scope is disputed, stop implementing and request a human
ruling. A coding agent or reviewer agent must not "resolve" the dispute by
continuing to change the repository.
