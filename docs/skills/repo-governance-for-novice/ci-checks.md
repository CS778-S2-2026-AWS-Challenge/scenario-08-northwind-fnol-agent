# §10 Mechanical CI checks

This file defines the CI quality-profile mechanism and the checks attached to
it.

Quality-profile mechanism: the `github` profile uses the GitHub Actions checks
`Backend quality`, `Customer quality`, and `Northwind PR policy`; the
`circleci` profile uses the CircleCI equivalents. The `none` profile means no remote
code-quality provider is configured and cannot supply merge evidence.
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
- **AuditEvent envelope drift check**: the provider-neutral audit envelope is
  defined by the Pydantic model in `backend/domain/audit.py`. The committed
  `docs/contracts/audit-event.schema.json` snapshot is regenerated with
  `python scripts/export_audit_contract.py`; the backend quality profile runs
  the script with `--check`, and a snapshot change must update
  `docs/persistence-schema.md` in the same PR. The snapshot checks structure
  only; event meaning, visibility, authorisation, retention, and transaction
  boundaries remain governed by the persistence contract and tests.
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

- **Job planning**: a setup pipeline (`.circleci/config.yml` running
  `scripts/ci_plan.py`) decides from the changed paths which workflows exist,
  then continues with `.circleci/continue_config.yml`. A job that a change does
  not need is never created; do not add jobs that start and then skip
  themselves. `main` creates every job; the daily schedule creates only the full
  backend suite; a change to the CI definition creates everything.

- **Coverage-selected backend tests**: every merge to `main` and the daily
  schedule run the whole backend suite in parallel containers with
  `--cov-context=test`. `scripts/backend_test_map.py` turns the result into a
  map from each backend line to the test files that executed it, cached for pull
  requests. On a pull request `scripts/select_backend_tests.py` runs:
  1. the test files that executed the changed lines (for a line that runs only
     at import time, such as a signature or class body, every test file that
     uses the module);
  2. the test files the pull request changes, and the test files that import a
     changed test-support or script module;
  3. the whole suite when shared test infrastructure changes (`tests/conftest.py`,
     `pyproject.toml`, backend requirements, `.circleci/`, the selector itself)
     or no map is available.
  There is no hand-written path-to-test table to maintain. Ruff and Mypy
  receive only changed Python files, while OpenAPI and AuditEvent snapshot
  checks run only when their contract can be affected (always on `main`).

- **Full-suite failures**: when the full suite fails on `main` or on the
  schedule, CI opens a GitHub issue titled "Full backend suite fails on main",
  or comments on the open one. Fix `main` or mark a test that fails for a known
  product defect `xfail(strict=True)` with the defect's issue; never delete a
  failing test to make the run green.

- **Changed-line backend coverage**: at least 85% of the executable Python lines
  a pull request adds under `backend/` must be executed by the selected tests
  (`python scripts/check_diff_coverage.py --base origin/main --min 85`).
  Because the selection includes the existing tests that already cover those
  lines, **reuse comes first**: if existing tests execute the changed lines, add
  no new test. When a new case is needed, add it to the test file of the module
  it exercises; create a new test file only for a module or behaviour that has
  none, and name it after that module or behaviour, never after a PR, issue,
  week, or prompt version. CI prints non-blocking advice for new test files that
  break this naming rule or extend an existing file's name
  (`scripts/check_test_layout.py`). Deleted lines, non-Python changes, and
  non-executable lines are excluded from the denominator.

- Markdown lint: `DavidAnson/markdownlint-cli2-action`, linting only the
  markdown files changed in the current PR (no back-scan of existing
  documents, to avoid an enormous first run).
- PR policy adds the "read AGENT.md" field check (see `pr-workflow.md`
  section 5.4).
- **Commit message format check**: the Cloudflare Worker checks the first line
  of every commit in the PR as part of the `Northwind PR policy` status
  (`.github/scripts/commit_policy.cjs`) against the following regex:

```text
^(feat|fix|docs|chore|ci|test|refactor|perf|revert)(\((backend|frontend|docs|deploy|scripts|api|deps)\))?!?: .+
```

  Merge commits are exempt. The same check verifies breaking-change two-way
  consistency: when a commit carries `!` or a `BREAKING CHANGE:` footer, the
  PR body must contain a breaking-change declaration section (see
  `pr-workflow.md` section 5.1).
