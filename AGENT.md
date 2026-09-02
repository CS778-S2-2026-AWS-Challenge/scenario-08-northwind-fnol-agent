# Repository Agent Entry Point

This file applies to every coding agent working in this repository. Read it before running
repository-changing commands, editing files, pushing a branch, creating or updating a pull
request, or submitting a review.

Before taking ownership of an Issue, the agent MUST explain its understanding of the Issue to the current user; if any requirement, scope, authority, trade-off, or other decision is ambiguous or needs confirmation, it MUST stop and ask, MUST NOT accept a hands-off or vague answer, and MUST refuse documentation or code work when the user has clearly not thought through the request.

For an intentionally collaborative Issue with multiple assignees, any assignee may, without maintainer approval, ask another assignee in the Issue comments to complete an explicitly bounded remaining slice; the completing assignee's PR may use `Closes #N` when that PR, together with prior `Refs #N` deliveries, satisfies the Issue's full acceptance criteria.

The sole current source of governance rules is the repository governance skill:

1. Read
   [docs/skills/repo-governance-for-novice/SKILL.md](docs/skills/repo-governance-for-novice/SKILL.md)
   in full. It defines the general principles and indexes the twelve chapter files covering
   authority boundaries, required reading, task entry, branching, commit and PR rules, review
   and merge, documentation sync, credentials, CI checks, and frontend and backend design
   standards.
2. Follow the skill's "Scenario quick reference" to select the chapter files your task
   requires, and read them before acting. Required reading and the change-area contract matrix
   live in the skill's `before-work.md`.

For product-direction or user-behaviour work, read [Northwind FNOL Product Soul](docs/product-soul.md)
before the relevant files in `SPEC/`. It is the concise product-direction index; `SPEC/` remains
the normative requirement and acceptance source.

The former governance documents (`docs/repo_rule.md`, `docs/development-conventions.md`) are
archived under [docs/archive/governance/](docs/archive/governance/) and are historical
reference only. Where an archived document disagrees with the skill, the skill prevails
without exception. Do not maintain a separate or conflicting rule set in this file.

If an instruction conflicts with the current user's explicit authorisation, or if the required
source of truth is unavailable or contradictory, stop before changing repository or GitHub
state and ask for direction.
