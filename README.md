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
| `customer/` | React and Vite claimant experience |
| `workbench/` | React and Vite Claims Workbench with independent staff authentication |
| `admin/` | React and Vite Control Plane console backed by the authenticated Admin API |
| `employee/` | Deprecated redirect shell and legacy migration inventory; supported Workbench is `workbench/` |
| `frontend/shared/` | Shared semantic design tokens consumed by claimant and staff clients |
| `prototype/` | Historical static interaction demonstrators |
| `tests/` | Backend unit, middleware, API, and fixture tests |
| `.circleci/` | External backend, frontend, PR-policy, documentation, and GitHub-automation quality jobs |
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

Use Python 3.12 and Node.js 22. On Windows, install dependencies from the repository root with:

```powershell
py -3.12 -m pip install -r backend/requirements-dev.txt
npm ci --prefix customer
npm ci --prefix workbench
npm ci --prefix admin
```

The development requirements include `jsonschema` (MIT) and its typing package
`types-jsonschema` (Apache-2.0). They validate the actual provider-transformed JSON
schemas in contract tests; Pydantic validation of a response alone cannot detect an
unsatisfiable provider schema. They are not production runtime dependencies.

### Run the app

Start the backend and the claimant frontend against the shared model with one command:

```powershell
.\scripts\start-dev.ps1
```

It pulls the model credentials from the team secrets endpoint, starts the backend on port 8000
with the `model_gateway` runtime profile and the shared `config/model-runtime-bindings.json`
(currently OpenRouter `openai/gpt-4o`), then starts the claimant frontend on port 5173. Open
`http://127.0.0.1:5173/`. Add `-BackendOnly` to skip the frontend, or `-BackendPort` /
`-CustomerPort` to move either process.

The script starts from a fresh Control Plane database each time (`var/dev/control-plane.sqlite3`,
ignored by git). The backend only publishes the checked-in model catalogue into an empty Control
Plane; a database left over from an earlier checkout keeps its old catalogue, so you would see an
old default model or profiles that no longer exist and nothing would tell you why. Claims,
sessions and accounts are in separate databases and are kept. Pass `-KeepControlPlane` if you
have published a release locally through the Admin console and want to keep it.

Nobody keeps a private `.env` or a local credential store any more. Which model the team talks to
is decided by `config/model-runtime-bindings.json`; when that file is loaded the backend ignores
`MODEL_PROVIDER`, `MODEL_BASE_URL`, `MODEL_IDENTIFIER`, `MODEL_API_KEY_ENV` and the
`MODEL_SUPPORTS_*` variables, so change the model there, not in the environment.

The same steps, one at a time, if you prefer to run them by hand:

```powershell
# 1. Pull the credentials. The bundle is KEY=VALUE lines.
$bundle = Invoke-RestMethod -Uri 'https://ysoseri.us/secret/northwind-dev' `
    -Headers @{ Authorization = 'Bearer ysk_nEtbZytRcPqjtTHzaEFD-0Lg2sxlGZ9oUdCfXrfuAJA' }
foreach ($line in ($bundle -split "`n")) {
    if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
}

# 2. Fresh Control Plane (see above), then select the model_gateway runtime and the shared profile.
New-Item -ItemType Directory -Force -Path var/dev | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue var/dev/control-plane.sqlite3*
$env:NORTHWIND_ENVIRONMENT = 'development'
$env:NORTHWIND_IDENTITY_MODE = 'normal'
$env:NORTHWIND_CONTROL_PLANE_DB_PATH = 'var/dev/control-plane.sqlite3'
$env:AGENT_RUNTIME_PROFILE = 'model_gateway'
$env:MODEL_RUNTIME_BINDINGS_PATH = 'config/model-runtime-bindings.json'
$env:MODEL_PROFILE_ID = 'openrouter-gpt4o-mini'
$env:MODEL_TIMEOUT_SECONDS = '180'

# 3. Backend (in this shell).
py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-config scripts/dev-logging.json

# 4. Claimant frontend (in a second shell; it proxies /api to port 8000).
npm run dev --prefix customer -- --host 127.0.0.1 --port 5173
```

The Workbench and Admin frontends start the same way from `workbench/` and `admin/` on ports
5174 and 5175 if you need them.

`AGENT_RUNTIME_PROFILE=controlled` is a deterministic agent that never calls a model. It exists
for CI and the test suite only and is not a way to run the app.

Deployment environments inject the same variable names through their secret and configuration
mechanisms; they must not package a local `.env` file.

### Configure protected account data

The backend uses the maintained `cryptography` package's Fernet authenticated-encryption
implementation for bank-account and identity-document numbers. Python's standard library does not
provide an equivalent authenticated-encryption primitive. Development and test profiles derive a
stable synthetic-only key so local persistence remains repeatable; that key is not suitable for
deployed customer data.

Every non-development runtime that accepts protected account writes must inject a dedicated
`NORTHWIND_PROTECTED_DATA_KEY` through its approved secret mechanism. Generate a valid key with:

```powershell
py -3.12 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Do not commit or log the generated value. A configured but invalid key stops application startup.
When the key is absent outside development and test, ordinary API startup remains available but
protected writes fail closed with `503 PROTECTED_DATA_UNAVAILABLE`; the backend never stores the
plaintext as a fallback. Key custody, rotation, recovery, and retention remain deployment-security
responsibilities.

Multimodal model input is declared per profile by the `image_input` and `document_input` flags in
`config/model-runtime-bindings.json`. Those flags only enable image or PDF Evidence blocks for a
provider profile that has repeatable adapter evidence; they do not grant access to object storage
or bypass the Evidence authorization boundary.

The governed multi-model deployment allow-list is the same bindings file. Private model endpoints
remain environment-owned; the Qwen binding resolves `NORTHWIND_QWEN_BASE_URL` at process startup
rather than storing that address in source control. For the complete model publication contract,
see [Provider-Neutral Model Gateway](docs/model-gateway.md).

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

For a single-host Validation Prototype handoff, set the browser-reachable object-storage origin,
staff bootstrap credentials, and optional model configuration through the process environment,
then start the explicit Compose profile:

```powershell
docker compose --profile vp up -d --build
```

This profile uses normal claimant and staff authentication, durable MongoDB, MinIO, and SQLite
volumes, and an idempotent governed-knowledge bootstrap. It still labels policy/history and the
controlled assessor honestly as synthetic; it is not an AWS or production deployment claim.

To run the same changed-scope backend coverage check locally, use:

```powershell
$selectedTests = py -3.12 scripts/select_backend_tests.py --tests
py -3.12 -m pytest --cov=backend --cov-report=json:coverage.json --cov-fail-under=0 $selectedTests
py -3.12 scripts/check_diff_coverage.py --coverage coverage.json --base origin/main --min 85
```

The remote backend quality gate requires at least 85% of executable lines added or modified
under `backend/` to be covered by the selected consumer tests. Deleted lines, non-Python files,
and non-executable lines are not part of the diff denominator. Remote CI does not run the full
backend suite or enforce repository-wide total coverage; developers may still run the complete
suite manually when diagnosing broad interactions.

In another terminal, start the claimant client:

```powershell
npm run dev --prefix customer
```

The Vite development server proxies `/api` requests to the local backend. Start the Claims
Workbench separately:

```powershell
npm run dev --prefix workbench
```

Configure the initial normal-mode staff account as documented in
[workbench/README.md](workbench/README.md). The legacy files under `employee/` remain only until
their still-valid capabilities have been migrated and verified; do not add new product behaviour
to that client.

Start the Control Plane console separately when administrator access is required:

```powershell
npm run dev --prefix admin
```

The Admin Console uses `/internal/v1/admin` projections only. It does not connect directly to a
database, object store, model endpoint, or secret manager; sign in with an administrator bearer
token and inspect server-owned configuration, knowledge, evaluation, operation, integration, and
account state.

Copy the non-secret values from `.env.example` into the process environment when overrides are needed. Local development permits any CORS origin by default and does not enable credentialed cross-origin requests.

Developer mode uses separate synthetic administrator and release-approver tokens. The
administrator may author and validate configuration, while
`NORTHWIND_SYNTHETIC_RELEASE_APPROVER_TOKEN` represents the independent identity required to
publish a high-impact configuration. These synthetic tokens are local test identities only and
must not be used as a production approval mechanism.

## Verification

CircleCI is the authoritative repository quality provider for the active backend, frontend, policy,
documentation, and GitHub-automation gates. Claimant, Workbench, and Control Plane quality gates
run only when their package or shared frontend tokens change; unrelated pull requests complete
their impact check without installing frontend dependencies. Each affected package runs its
`npm ci`, lint, test, and build chain. Backend pull requests use impact-scoped tests selected by
`scripts/select_backend_tests.py`; known paths run mapped consumer tests, while shared or unmapped
backend and quality-tooling changes run the selector contract sentinel and rely on diff coverage to
require focused tests for changed executable lines. Ruff and Mypy inspect only changed Python files,
and contract snapshot checks run only when their inputs are affected. Documentation-only changes
skip the Python backend quality chain. Pull requests and `main` use the same diff-scoped policy.

For focused local backend verification while developing, run the checks affected by the change:

```powershell
py -3.12 -m ruff format --check .
py -3.12 -m ruff check .
py -3.12 -m mypy backend tests
py -3.12 -m pytest
```

The frontend and GitHub automation packages retain their own `npm` verification commands. Local
frontend checks remain useful while developing; affected frontend, backend, policy, documentation,
and automation changes require the exact-head CircleCI result.

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
