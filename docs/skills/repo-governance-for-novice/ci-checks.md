# §10 Mechanical CI checks

This file defines the CI quality-profile mechanism and the checks attached to
it.

Quality-profile mechanism: the `github` profile uses the GitHub Actions checks
`Backend quality` and `Northwind PR policy`; the `circleci` profile uses the
CircleCI equivalents plus the scoped documentation and automation checks. The
`none` profile means no remote code-quality provider is configured and cannot
supply merge evidence.
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

- **Impact-scoped backend tests**: pull requests use
  `scripts/select_backend_tests.py` to select direct consumer tests from the
  changed paths. Documentation-only changes may skip backend pytest. Shared
  domain models, repository protocols, runtime composition, dependency
  manifests, and unmapped backend changes select the complete suite. The
  `main` branch always runs the complete suite with coverage enforcement.
  Scoped PRs also scope Ruff and Mypy to changed Python files, while OpenAPI
  and AuditEvent snapshot checks run only when their contract can be affected.
  Scoped pytest runs intentionally omit the global coverage threshold; the
  full coverage gate remains on `main`. The selector is itself covered by
  tests and must never return an empty selection for a backend behavior change.

- **Path-filtered CircleCI workflows**: the setup configuration uses the
  CircleCI path-filtering continuation flow. A pull request creates only the
  affected quality workflow: backend, GitHub automation, documentation, or CI
  configuration. The policy workflow remains universal because every pull
  request must satisfy repository governance. A `main` push bypasses path
  filtering and runs the complete quality set.

  The backend workflow remains one executor so dependency installation and
  coverage setup are not duplicated, but its pytest command receives the
  individual files selected by `scripts/select_backend_tests.py`. Unselected
  test files are not collected or run. CI configuration changes do not force a
  full backend suite; they run the lightweight CI YAML and selector checks
  instead. Changes to the selector itself, shared dependencies, or shared
  domain contracts still force the complete backend suite because those paths
  can invalidate every test mapping.

  GitHub Actions uses the same boundary at workflow level: backend quality is
  created only for backend/test/contract changes, while documentation quality
  is created only for documentation and planning changes. Both workflows still
  run on `main` pushes. This keeps the two configured providers aligned without
  making a documentation change start the backend executor.

- **Two-signal backend coverage**: the existing total coverage floor and changed-line
  coverage answer different questions and are both required:
  1. Full backend runs keep `fail_under = 90` in `pyproject.toml`; this prevents the
     repository-wide signal from silently falling.
  2. Full and scoped backend runs also emit `coverage.json` and run
     `python scripts/check_diff_coverage.py --base origin/main --min 85`.
  3. Diff coverage measures only added executable Python lines under `backend/` in the
     exact PR diff. Deleted lines, non-Python changes, and lines omitted from coverage.py's
     executable-line report are excluded.
  4. The check is implemented inside the existing GitHub/CircleCI backend quality profiles;
     Codecov, Coveralls, and a second remote quality provider are not required.
  5. A passing diff check does not replace the total floor, and a passing total report does
     not prove that new behavior has focused tests. Both results must be recorded against the
     exact PR head.

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
