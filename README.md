# Northwind FNOL Agent

Northwind FNOL Agent is a trusted, adaptive First Notice of Loss service for Northwind Insurance. A claimant explains a loss in their own words while the system handles insurance structure, evidence tracking, authorised knowledge retrieval, and next-step planning internally.

The product is designed to sit between a rigid web form and a fully manual phone process. Straightforward work can progress with minimal questioning, while ambiguity, urgency, support needs, and high-impact decisions are transferred to staff with a source-preserving claim context. The claimant should not have to manage the insurer's process or repeat confirmed information when work changes hands.

## Product Goal

The service should:

- reduce avoidable claimant questions, process interpretation, repetition, and waiting;
- progress a claim when the information is sufficient for the next safe action, even if later evidence is still pending;
- preserve context across sessions and human handoffs;
- give claims staff a workbench backed by the same claim state used by the Agent;
- provide a governed administration and control plane for versioned model, data, knowledge, rule, integration, access, evaluation, and operational configuration as the product direction develops;
- keep coverage, fraud, safety, and other high-impact decisions within explicit business and human-review boundaries;
- make claimant effort, human effort, and agent cost observable.

## Users

- **Claimants** report an incident naturally, correct material misunderstandings, provide evidence, and follow progress without managing the internal process.
- **Claims professionals** review ambiguity, risk signals, handoffs, and claim actions without recollecting known facts.
- **Claims operations** owns the process, service quality, governance, and operating efficiency.
- **System administrators and approved knowledge managers** validate and publish system configuration, knowledge, integrations, and access through the Control Plane.
- **Approved service participants** may later receive task-specific claim context for assessment, repair, or another authorised downstream action.

## Current Stage

The project is in Sprint 3 and is advancing the MVP into a repeatable Validation Prototype. Current work validates the Agent, claimant and staff experiences, shared Claim Context, knowledge retrieval, data runtime profiles, Control Plane, third-party service boundaries, and confirmed AWS capabilities across representative motor, home, and contents paths.

Controlled scenarios and fixture adapters remain valid development tools, but they must be labelled honestly. Cloud services, Northwind data, provider schemas, permissions, production rules, and deployment readiness are not claimed until verified.

The product direction is summarised in [Northwind FNOL Product Soul](docs/product-soul.md). Detailed product requirements are maintained in `SPEC/`, sprint plans in `sprint/`, engineering and research documentation in `docs/`, and demonstrators in `prototype/`.

Frontend and frontend-runtime design work follows the [Frontend and Runtime Quality Standard](docs/frontend-and-runtime-quality-standard.md). Read it before changing claimant or Workbench routes, components, tokens, state handling, Agent integration, or Runtime-facing behavior; historical single-page prototypes are migration evidence only.

## Repository Operation Rules

All contributors and coding agents must follow the
[repository governance skill](docs/skills/repo-governance-for-novice/SKILL.md).
Coding agents enter through [AGENT.md](AGENT.md), which routes to the skill and its file index.
Every pull request must reference a repository issue and pass the configured remote quality
checks. Coding agents must not merge pull requests or change Draft status without explicit current
authorisation.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI transport, application services, domain rules, persistence ports, and replaceable adapters |
| `archive/customer/` | Archived React/Vite claimant implementation; not a current runtime entry point |
| `archive/workbench/` | Archived React/Vite Claims Workbench implementation; not a current runtime entry point |
| `archive/admin/` | Archived React/Vite Control Plane implementation; not a current runtime entry point |
| `archive/` | Historical frontend source preserved for reference and excluded from product CI |
| `employee/` | Deprecated redirect shell and legacy migration inventory; not a current product entry point |
| `frontend/shared/` | Shared semantic design tokens consumed by claimant and staff clients |
| `prototype/` | Historical static interaction demonstrators |
| `tests/` | Backend unit, middleware, API, and fixture tests |
| `.circleci/` | External backend, PR-policy, documentation, and GitHub-automation quality jobs |
| `automation/github-automation/` | External GitHub webhook, PR policy, and Project 12 synchronization Worker |
| `SPEC/` | Current product requirements and acceptance scenarios |
| `docs/` | Product direction, API contract, engineering conventions, and research material |
| `sprint/` | Time-bound sprint commitments and delivery flow |
| `scripts/` | Repository-level development and verification commands |

Backend packages have fixed responsibilities:

- `backend/api/` validates and translates HTTP requests and responses.
- `backend/core/` owns configuration and cross-cutting HTTP behaviour.
- `backend/domain/` owns provider-independent claim state and business rules.
- `backend/services/` coordinates domain rules and ports for application use cases.
- `backend/repositories/` defines persistence protocols.
- `backend/adapters/` implements replaceable external and provider integrations.

Route handlers must not define private domain enums or access a provider SDK directly.

## Local Development

Use Python 3.12 for the current backend and repository tooling. The former claimant, Workbench,
and Control Plane packages are preserved under `archive/` for historical reference and are not
installed or started as current product entry points.

On Windows, install the backend development dependencies from the repository root with:

```powershell
py -3.12 -m pip install -r backend/requirements-dev.txt
```

Start the backend:

```powershell
py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

To run a configured model profile from the ignored project `.env`, load it explicitly:

```powershell
py -3.12 -m uvicorn backend.main:app --env-file .env --reload --host 127.0.0.1 --port 8000
```

Deployment environments inject the same variable names through their secret and configuration
mechanisms; they must not package the local `.env` file.

The default object store remains the deterministic fixture adapter. To run the same
FastAPI evidence flow against local MinIO, start the packaged service and configure the
`s3_compatible` adapter as described in
[MinIO Object-Storage Boundary](docs/minio-object-storage.md).

To run the bounded local MVP persistence path, start the local MongoDB replica set and MinIO
initialisers, then use `deploy/runtime/local-mvp.env.example`. The repeatable
`py -3.12 scripts/run_local_mvp_smoke.py` check verifies MongoDB-backed claimant/staff recovery,
revision and idempotency behaviour, protected MinIO evidence bytes, and governed knowledge
retrieval. Policy/history remain synthetic. After those checks pass,
`py -3.12 scripts/run_local_model_mvp_smoke.py` verifies the merged provider-neutral model path
against the same MongoDB composition with a deterministic OpenAI-compatible transport. It covers
accepted-turn provenance, restart recovery, replay without a second model call, stale revisions,
and atomic timeout, malformed, incomplete, and unauthorised-output failures. This deterministic
transport is repeatable contract evidence, not a live-provider claim; a live run additionally
requires an approved endpoint and secret supplied through the documented model environment.

To check changed backend lines locally after a coverage run, use:

```powershell
py -3.12 -m pytest --cov=backend --cov-report=term-missing --cov-report=json:coverage.json tests
py -3.12 scripts/check_diff_coverage.py --coverage coverage.json --base origin/main --min 85
```

The repository keeps two separate backend coverage signals. The full suite must continue to
meet the existing 90% total coverage floor. The diff check requires at least 85% of executable
lines added or modified under `backend/` to be covered by the current test run. Deleted lines,
non-Python files, and non-executable lines are not part of the diff denominator.

The archived frontend packages are not supported local entry points. Do not add new product
behaviour to `archive/` or the compatibility-only files under `employee/`.

Copy the non-secret values from `.env.example` into the process environment when overrides are needed. Local development permits any CORS origin by default and does not enable credentialed cross-origin requests.

Developer mode uses separate synthetic administrator and release-approver tokens. The
administrator may author and validate configuration, while
`NORTHWIND_SYNTHETIC_RELEASE_APPROVER_TOKEN` represents the independent identity required to
publish a high-impact configuration. These synthetic tokens are local test identities only and
must not be used as a production approval mechanism.

## Verification

CircleCI is the authoritative repository quality provider. Its workflow checks backend formatting,
linting, types, tests, PR policy, GitHub automation, and documentation for every pull request.
The archived frontend source is not a CI target. Backend pull requests use impact-scoped tests selected by
`scripts/select_backend_tests.py`; shared-contract and unmapped backend changes run the complete
suite. Scoped PRs also limit Ruff and Mypy to changed Python files and run contract snapshot checks
only when their inputs are affected. Documentation-only PRs skip the Python backend quality chain.
The `main` branch retains the complete backend suite with coverage enforcement.

For focused local backend verification while developing, run the checks affected by the change:

```powershell
py -3.12 -m ruff format --check .
py -3.12 -m ruff check .
py -3.12 -m mypy backend tests
py -3.12 -m pytest
```

The GitHub automation package retains its own `npm` verification commands. Local focused checks
shorten feedback time but do not replace the exact-head CircleCI result required for review and merge.

Run the synthetic integration fixtures from the repository root with:

```powershell
py -3.12 scripts/run_scenarios.py
```

Validate the reusable evidence lifecycle catalogue with:

```powershell
py -3.12 scripts/run_evidence_fixtures.py
```

Validate evidence visibility and the five business-path entry states with:

```powershell
py -3.12 scripts/run_evidence_visibility_fixtures.py
```

Every invocation creates a fresh in-memory repository, so rerunning the command
is a clean reset for that isolated fixture verifier. It does not reset a running
FastAPI demo process.

To reset the running local demo backend, start the backend and run:

```powershell
py -3.12 scripts/reset_demo.py
```

The command clears only the in-memory fixture repository and mock adapter state,
prints a record count for every cleared store, and exits non-zero when the backend
cannot confirm the reset. It refuses to run against components that have not
explicitly opted into the synthetic reset boundary. The concrete API and logical
DynamoDB mapping is preserved as a historical Sprint 1
[fixture example](docs/archive/sprint-1/validation/api-dynamodb-fixture-examples.md).

## Contract Changes

`docs/api.md` is the normative transport and schema contract. A contract change must update affected backend models, clients, fixtures, tests, and API documentation in the same pull request. Product scope changes belong in `SPEC/`; sprint commitments belong in `sprint/`.

The current provider-neutral data, knowledge, RAG, and runtime-profile contract is
documented in [Data Architecture](docs/data-architecture.md).

## Historical Delivery Evidence

The Day 3 implementation map, Day 4 integration and demonstration records, Day 5
validation records, screenshots, and static prototypes preserve Sprint 1 evidence. They
remain useful for regression and provenance, but they do not override the current
`SPEC/`, `docs/api.md`, data architecture, or sprint commitments. The documentation
index separates current engineering contracts from these historical records.
