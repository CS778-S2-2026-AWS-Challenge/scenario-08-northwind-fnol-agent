# Day 4 Technical Demo Runbook

## Purpose and status language

This runbook defines the technical order, evidence, safety boundaries, and
final readiness gate for the Sprint 1 demonstration under D4-T10 (#49). It
does not define the product narrative or speaking roles.

The document uses these status terms deliberately:

- **Verified**: exercised against the assembled prototype or by the named
  executable fixture or test on the candidate baseline.
- **Known limitation**: a reproduced defect or constraint that must not be
  presented as working behaviour.
- **Pending dependency**: an owned deliverable that is not yet available and
  must remain visibly incomplete.

## Candidate baseline

| Item | Status | Record |
|---|---|---|
| Candidate `main` | **Verified** | `c987be410aa2f5223b82a377f44caeaf4249fe55` |
| D4-T01 integration record | **Verified** | PR #95 is merged and the assembled baseline is recorded in [Day 4 Assembled Prototype Integration Baseline](day4-assembled-prototype-integration-results.md). |
| D4-T01 | **Verified** | Issue #40 is completed. |
| Demonstration data | **Verified boundary** | Use synthetic fixtures only; do not use real claimant or policy data. |

The candidate establishes an assembled shared runtime. It does not imply that
the open #47 claimant and Agent journeys, #57 reset command, or #56 fallback
captures are complete.

## Local start sequence

Start each surface from the repository root in a separate terminal. Use the
same Python environment for the backend and employee static server.

1. Start the FastAPI backend:

   ```powershell
   py -3.12 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
   ```

2. Start the claimant Vite client:

   ```powershell
   npm run dev --prefix customer -- --host 127.0.0.1 --port 5173
   ```

3. Serve the employee workbench:

   ```powershell
   py -3.12 -m http.server 8002 --bind 127.0.0.1 --directory employee
   ```

On a Windows host without the `py` launcher, use the configured Python 3.12
executable, such as `.venv\Scripts\python.exe`, for the same commands.

Confirm these URLs before beginning:

| Surface | URL | Required result |
|---|---|---|
| Backend liveness | `http://127.0.0.1:8000/health/live` | HTTP `200` |
| Claimant client | `http://127.0.0.1:5173/` | HTTP `200` |
| Employee workbench | `http://127.0.0.1:8002/` | HTTP `200` |

The claimant and employee surfaces must use the same FastAPI process on port
8000. Do not restart the backend between claimant creation and the matching
workbench observation.

## Verified technical demo order

Use only the steps whose prerequisites remain green in the final re-test gate.

| Step | Technical action | Required observable evidence | Status |
|---:|---|---|---|
| 1 | Create and update a claimant working claim through the versioned claimant API used by the Vite client. | Record the working `claim_id` and current revision from the response. | **Verified shared-runtime capability** |
| 2 | Open the employee queue and detail view without restarting the backend. | The same `claim_id` and revision appear in the workbench projection. | **Verified shared-runtime capability** |
| 3 | Run the `PRES-01` path: record pending police evidence and request a person. | The pending evidence remains attached to the claim and a claimant-safe human handoff is queued with confirmed context. | **Verified by executable presentation journey** |
| 4 | Accept the handoff as staff. | The workbench records the staff assignee and the claimant projection shows the safe accepted status without internal assignment details. | **Verified by executable presentation journey** |
| 5 | Continue the persisted conversation. | A claimant message is routed to staff while the handoff is open; the staff reply appears in the claimant-visible conversation. | **Verified by executable presentation journey** |
| 6 | Resolve the handoff. | The staff result and completed action are persisted, and the handoff becomes resolved. | **Verified by executable presentation journey** |
| 7 | Read the claimant-safe write-back. | The claimant next step contains the staff update without internal signals, queues, reason codes, or staff-only action data. | **Verified by executable presentation journey** |
| 8 | Exercise controlled mock claim creation only with a current revision and an authorised creation decision. | A mock claim number, route, next step, and timing are returned and stored in shared state. | **Verified by API journey and integration tests** |
| 9 | Exercise assessor routing only with an explicit authorised assessor rule. | The routing result contains the synthetic assessor or queue reference and a claimant-safe next step. Severity alone must not authorise routing. | **Verified by integration tests** |

Steps 8 and 9 are technical API evidence. Do not substitute the currently
blocked claimant UI clear-motor path for those steps until the #47 re-test gate
passes.

## Fixed synthetic fixtures

| Fixture | Demonstration purpose | Current use |
|---|---|---|
| `AT-01` | Clear motor facts and controlled mock claim creation | **Verified fixture/API evidence**; the equivalent claimant UI creation path remains limited by #47. |
| `AT-06` | Police evidence pending generation while unrelated safe work continues | **Verified fixture evidence** |
| `AT-08` | Resume saved context, unresolved work, pending evidence, and prior commitments | **Verified fixture evidence** |
| `AT-12` | Internal signal, staff decision, shared-state write-back, and claimant-safe projection | **Verified fixture evidence** |
| `PRES-01` | Pending evidence, explicit human request, staff accept, persisted conversation, resolve, and claimant update | **Verified executable presentation journey** |

Canonical fixture locations:

- `tests/fixtures/scenarios/AT-01-clear-motor.json`
- `tests/fixtures/scenarios/AT-06-pending-evidence.json`
- `tests/fixtures/scenarios/AT-08-resume.json`
- `tests/fixtures/scenarios/AT-12-signal-writeback.json`
- `tests/fixtures/journeys/PRES-01-rear-end-handoff.json`

Run the repeatable fixture evidence with:

```powershell
py -3.12 scripts/run_scenarios.py
```

This command creates fresh repositories for the four scenario fixtures. It is
not the supported live-demo reset required by #57.

## Known blockers and limitations

### Known limitation: #47 safety negation

The statement "No one was injured and there is no continuing danger" can
incorrectly trigger an urgent handoff. Do not use this path in the final live
demo until the fix is merged and the exact negated-safety journey is re-tested.

### Known limitation: #47 clear motor creation

The claimant client can create a working claim without `incident_type`, reach
`ready_to_create`, and then fail controlled creation because the motor route
discriminator is absent. Do not present the claimant UI clear-motor creation
path as complete until the fix and end-to-end re-test pass.

### Pending dependency: #57 reset

**Pending #57:** the supported one-command live-demo reset is not available.
Do not replace it with hidden-data editing, manual database repair, or the
archived presentation runtime. Insert the supported command here only after
#57 is merged and verified twice:

```text
Pending #57: <supported live-demo reset command>
```

### Pending dependency: #56 fallback captures

**Pending #56:** tested-candidate screenshots or a short recording are not yet
attached. Do not describe fixture output alone as the completed visual
fallback.

```text
Pending #56: <claimant, handoff, and staff capture links>
```

## Demo safety rules

- Demonstrate only behaviour that has passed the final re-test gate.
- Use fixed synthetic data and public, versioned product routes.
- Do not edit hidden repository state to make a step pass.
- Do not perform manual database or in-memory record repair.
- Do not live-code during the primary path or fallback.
- Do not make unsupported coverage, fraud, liability, safety, or assessor
  conclusions.
- Do not expose internal review signals, queues, staff notes, reason codes,
  provider keys, or storage implementation fields to the claimant surface.
- Keep claimant, staff, and integration credentials within their tested role
  boundaries.
- If a required observable result differs from the runbook, stop that path and
  use the approved fallback; do not improvise a hidden repair.

## Fallback structure

1. **Primary live path:** use the shared FastAPI process and the verified order
   above after all final gates pass.
2. **Fixed synthetic evidence:** use AT-01, AT-06, AT-08, AT-12, and PRES-01
   outputs to explain the expected state transitions without changing hidden
   state.
3. **Visual fallback:** **Pending #56.** Use only captures produced from the
   tested candidate and labelled with their fixture and expected outcome.
4. **Environment recovery:** **Pending #57.** Use only the supported scoped
   reset command after its two-run verification passes.

A fallback must not require live coding, unreviewed source edits, manual state
repair, or claimant exposure of staff-only information.

## Re-test gate before the final demo

All items below are required before describing the final live sequence as
ready:

- [ ] #47 fixes are merged into the candidate baseline.
- [ ] The exact safety-negation input remains on the normal intake path and
      does not create an urgent handoff.
- [ ] The claimant motor journey retains or derives `incident_type`, reaches
      controlled creation, and returns the mock claim result without a hidden
      edit.
- [ ] The supported #57 reset command succeeds twice and produces the same
      semantic starting state for claims, sessions, evidence, handoffs, and
      mock results.
- [ ] A #57 failure is visible and actionable, and the command cannot delete
      data outside the prototype fixture scope.
- [ ] #56 claimant, handoff, and staff captures are attached and identify the
      tested candidate, fixture, and expected result.
- [ ] The final candidate SHA replaces the baseline at the top of this runbook
      if any dependency merge changes `main`.

## Final technical checklist

### Before the session

- [ ] Confirm the candidate SHA and all dependency merges.
- [ ] Run the repository validation required by the dependency changes.
- [ ] Run the supported #57 reset and verify the starting queue.
- [ ] Start backend, claimant, and employee surfaces in the documented order.
- [ ] Confirm all three URLs and the shared backend process.
- [ ] Open the approved #56 fallback captures without exposing them on screen.
- [ ] Confirm only synthetic fixture data is present.

### During the live path

- [ ] Record the claimant-created working `claim_id` and revision.
- [ ] Match that ID and revision in workbench queue/detail.
- [ ] Preserve pending evidence through the `PRES-01` handoff.
- [ ] Accept the handoff, exchange persisted messages, and resolve it.
- [ ] Confirm the claimant-safe update contains no internal signal or staff
      detail.
- [ ] Demonstrate claim creation and assessor routing only through authorised,
      revision-current technical paths.
- [ ] Stop and use the approved fallback if an expected state is absent.

### After the session

- [ ] Stop the three local services.
- [ ] Do not preserve or publish runtime tokens, logs with sensitive data, or
      unreviewed internal projections.
- [ ] Record any deviation as a limitation or defect instead of repairing it
      outside the tested flow.
