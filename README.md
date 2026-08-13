# Northwind FNOL Agent

Northwind FNOL Agent is a trusted, adaptive First Notice of Loss service for Northwind Insurance. It helps a claimant describe an incident in their own words, turns that account into a visible and correctable claim record, and chooses the next safe action according to the claim, evidence, user, and system state.

The product is designed to sit between a rigid web form and a fully manual phone process. Straightforward claims can move quickly, while ambiguity, urgency, support needs, or high-impact decisions are transferred to staff with the claimant's confirmed context intact.

## Product Goal

The service should:

- reduce avoidable claimant questions, repetition, and waiting;
- progress a claim when the information is sufficient for the next safe action, even if later evidence is still pending;
- preserve context across sessions and human handoffs;
- give claims staff a workbench backed by the same claim state seen by the agent;
- keep coverage, fraud, safety, and other high-impact decisions within explicit business and human-review boundaries;
- make claimant effort, human effort, and agent cost observable.

## Users

- **Claimants** report an incident, confirm the structured account, provide evidence, and follow progress.
- **Claims professionals** review ambiguity, risk signals, handoffs, and claim actions without recollecting known facts.
- **Claims operations** owns the process, service quality, governance, and operating efficiency.

## Current Stage

The project is in Sprint 1 and is building a full-path prototype. The prototype may use controlled scenarios and mock integrations, but each demonstrated path must change shared system state and remain traceable. Production integrations, security controls, and final business rules will be refined as Northwind data and AWS service availability are confirmed.

Detailed product requirements are maintained in `SPEC/`, sprint plans in `sprint/`, engineering and research documentation in `docs/`, and demonstrators in `prototype/`.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI transport, application services, domain rules, persistence ports, and replaceable adapters |
| `customer/` | React and Vite claimant experience |
| `prototype/` | Static claimant and employee workbench demonstrators |
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

Start the backend:

```powershell
py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, start the claimant client:

```powershell
npm run dev --prefix customer
```

The Vite development server proxies `/api` requests to the local backend. The static employee workbench demonstrator is `prototype/employee-workbench-prototype.html` and does not require a server.

Copy the non-secret values from `.env.example` into the process environment when overrides are needed. Local development permits any CORS origin by default and does not enable credentialed cross-origin requests.

## Verification

Run the complete repository quality gate before requesting review:

```powershell
./scripts/check.ps1
```

After dependencies are installed, use `./scripts/check.ps1 -SkipInstall` for a faster repeat run. The command checks backend formatting, linting, types, tests and coverage, then checks and builds the claimant client.

Run the synthetic integration fixtures from the repository root with:

```powershell
python scripts/run_scenarios.py
```

Every invocation creates a fresh in-memory repository, so rerunning the command
is the clean fixture reset. The concrete API and logical DynamoDB mapping is
[documented here](docs/api-dynamodb-fixture-examples.md), and the latest Day 4
integration record is [documented here](docs/day4-bdfa-integration-results.md).

## Contract Changes

`docs/api.md` is the normative transport and schema contract. A contract change must update affected backend models, clients, fixtures, tests, and API documentation in the same pull request. Product scope changes belong in `SPEC/`; sprint commitments belong in `sprint/`.

The Day 3 claimant, Agent, API, fixture, and observable-state dependency map is [documented here](docs/day3-implementation-map.md). It is a planning contract, not a claim that full frontend-backend integration is complete.
