# Complete-journey runs

Sprint 4 requires 100 independent complete-journey runs (50 motor, 30 home, 20 contents), each
using its scenario's full material pack and recording the fields in `sprint/sprint4.md` section 7.
This package defines the record those runs leave.

A run record is verification evidence, not a fixture (`docs/fixtures_convention.md`). Records are
written outside the repository and summarised on the delivery issue. They are never committed.

## The record

`record.JourneyRunRecord`, schema `northwind-journey-run/6`:

Schema `/6` is a breaking evidence-contract revision from `/5`. It adds `metrics`, the Sprint 4
metric coverage every run must state. `/5` added `steps[].response_body_valid` and changed
successful-response classification as described below. Consumers must select the model by
`record_schema` rather than parse a newer record as an older one.

| Field | Holds |
|---|---|
| `scenario_id`, `family`, `pack_id`, `rubric_refs` | What was run and which rubric items it evidences |
| `configuration` | Exact head, start and finish time, runtime (`fixture`/`deployed`), provider mode (`simulated`/`live`), Agent runtime and model profile, evidence level |
| `materials` | Every pack material: class, the condition the pack declares, who provides it, how the run actually got it in (`claimant_upload`, `consent_route`, `simulated_provider_result`), or why not (`no_route`: the journey needs it but nothing can deliver it; `not_delivered`: its step failed or was never reached; `not_applicable`: the selected operating form never calls for it, with `not_applicable_authority` quoting the document that says so), and the step that delivered it |
| `steps` | Every route called, in order: actor (`claimant`/`staff`/`integration`), expected and actual HTTP status, whether the response body is a valid JSON object, outcome, resulting Claim revision, error detail |
| `agent_turns` | Each claimant input with the Agent's reply, proposed action, reason codes, and next step, plus tool calls and Runtime decisions, or the reason they could not be observed |
| `consents` | Each permission given or refused: purpose, step, Claim revision, disclosed fields where observable |
| `visibility_checks` | Whether the claimant or staff can see what they should, and cannot see what they should not |
| `seam_checks` | Questions claimant and staff must answer the same way, each `consistent`, `contradictory`, `missing`, or `unavailable` |
| `unavailable_capabilities` | A capability the journey needs that this runtime does not provide: the capability, the step it was needed for, and the observation and document that establish it |
| `final_state` | Claim number, expected timing, workflow and lifecycle state, queue, next step and its owner, session and active session, evidence, external-task and handoff status |
| `effort` | Claimant messages, confirmations, uploads, consents |
| `metrics` | Every metric `sprint/sprint4.md` section 2 requires, each `measured`, `partly_measured`, or `not_measured`, with what the run observed and, short of a full measurement, a limitation quoting the document that establishes it |
| `result_class`, `result_reason` | One class, and why |

The record rejects evidence that contradicts itself:

- A step's outcome must be the one its HTTP status and response-body evidence support. A matching
  status is `succeeded`, except that a 2xx response whose body is not a valid JSON object is
  `failed`; 403, 409, 422 are `blocked`; 404, 501, 503 are `unavailable`; anything else, or no
  response, is `failed`. An expected non-2xx response can still be `succeeded` as an observation
  of the intended failure while `response_body_valid=false` and `detail` preserve its invalid body.
- A `contradictory` or `missing` seam check must name the defect that tracks it, or `untracked`.
- Unobserved tool calls or Runtime decisions need a `trace_limitation`. The claimant route keeps
  those records internal (`docs/api.md`), so an API-level run says so instead of recording them as
  empty.
- Agent turns and consents must point at a recorded step.
- An unavailable capability must name a step the run did not attempt; a step that was attempted
  is judged by its own outcome.
- A delivered material must name the step that delivered it, and that step must have succeeded; an
  undelivered one names no step.
- A `not_applicable` material names no step and no evidence. Its `not_applicable_authority` must
  start with a document path under `docs/` or `SPEC/` and quote at least one passage from it; a
  directory name or a path fragment inside other text is rejected, and the suite checks that every
  cited document exists and contains each quoted passage. No other material may carry one.

## Result classes

The class is derived from the record's own evidence. A record that declares any other class is
rejected. The first rule that matches wins:

1. `failed`: a step failed, a fixture oracle disagrees with an observed response, or a visibility
   check does not hold.
2. `blocked`: a step was refused.
3. `unavailable`: a step the journey needs has no capability, or the run records a capability
   this runtime does not provide.
4. `partial`: every step succeeded, but a pack material the journey needs had no route in or was
   not delivered, or claimant and staff disagree. A `not_applicable` material is not needed, so it
   never makes a run partial.
5. `fixture-only`: everything was exercised and agrees, but on the fixture runtime, a simulated
   provider, or a simulated provider result.
6. `completed`: the same, on a deployed runtime with live providers.

A run is stopped at its first step that does not succeed or its first fixture-oracle mismatch. The
steps that follow are not attempted, and every material they would have delivered is recorded as
`not_delivered`, so the record never implies they ran. An oracle mismatch remains a successful HTTP
step, but its `detail` records the expected and actual values plus `defect_ref=untracked`; the runner
returns and writes the resulting `failed` record instead of aborting before evidence exists.

## Runners

A runner drives one scenario through the API and returns a `JourneyRunRecord`. `engine.py` holds
what every runner does the same way (route calls, uploads, delivery, the shared read-back, and
record assembly); a runner holds its own steps, pack, and seam checks. The record and its
classification rules are shared, so runs from different runners and families can be counted
together.

```bash
python -m tests.journey_runs --scenario motor --runs 50 --out ../journey-runs
python -m tests.journey_runs --scenario home --runs 30 --out ../journey-runs
python -m tests.journey_runs --scenario contents --runs 20 --out ../journey-runs
python -m tests.journey_runs --scenario motor-failures --runs 5 --out ../journey-runs
python -m tests.journey_runs --schema
```

Each run starts a fresh fixture runtime and writes one `<run_id>.json`; `--schema` prints the
record's JSON Schema. `--runs` selects from a bounded matrix of distinct input/material pairs and
rejects a number larger than the matrix instead of silently repeating an identical input. For
motor, the matrix interleaves AT-01, PRES-01, and PRES-02 with 50 exact claimant/staff input
variations drawn from ten Auckland locations and five incident times, plus five material packs.
Every baseline case has a distinct serialized claimant/staff input, and the matrix assertion also
includes the complete material pack rather than trusting synthetic IDs. The successful route
step's `detail` records each fixture-oracle comparison; action, proposed fields, next step,
response text, pending evidence, and handoff mismatches produce a serializable `failed` run.
PRES-02 also executes and verifies the fixture's declared staff resolution.

`tests/test_journey_runs.py` exercises the matrix contract and representative journeys in the
ordinary suite. It fails on any `untracked` disagreement, and on a home or contents stop that is neither in
`household.KNOWN_STOPS` nor a documented unavailable capability: report it to its owner, then
record it there.

| Runner | Journey | Evidence level |
|---|---|---|
| `motor_collision.py` | Run AT-01 creation/assessor routing, PRES-01 human handoff, or PRES-02 guided professional review and staff resolution; upload the selected claimant pack and validate the fixture oracle | API projections on the fixture runtime; not browser; no provider contacted |
| `assessor_failures.py` (`motor-failures`) | Run AT-01 to assessor consent, route against an adapter scripted to fail one way, check both ends at the failure, then recover only through the claimant's retry or the projected Workbench `accept-review` or `reconcile` action | The same |
| `household.py` (`home`, `contents`) | Create, describe, upload the claimant's pack, then answer each `dynamic_form.requirements.next_required_item` from a scripted claimant answer and confirm the proposals, until the requirements are `ready` and the claim is created | The same |

The default motor pack (`motor-collision-provisional-2`) uses the `received` motor materials in
`backend/demo_data/materials/`:

- the two incident photos and the police event report are uploaded by the claimant. The Police
  form is claimant-supplied material (`P3-NZP-REPORT`,
  `docs/research/sprint4-third-party-integration-forms.md`);
- the consent record is Northwind's record of the consent route;
- the assessment arrives as the fixture assessor's own result.

Four additional packs explicitly record the condition of the affected material: unreadable
(`invalid`), conflicting (`disputed`), assessment v1 (`superseded`), and an assessment that cannot
be obtained (`unavailable`). Conditions survive into each record's `materials.pack_condition`;
they are not hidden in a note string.

The home and contents runners stop when a step fails or is refused, when the next required item
is one this runtime is documented not to capture (recorded as an unavailable capability after one
answer), when the same item is asked for again after its answer (creation is then attempted, so the
refusal is the evidence), or after 12 turns.

- **Home (`home-water-ingress-provisional-1`):** roof-valley ingress into the lounge ceiling and an
  adjacent room. The two incident photos and the repair assessment are claimant uploads (the
  assessment as claimant-supplied material under `P3-REPAIRER`, manual). The disclosure consent
  record is `not_applicable`: in that selected form Northwind discloses nothing to the repairer
  (`docs/research/sprint4-third-party-integration-forms.md`, `P3-REPAIRER`), and the record only
  applies before a disclosure. The controlled runtime completes the registered home intake fields
  and reaches Claim creation.
- **Contents (`contents-damaged-item-provisional-1`):** one damaged laptop. The two item photos,
  the purchase receipt, and the replacement assessment (`P3-CONTENTS-EVIDENCE`, manual) are
  claimant uploads. The consent record is `not_applicable` for the same reason: the selected form
  states that external-send consent is not applicable because Northwind sends nothing
  (`P3-CONTENTS-EVIDENCE`). The theft-path Police report is excluded. On the controlled runtime `contents.items` is not captured, so the run is
  `unavailable` (`docs/model-gateway.md`; Discussion #847).

The five assessor failure cases are a separate failure-path set, not part of the 50/30/20 baseline:
`retryable-unavailable` (503, claimant retry), `terminal-access-denied` and `terminal-not-required`
(502, staff accept the review), `unknown-outcome` (409, staff reconcile), and
`interrupted-dispatch` (500, staff reconcile). Each routing step expects its documented status and
records the error code as a fixture oracle. Four `failure.*` seam checks read both ends before any
recovery: who acts next, whether staff can find the work and have a task action when either end
names staff, and whether `can_request` matches what a resend does. Both ends agree at every check
in all five cases; the retryable case agrees since #942 made the claimant the staff-side owner, as
decided in Discussion #934. Any disagreement is `untracked` and fails the suite.
