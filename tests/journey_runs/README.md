# Complete-journey runs

Sprint 4 requires 100 independent complete-journey runs (50 motor, 30 home, 20 contents), each
using its scenario's full material pack and recording the fields in `sprint/sprint4.md` section 7.
This package defines the record those runs leave.

A run record is verification evidence, not a fixture (`docs/fixtures_convention.md`). Records are
written outside the repository and summarised on the delivery issue. They are never committed.

## The record

`record.JourneyRunRecord`, schema `northwind-journey-run/1`:

| Field | Holds |
|---|---|
| `scenario_id`, `family`, `pack_id`, `rubric_refs` | What was run and which rubric items it evidences |
| `configuration` | Exact head, start and finish time, runtime (`fixture`/`deployed`), provider mode (`simulated`/`live`), Agent runtime and model profile, evidence level |
| `materials` | Every pack material: class, condition, who provides it, and how it actually arrived (`claimant_upload`, `consent_route`, `simulated_provider_result`, `no_route`) |
| `steps` | Every route called, in order: actor (`claimant`/`staff`/`integration`), expected and actual HTTP status, outcome, resulting Claim revision, error detail |
| `agent_turns` | Each claimant input with the Agent's reply, proposed action, reason codes, and next step, plus tool calls and Runtime decisions, or the reason they could not be observed |
| `consents` | Each permission given or refused: purpose, step, Claim revision, disclosed fields where observable |
| `visibility_checks` | Whether the claimant or staff can see what they should, and cannot see what they should not |
| `seam_checks` | Questions claimant and staff must answer the same way, each `consistent`, `contradictory`, `missing`, or `unavailable` |
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

## Result classes

The class is derived from the record's own evidence. A record that declares any other class is
rejected. The first rule that matches wins:

1. `failed`: a step failed, or a visibility check does not hold.
2. `blocked`: a step was refused.
3. `unavailable`: a step the journey needs has no capability.
4. `partial`: every step succeeded, but a pack material had no route in, or claimant and staff
   disagree.
5. `fixture-only`: everything was exercised and agrees, but on the fixture runtime, a simulated
   provider, or a simulated provider result.
6. `completed`: the same, on a deployed runtime with live providers.

A run is stopped at its first step that does not succeed. The steps that follow are not attempted,
so the record never implies they were.

## Runners

A runner drives one scenario through the API and returns a `JourneyRunRecord`. The record and its
classification rules are shared, so runs from different runners and families can be counted
together. The first runner, for the motor collision journey, follows in a separate PR.
