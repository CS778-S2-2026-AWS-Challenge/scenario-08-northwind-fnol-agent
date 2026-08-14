# Day 4 Complete Prototype Integration Results

## Scope

This record completes the shared integration verification for D4-T01 (#40) on
14 August 2026. The live run used checkout commit
`ed4579a5170ee73f8c7eab4598ed614f04a5c1a9`; its application source is the
merged `main` commit `4c9e8069e0bee68f0a3daf269f964bb1bcc2d9c0`, with only this
documentation record added. Staff workbench actions and shared-state
write-back from #37 are therefore included. All verification data is
synthetic.

The earlier [Day 3 integration record](day3-bdfa-integration-results.md)
verified the claimant, fixture, and persistence foundations before the final
staff-action routes and workbench controls were available. This record adds
that remaining employee-side scope and reruns the complete repository gate.

## Integrated path

The documented local start path in the repository [README](../README.md#local-development)
starts the backend, claimant client, and employee workbench against the same
backend process. No source file, fixture, or hidden record needs to be edited
between roles.

The merged prototype now contains and verifies:

- claimant intake, confirmation, evidence, session resume, and claim creation;
- Agent decisions bounded by the shared authority and state models;
- claimant and staff projections over the same repository record;
- workbench queue/detail, persisted handoff communication, staff actions, and
  internal review-signal decisions;
- revision-checked and idempotent staff write-back with a separate
  claimant-safe status update; and
- repeatable synthetic scenarios with a fresh in-memory repository on every
  invocation.

## Live shared-process run

The documented start sequence was run from the repository root in three local
terminals. On this Windows verification host, the configured Python 3.12
executable was used in place of the `py -3.12` launcher:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
npm run dev --prefix customer -- --host 127.0.0.1 --port 5173
python -m http.server 8002 --bind 127.0.0.1 --directory employee
```

The following live URLs were checked before exercising the shared state:

| Surface | URL | Observed result |
|---|---|---|
| FastAPI liveness | `http://127.0.0.1:8000/health/live` | `200`, status `ok` |
| Claimant client | `http://127.0.0.1:5173/` | `200` |
| Employee workbench | `http://127.0.0.1:8002/` | `200` |

A claimant-authenticated request then created a working claim through the same
versioned route used by the claimant client:

```text
POST http://127.0.0.1:8000/api/v1/claims
Authorization: Bearer synthetic-claimant
Idempotency-Key: issue40-readme-live-claim

claim_id = clm_5d14d4937bfb216f3eff
revision = 1
```

Without restarting the backend or editing repository state, a
staff-authenticated workbench request read that exact record:

```text
GET http://127.0.0.1:8000/api/v1/workbench/claims/clm_5d14d4937bfb216f3eff
Authorization: Bearer synthetic-staff

claim_id = clm_5d14d4937bfb216f3eff
revision = 1
```

The matching claim identifier and revision demonstrate observable claimant-to-
workbench state through one running FastAPI process. All three local services
were stopped after the check.

## Verification results

| Check | Result |
|---|---|
| Backend formatting | Passed; 66 files already formatted |
| Backend lint | Passed |
| Mypy strict type check | Passed; 63 source files checked |
| Backend tests | Passed; 130 tests |
| Backend coverage | Passed; 90.09% (90% required) |
| Claimant client lint | Passed |
| Frontend behaviour tests | Passed; 14 tests |
| Claimant client production build | Passed |
| Scenario run 1 | Passed; AT-01, AT-06, AT-08, and AT-12 |
| Scenario run 2 / reset check | Passed with the same four starting fixtures and counts |

The two scenario invocations each produced these starting records:

| Scenario | Claim | Sessions | Evidence | Messages |
|---|---|---:|---:|---:|
| AT-01 clear motor | `clm_fixture_at01` | 1 | 0 | 1 |
| AT-06 pending evidence | `clm_fixture_at06` | 1 | 1 | 1 |
| AT-08 resume | `clm_fixture_at08` | 1 | 1 | 3 |
| AT-12 signal write-back | `clm_fixture_at12` | 1 | 1 | 2 |

## Staff write-back verification

The executable API and frontend tests verify the final scope that was missing
from the Day 3 record:

- `tests/test_staff_actions_api.py` verifies staff authentication, optimistic
  revision checks, allowed state paths, actor/outcome/reason audit data,
  idempotent signal decisions, and claimant-safe shared-state updates.
- `tests/test_workbench_api.py` verifies the authorised workbench projection.
- `customer/src/EmployeeWorkbench.test.js` loads the employee page and verifies
  persisted handoff behaviour, staff mutation refresh, empty-queue cleanup,
  exhausted action/signal controls, and refresh-failure cleanup.
- Claimant projections exclude internal staff actions, signal decisions, and
  reason codes while exposing the appropriate next step.

## Acceptance mapping

| D4-T01 acceptance criterion | Evidence |
|---|---|
| The prototype uses one documented start path. | The root README documents the backend, claimant client, and employee workbench sequence and their shared API. |
| The run does not require manual hidden-data changes. | Tests and UI clients use public versioned routes; scenarios seed synthetic records through the repository loader. |
| A clean fixture reset is available. | `scripts/run_scenarios.py` creates a fresh repository per scenario; two consecutive full runs produced identical starting IDs and counts. |

No integration blocker was found in the verified scope.

## Boundary

This is Sprint 1 prototype verification, not production-readiness evidence.
AWS services remain replaceable adapters or fixtures, and the results do not
claim production identity, security, performance, operational-volume, or
insurer-rule validation.
