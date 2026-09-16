# Complete-journey runs

Sprint 4 requires 100 independent complete-journey runs (50 motor, 30 home, 20 contents), each
using its scenario's full material pack and recording the fields in `sprint/sprint4.md` section 7.
This package defines the record those runs leave.

A run record is verification evidence, not a fixture (`docs/fixtures_convention.md`). Records are
written outside the repository and summarised on the delivery issue. They are never committed.

## The record

`record.JourneyRunRecord`, schema `northwind-journey-run/3`:

| Field | Holds |
|---|---|
| `scenario_id`, `family`, `pack_id`, `rubric_refs` | What was run and which rubric items it evidences |
| `configuration` | Exact head, start and finish time, runtime (`fixture`/`deployed`), provider mode (`simulated`/`live`), Agent runtime and model profile, evidence level |
| `materials` | Every pack material: class, the condition the pack declares, who provides it, how the run actually got it in (`claimant_upload`, `consent_route`, `simulated_provider_result`), or why not (`no_route`: nothing can deliver it; `not_delivered`: its step failed or was never reached), and the step that delivered it |
| `steps` | Every route called, in order: actor (`claimant`/`staff`/`integration`), expected and actual HTTP status, outcome, resulting Claim revision, error detail |
| `agent_turns` | Each claimant input with the Agent's reply, proposed action, reason codes, and next step, plus tool calls and Runtime decisions, or the reason they could not be observed |
| `consents` | Each permission given or refused: purpose, step, Claim revision, disclosed fields where observable |
| `visibility_checks` | Whether the claimant or staff can see what they should, and cannot see what they should not |
| `seam_checks` | Questions claimant and staff must answer the same way, each `consistent`, `contradictory`, `missing`, or `unavailable` |
| `unavailable_capabilities` | A capability the journey needs that this runtime does not provide: the capability, the step it was needed for, and the observation and document that establish it |
| `final_state` | Claim number, expected timing, workflow and lifecycle state, queue, next step and its owner, session and active session, evidence, external-task and handoff status |
| `effort` | Claimant messages, confirmations, uploads, consents |
| `result_class`, `result_reason` | One class, and why |

The record rejects evidence that contradicts itself:

- A step's outcome must be the one its HTTP status supports: the expected status is `succeeded`;
  403, 409, 422 are `blocked`; 404, 501, 503 are `unavailable`; anything else, or no response, is
  `failed`.
- A `contradictory` or `missing` seam check must name the defect that tracks it, or `untracked`.
- Unobserved tool calls or Runtime decisions need a `trace_limitation`. The claimant route keeps
  those records internal (`docs/api.md`), so an API-level run says so instead of recording them as
  empty.
- Agent turns and consents must point at a recorded step.
- An unavailable capability must name a step the run did not attempt; a step that was attempted
  is judged by its own outcome.
- A delivered material must name the step that delivered it, and that step must have succeeded; an
  undelivered one names no step.

## Result classes

The class is derived from the record's own evidence. A record that declares any other class is
rejected. The first rule that matches wins:

1. `failed`: a step failed, or a visibility check does not hold.
2. `blocked`: a step was refused.
3. `unavailable`: a step the journey needs has no capability, or the run records a capability
   this runtime does not provide.
4. `partial`: every step succeeded, but a pack material had no route in or was not delivered, or
   claimant and staff disagree.
5. `fixture-only`: everything was exercised and agrees, but on the fixture runtime, a simulated
   provider, or a simulated provider result.
6. `completed`: the same, on a deployed runtime with live providers.

A run is stopped at its first step that does not succeed. The steps that follow are not attempted,
and every material they would have delivered is recorded as `not_delivered`, so the record never
implies they ran.

## Runners

A runner drives one scenario through the API and returns a `JourneyRunRecord`. `engine.py` holds
what every runner does the same way (route calls, uploads, delivery, the shared read-back, and
record assembly); a runner holds its own steps, pack, and seam checks. The record and its
classification rules are shared, so runs from different runners and families can be counted
together.

```bash
python -m tests.journey_runs --scenario motor --runs 10 --out ../journey-runs
python -m tests.journey_runs --scenario home --runs 10 --out ../journey-runs
python -m tests.journey_runs --scenario contents --runs 10 --out ../journey-runs
python -m tests.journey_runs --schema
```

Each run starts a fresh fixture runtime and writes one `<run_id>.json`; `--schema` prints the
record's JSON Schema. `tests/test_journey_runs.py` runs each journey once in the ordinary suite. It
fails on any `untracked` disagreement, and on a home or contents stop that is neither in
`household.KNOWN_STOPS` nor a documented unavailable capability: report it to its owner, then
record it there.

| Runner | Journey | Evidence level |
|---|---|---|
| `motor_collision.py` | Create, describe (`AT-01-clear-motor-creation` input), upload the claimant's pack, confirm, create, consent, route the assessor, receive the assessment | API projections on the fixture runtime; not browser; no provider contacted |
| `household.py` (`home`, `contents`) | Create, describe, upload the claimant's pack, then answer each `dynamic_form.requirements.next_required_item` from a scripted claimant answer and confirm the proposals, until the requirements are `ready` and the claim is created | The same |

The motor pack (`motor-collision-provisional-2`) is provisional until an owner freezes the rubric
anchors. It uses the `received` motor materials in `backend/demo_data/materials/`:

- the two incident photos and the police event report are uploaded by the claimant. The Police
  form is claimant-supplied material (`P3-NZP-REPORT`,
  `docs/research/sprint4-third-party-integration-forms.md`);
- the consent record is Northwind's record of the consent route;
- the assessment arrives as the fixture assessor's own result.

The deliberately defective variants (unreadable, conflicting, superseded, not obtainable) belong to
failure-path runs.

The home and contents runners stop when a step fails or is refused, when the next required item
is one this runtime is documented not to capture (recorded as an unavailable capability after one
answer), when the same item is asked for again after its answer (creation is then attempted, so the
refusal is the evidence), or after 12 turns.

- **Home (`home-water-ingress-provisional-1`):** roof-valley ingress into the lounge ceiling and an
  adjacent room. The two incident photos and the repair assessment are claimant uploads (the
  assessment as claimant-supplied material under `P3-REPAIRER`, manual); the disclosure consent
  record has no home route. The controlled runtime completes the registered
  home intake fields and reaches Claim creation.
- **Contents (`contents-damaged-item-provisional-1`):** one damaged laptop. The two item photos,
  the purchase receipt, and the replacement assessment (`P3-CONTENTS-EVIDENCE`, manual) are
  claimant uploads; the consent record has no contents route. The theft-path Police report is
  excluded. On the controlled runtime `contents.items` is not captured, so the run is
  `unavailable` (`docs/model-gateway.md`; Discussion #847).
