# Day 4 Technical Demo Runbook

## Purpose and status

This Draft runbook records the technical order, evidence, safety boundaries, and
remaining readiness gates for the Sprint 1 demonstration under D4-T10 (#49).
It does not define product narrative or speaking roles, and it must remain Draft
until the outstanding Sprint 1 dependencies are closed.

Status terms:

- **Verified**: exercised against the assembled prototype or by the named test.
- **Known limitation**: a reproduced defect that must not be presented as working.
- **Pending dependency**: owned work that is not yet complete.
- **Optional technical evidence**: verified capability outside the short primary live path.

## Working baseline

| Item | Status | Record |
|---|---|---|
| Current `main` | **Working baseline, not final demo candidate** | `64b8a96fa188fabb7d5aa765b8632eae624eacf0` |
| D4-T01 integration record | **Verified** | PR #95 merged; Issue #40 completed. |
| Live demo reset | **Verified** | PR #100 merged; Issue #57 completed. |
| Demonstration data | **Verified boundary** | Synthetic fixtures only; no real claimant or policy data. |

The final demo candidate SHA must be refreshed after the remaining #47/#48/#56
work is reconciled. This document must not be treated as final while those gates
remain open.

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

The agreed timed live demonstration is one short continuous path. Claim creation
and assessor routing are not part of this primary sequence.

| Step | Technical action | Required observable evidence |
|---:|---|---|
| 1 | Reset the running synthetic demo state, then start/confirm the three surfaces. | Reset succeeds and all three surfaces are reachable. |
| 2 | Enter a natural-language rear-end incident through the claimant client and confirm the material facts. | The same working claim remains current and the confirmed facts are visible in claimant state. |
| 3 | Record the police report as expected later / pending evidence. | Pending evidence remains attached without blocking unrelated safe work. |
| 4 | Request a person and create the context-preserving handoff. | Confirmed facts and pending evidence remain attached to the same claim/handoff context. |
| 5 | Open the employee workbench against the same backend. | Staff sees the same claim and the context required to continue without making the claimant restart. |

Only use this live path after the #47 regression gate passes. Until then, the
known #47 claimant/Agent defects remain presentation limitations.

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

These capabilities must still obey role visibility and revision boundaries.

## Fixed synthetic fixtures

| Fixture | Demonstration purpose | Current use |
|---|---|---|
| `AT-01` | Clear motor facts and controlled mock claim creation | **Verified fixture/API evidence**; equivalent claimant UI creation remains limited by #47. |
| `AT-06` | Police evidence pending generation | **Verified fixture evidence** |
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
  are included in the controlled reset scope.

Do not substitute hidden-data editing, manual repository repair, or the archived
presentation runtime for this command.

## Remaining blockers and limitations

### #47 claimant / Agent blockers — pending

Two reproduced issues still require owner fixes and targeted re-test:

1. Negated safety language such as "No one was injured and there is no continuing danger"
   can incorrectly trigger an urgent handoff.
2. The claimant clear-motor path can reach a ready-to-create state without retaining
   or deriving `incident_type`, producing a creation dead end.

Do not present either affected path as complete until #47 is fixed and re-tested.

### #48 backend / workbench / integration closure — pending dependency

Independent verification found no #48-owned backend/workbench-data defect that
requires a new `jxu316-arch` code change. #48 remains open while its shared-owner
acceptance/dependency chain, especially #47 re-test, is incomplete.

### #56 visual fallback captures — pending

Fixture/result references exist, but the required claimant/staff screenshots or
short recordings are still not attached. PR #163 addresses a claimant
presentation defect discovered during #56 capture (`null` for pending-generation
evidence), but #56 remains incomplete until tested-candidate visual evidence is
attached by its owners.

Do not claim the fixed-fixture output alone satisfies the visual fallback requirement.

## Demo safety rules

- Demonstrate only behaviour that has passed the final re-test gate.
- Use synthetic data and public/versioned product routes.
- Do not edit hidden repository state or manually repair in-memory records to make a step pass.
- Do not live-code during the primary path or fallback.
- Do not make unsupported coverage, fraud, liability, safety, or assessor conclusions.
- Do not expose staff-only signals, queues, notes, reason codes, provider keys, or storage details to claimant views.
- If an expected result differs from the runbook, stop that path and use approved evidence/fallback instead of improvising a hidden repair.

## Fallback structure

1. **Primary live path:** the short rear-end -> confirmed facts -> pending evidence -> handoff -> staff view path, after final gates pass.
2. **Executable/fixed evidence:** AT-01, AT-06, AT-08, AT-12, and PRES-01 outputs.
3. **Visual fallback:** **Pending #56** tested-candidate claimant/staff captures.
4. **Environment recovery:** **Verified #57** live reset with `py -3.12 scripts/reset_demo.py`.

A fallback must not require live coding, unreviewed source edits, manual state repair,
or claimant exposure of internal-only information.

## Final re-test gate

Do not mark this runbook Ready or close #49 until all unchecked items are complete.

- [ ] #47 fixes are merged into the candidate baseline.
- [ ] Exact safety-negation input remains on the normal intake path.
- [ ] Claimant motor journey retains/derives `incident_type` and no longer reaches the creation dead end.
- [ ] #48 shared-owner/dependency closure is complete after #47 re-test.
- [x] #57 supported live reset is merged and independently verified.
- [x] Reset failure is visible/actionable and the reset is scoped to synthetic opt-in components.
- [ ] #56 claimant/staff fallback captures are attached to a tested candidate.
- [ ] Final candidate SHA replaces the working baseline above after remaining dependency merges.
- [ ] Narrative owner confirms the final speaking order.

## Final technical checklist

### Before the session

- [ ] Confirm final candidate SHA and dependency closure.
- [ ] Run repository validation required by the dependency changes.
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
