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

The project is in Sprint 2 and is advancing the full-path prototype into a repeatable MVP. Current work includes natural claimant interaction, provider-neutral model and data boundaries, persistent shared claim state, cited knowledge retrieval, and staff review. Control Plane implementation is product-direction work tracked separately as extra backlog, not a committed Sprint 2 capacity item.

Controlled scenarios and fixture adapters remain valid development tools, but they must be labelled honestly. Cloud services, Northwind data, provider schemas, permissions, production rules, and deployment readiness are not claimed until verified.

Detailed product requirements are maintained in `SPEC/`, sprint plans in `sprint/`, engineering and research documentation in `docs/`, and demonstrators in `prototype/`.

## Repository Operation Rules

All contributors and coding agents must follow [the repository operation rules](docs/repo_rule.md).
Coding agents enter through [AGENT.md](AGENT.md), which defines the mandatory reading order and
authority boundary. Install the versioned local quality hook once per clone:

```powershell
./scripts/install-git-hooks.ps1
```

Every pull request must reference a repository issue and pass the required GitHub checks. Coding
agents must not merge pull requests or change Draft status without explicit current authorisation.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI transport, application services, domain rules, persistence ports, and replaceable adapters |
| `customer/` | React and Vite claimant experience |
| `employee/` | Static employee workbench backed by the shared Workbench API |
| `prototype/` | Historical static interaction demonstrators |
| `tests/` | Backend unit, middleware, API, and fixture tests |
| `SPEC/` | Current product requirements and acceptance scenarios |
| `docs/` | API contract, engineering conventions, and research material |
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

Use Python 3.12 and Node.js 22. On Windows, install dependencies from the repository root with:

```powershell
py -3.12 -m pip install -r backend/requirements-dev.txt
npm ci --prefix customer
```

Protected APIs are fail-closed by default. The repository synthetic identities are available only
when local/test developer identity mode is selected explicitly. For the local demo backend:

```powershell
$env:NORTHWIND_ENVIRONMENT='development'
$env:NORTHWIND_IDENTITY_MODE='developer'
py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The default object store remains the deterministic fixture adapter. To run the same
FastAPI evidence flow against local MinIO, start the packaged service and configure the
`s3_compatible` adapter as described in
[MinIO Object-Storage Boundary](docs/minio-object-storage.md).

In another terminal, start the claimant client with its explicit local synthetic credential:

```powershell
$env:VITE_NORTHWIND_CLAIMANT_TOKEN='synthetic-claimant'
npm run dev --prefix customer
```

The browser credential does not enable developer mode; the backend must already be running with
`NORTHWIND_IDENTITY_MODE=developer`. In normal mode the same repository synthetic credential is
rejected. This is a local fixture identity path, not production authentication.

The Vite development server proxies `/api` requests to the local backend. To run the employee
workbench, serve `employee/` on port 8002 as documented in `employee/README.md`; it reads and
updates the same backend claim state.

`.env.example` records the complete non-secret local-demo settings, including the explicit identity
mode and synthetic profiles. The application does not silently enable developer identity merely
because `NORTHWIND_ENVIRONMENT=development` or `test`. Local development permits any CORS origin by
default and does not enable credentialed cross-origin requests.

## Verification

Run the complete repository quality gate before pushing and before requesting review:

```powershell
./scripts/check.ps1
```

After dependencies are installed, use `./scripts/check.ps1 -SkipInstall` for a faster repeat run.
The command checks backend formatting, linting, types, tests and coverage, the pull-request policy
validator, and then checks and builds the claimant client.

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

To reset the running local demo backend, start the backend in explicit developer identity mode and
run:

```powershell
py -3.12 scripts/reset_demo.py
```

The command clears only the in-memory fixture repository and mock adapter state,
prints a record count for every cleared store, and exits non-zero when the backend
cannot confirm the reset. It refuses to run against components that have not
explicitly opted into the synthetic reset boundary. The concrete API and logical
DynamoDB mapping is [documented here](docs/api-dynamodb-fixture-examples.md).

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
