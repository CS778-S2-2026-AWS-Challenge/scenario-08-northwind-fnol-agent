# Day 4 Technical Demo Runbook

## Purpose and status

This Draft runbook records the technical order, tested evidence, safety boundaries,
and remaining readiness gates for the Sprint 1 demonstration under D4-T10 (#49).
It does not define product narrative or speaking roles.

The primary technical path is now green on the current assembled baseline, including
the two claimant/Agent defects previously tracked by #47. The runbook must still
remain Draft until the remaining shared delivery gates are complete, especially
#48 shared-owner closure, #56 tested-candidate visual fallback captures, and final
speaking-order confirmation from the narrative owner.

Status terms:

- **Verified**: exercised against the named repository baseline or by the named test.
- **Pending dependency**: owned work or shared acceptance evidence that is not yet complete.
- **Optional technical evidence**: verified capability outside the short primary live path.

## Working baseline

| Item | Status | Record |
|---|---|---|
| Current `main` | **Tested working baseline; not yet declared final demo candidate** | `76d15fd78eb1418b7d44e6f49c910b0dbbf64892` |
| Shared runtime baseline | **Verified** | PR #95 merged; Issue #40 completed. |
| Claimant/Agent blockers | **Resolved and re-tested** | PR #170 merged; Issue #47 completed. |
| Pending-evidence presentation | **Resolved** | PR #163 merged. |
| Canonical handoff scenarios | **Verified on baseline** | PR #169 merged. |
| Live demo reset | **Verified** | PR #100 merged; Issue #57 completed. |
| Demonstration data | **Verified boundary** | Synthetic fixtures only; no real claimant or policy data. |

Current result references recorded against this exact `main` baseline:

- full backend suite: **166 passed**, **90.52% coverage**;
- canonical scenario runner: **7 passed**;
- claimant UI suite: **14 passed**;
- claimant lint: **passed**;
- claimant production build: **passed**;
- Employee Workbench static checks: included in the passing backend suite.

The final demo candidate SHA should be confirmed only after the remaining #48/#56
shared gates are reconciled and the narrative owner confirms the speaking order.

## Local start sequence

Start each surface from the repository root in a separate terminal and keep both
frontends on the same FastAPI process.

1. FastAPI backend:

   ```powershell
   py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
   ```

2. Claimant Vite client:

   ```powershell
   npm run dev --prefix customer -- --host 127.0.0.1 --port 5173
   ```

3. Employee workbench:

   ```powershell
   py -3.12 -m http.server 8002 --bind 127.0.0.1 --directory employee
   ```

Confirm before the run:

| Surface | URL | Required result |
|---|---|---|
| Backend liveness | `http://127.0.0.1:8000/health/live` | HTTP `200` |
| Claimant client | `http://127.0.0.1:5173/` | HTTP `200` |
| Employee workbench | `http://127.0.0.1:8002/` | HTTP `200` |

Do not restart the backend between claimant actions and the matching staff view.

## Primary live-demo sequence

The agreed timed live demonstration is one short continuous path. Claim creation,
assessor routing, and extended staff write-back are not part of the primary timed
sequence; they remain optional technical evidence.

| Step | Technical action | Required observable evidence |
|---:|---|---|
| 1 | Reset the running synthetic demo state, then start/confirm the three surfaces. | Reset succeeds and all three surfaces are reachable. |
| 2 | Enter a natural-language rear-end incident through the claimant client and confirm the material facts. | The same working claim remains current and confirmed facts are visible in claimant state. |
| 3 | Record the police report as expected later / pending evidence. | Pending evidence remains attached without displaying `null` or blocking unrelated safe work. |
| 4 | Request a person and create the context-preserving handoff. | Confirmed facts and pending evidence remain attached to the same claim/handoff context. |
| 5 | Open the employee workbench against the same backend. | Staff sees the same claim and enough context to continue without making the claimant restart. |

### Primary-path regression gate — verified

The two defects that previously blocked this path were fixed by PR #170 and
re-tested after merge on `main`:

- explicit safety negation such as "No one was injured and there is no continuing danger"
  remains on the normal intake path rather than creating an urgent handoff;
- a clear vehicle report created without an explicit `incident_type` derives/proposes
  `incident.type=motor`, persists the confirmed classification, reaches
  `ready_to_create`, and can create the controlled mock claim.

Post-merge focused verification across claim creation, handoff, workbench, and
integration suites produced **31 passing tests** with no #41/#47-scoped blocker
reproduced.

## Optional technical evidence

The following capabilities are verified technical/API evidence but must not be
inserted into the short primary live-demo sequence unless the narrative owner
explicitly changes the timed scope:

- staff handoff acceptance, persisted claimant/staff conversation, resolution,
  and claimant-safe write-back through `PRES-01`;
- controlled mock claim creation with a current claim revision and an authorised
  creation decision;
- assessor routing with an explicit authorised routing rule;
- fixed scenario evidence from AT-01, AT-06, AT-08, and AT-12.

These capabilities must still obey role visibility, authorisation, provenance,
and revision boundaries.

## Fixed synthetic fixtures

| Fixture | Demonstration purpose | Current use |
|---|---|---|
| `AT-01` | Clear motor facts and controlled mock claim creation | **Verified fixture/API evidence**; claimant clear-motor regression is resolved. |
| `AT-06` | Police evidence pending generation | **Verified fixture evidence**; claimant label no longer renders a literal `null`. |
| `AT-08` | Saved context, unresolved work, evidence, and prior commitments | **Verified fixture evidence** |
| `AT-12` | Internal signal, staff decision, shared-state write-back, claimant-safe projection | **Verified fixture evidence** |
| `PRES-01` | Pending evidence and context-preserving human handoff | **Verified executable presentation journey** |

Canonical fixture locations:

- `tests/fixtures/scenarios/AT-01-clear-motor.json`
- `tests/fixtures/scenarios/AT-06-pending-evidence.json`
- `tests/fixtures/scenarios/AT-08-resume.json`
- `tests/fixtures/scenarios/AT-12-signal-writeback.json`
- `tests/fixtures/journeys/PRES-01-rear-end-handoff.json`

Run isolated scenario verification with:

```powershell
py -3.12 scripts/run_scenarios.py
```

This scenario runner is separate from the live-process reset.

## Verified live-demo reset (#57)

Issue #57 is complete through merged PR #100. Reset the running local demo with:

```powershell
py -3.12 scripts/reset_demo.py
```

Verified properties recorded for #57:

- repeated reset/repopulate/reset verification produces the same semantic starting state;
- reset failures are visible and actionable;
- unsupported runtime components fail closed before mutation with `DEMO_RESET_UNAVAILABLE`;
- reset is limited to synthetic fixture/mock components that explicitly opt in;
- claims, sessions, messages, Agent decisions, evidence, staff actions, claimant
  updates, signal decisions, handoffs, idempotency records, and mock adapter state
  are included in the controlled reset scope on the current merged baseline.

Do not substitute hidden-data editing, manual repository repair, or an archived
presentation runtime for this command.

## Remaining blockers and limitations

### #47 claimant / Agent blockers — resolved

PR #170 is merged and Issue #47 is closed. Both formerly blocking claimant paths
have passed targeted post-merge verification. #47 is no longer a reason to exclude
the short claimant-to-handoff path from the tested technical candidate.

### #48 backend / workbench / integration closure — shared acceptance still open

`jxu316-arch` completed the required post-#170 regression on merged `main` with
**31 passing focused tests** and no new backend/workbench/integration defect.

No further #48 code is currently required from `jxu316-arch`. The issue remains
open only for remaining shared-owner acceptance/closure evidence, so this runbook
does not mark #48 globally complete.

### #56 visual fallback captures — pending dependency

Fixture/result references have been refreshed against `main` `76d15fd`, including:

- AT-01 clear motor;
- AT-02 coverage ambiguity;
- AT-04 urgent;
- AT-05 human request;
- AT-06 pending evidence;
- AT-08 resume;
- AT-12 signal write-back;
- PRES-01 rear-end handoff.

The required claimant/staff screenshots or short recordings are still not attached.
That capture work is owned by #56 assignees, not `jxu316-arch`. Fixed fixtures,
pytest output, or this document do **not** satisfy the visual fallback requirement.

## Demo safety rules

- Demonstrate only behaviour covered by the tested candidate and named evidence.
- Use synthetic data and public/versioned product routes.
- Do not edit hidden repository state or manually repair in-memory records to make a step pass.
- Do not live-code during the primary path or fallback.
- Do not make unsupported coverage, fraud, liability, safety, or assessor conclusions.
- Do not expose staff-only signals, queues, notes, reason codes, provider keys, or storage details to claimant views.
- If an expected result differs from the runbook, stop that path and use approved evidence/fallback instead of improvising a hidden repair.

## Fallback structure

1. **Primary live path:** rear-end intake -> confirmed facts -> pending evidence -> context-preserving handoff -> staff view.
2. **Executable/fixed evidence:** AT-01, AT-06, AT-08, AT-12, and PRES-01 outputs.
3. **Visual fallback:** **Pending #56** tested-candidate claimant/staff captures.
4. **Environment recovery:** **Verified #57** live reset with `py -3.12 scripts/reset_demo.py`.

A fallback must not require live coding, unreviewed source edits, manual state repair,
or claimant exposure of internal-only information.

## Final readiness gate

Do not mark this runbook Ready or close #49 until all unchecked items are complete.

- [x] #47 fixes are merged into the tested baseline.
- [x] Exact safety-negation input remains on the normal intake path after merge.
- [x] Clear motor journey derives/persists `incident_type` and no longer reaches the creation dead end.
- [x] `jxu316-arch` post-#170 #48 regression is complete with no new scoped blocker.
- [ ] #48 shared-owner acceptance/closure is complete.
- [x] #57 supported live reset is merged and independently verified.
- [x] Reset failure is visible/actionable and reset scope is synthetic/opt-in.
- [x] #56 fixture/result references are refreshed against the tested baseline.
- [ ] #56 claimant/staff visual fallback captures are attached to the tested candidate.
- [ ] Final candidate SHA is confirmed after remaining shared dependency/evidence closure.
- [ ] Narrative owner confirms the final speaking order.

## Final technical checklist

### Before the session

- [ ] Confirm final candidate SHA and remaining shared dependency closure.
- [ ] Run repository validation required by any changes after the tested baseline.
- [ ] Run `py -3.12 scripts/reset_demo.py` and verify the starting state.
- [ ] Start backend, claimant, and employee surfaces in the documented order.
- [ ] Confirm all three URLs use the same backend process.
- [ ] Open approved #56 fallback captures without exposing internal-only data.

### During the primary live path

- [ ] Natural-language rear-end intake stays on the expected safe path.
- [ ] Confirmed facts remain on the same working claim.
- [ ] Pending police evidence is represented as expected later/pending, not as missing or `null`.
- [ ] Human handoff preserves confirmed context.
- [ ] Staff workbench displays the same claim/context without requiring claimant restart.
- [ ] Stop and use approved fallback evidence if any expected state is absent.

### After the session

- [ ] Stop local services.
- [ ] Do not publish runtime tokens, sensitive logs, or internal-only projections.
- [ ] Record deviations as limitations/defects rather than repairing them outside the tested flow.
