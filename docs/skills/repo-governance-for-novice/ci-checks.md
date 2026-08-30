# §10 Mechanical CI checks

This file defines the CI quality-profile mechanism and the checks attached to
it.

Quality-profile mechanism: the `github` profile uses the GitHub Actions checks
`Backend quality`, `Customer quality`, and `Northwind PR policy`; the
`circleci` profile uses the CircleCI equivalents; the `none` profile uses
`Northwind PR policy` to verify the required local quality-gate evidence.
`Kanban Sync` only manages Project status rules — it must not merge PRs, must
not change Draft status, and must not substitute Project status for acceptance
evidence.

New checks attach to the existing profile mechanism; do not build a separate
one:

- **OpenAPI drift check** (the backend is FastAPI, so the spec is generated
  for free):
  1. The repository commits a spec snapshot (such as
     `docs/openapi.snapshot.json`), updated in the same PR as any API change.
  2. A CI step exports the current application's `app.openapi()` and diffs it
     against the snapshot; a mismatch fails the check with the message "API
     shape changed; update the snapshot and `docs/api.md` together".
  3. `docs/api.md` remains the human-readable authority; the snapshot is only
     a mechanical sentinel and does not replace contract tests.
  4. Optional: lint the exported spec with spectral.
- Broken-link check for documentation: `lycheeverse/lychee-action` over
  `./docs/**/*.md`.
- Path coupling (fail when API code changes but the contract document does
  not):

```yaml
- name: Check docs updated with API changes
  run: |
    if git diff --name-only origin/main | grep -q "backend/"; then
      if ! git diff --name-only origin/main | grep -q "docs/api.md"; then
        echo "Backend routes changed but docs/api.md not updated"
        exit 1
      fi
    fi
```

  Coupling on the whole `backend/` directory may over-report; narrow it to the
  route/model subdirectories when implementing.

- Markdown lint: `DavidAnson/markdownlint-cli2-action`, linting only the
  markdown files changed in the current PR (no back-scan of existing
  documents, to avoid an enormous first run).
- PR policy adds the "read AGENT.md" field check (see `pr-workflow.md`
  section 5.4).
- **Commit message format check**: add a step to the existing PR policy
  workflow that matches the first line of every commit message in the PR
  against the following regex (shell implementation; no commitlint or Node
  toolchain):

```text
^(feat|fix|docs|chore|ci|test|refactor|perf|revert)(\((backend|frontend|docs|deploy|scripts|api|deps)\))?!?: .+
```

  Merge commits are exempt. The same step verifies breaking-change two-way
  consistency: when a commit carries `!` or a `BREAKING CHANGE:` footer, the
  PR body must contain a breaking-change declaration section (see
  `pr-workflow.md` section 5.1).
