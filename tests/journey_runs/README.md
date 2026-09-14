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
| `steps` | Every route called, in order: HTTP status, outcome, resulting Claim revision, error detail |
| `seam_checks` | Questions claimant and staff must answer the same way, each `consistent`, `contradictory`, `missing`, or `unavailable` |
| `final_state` | Claim number, expected timing, workflow and lifecycle state, queue, next step and its owner, evidence, external-task and handoff status |
| `effort` | Claimant messages, confirmations, uploads, consents |
| `result_class`, `result_reason` | One class, and why |

A `contradictory` or `missing` seam check must name the defect that tracks it, or `untracked`, so a
disagreement is never recorded without saying whether anyone owns it.

## Result classes

The class is derived from the record's own evidence. A record that declares any other class is
rejected. The first rule that matches wins:

1. `failed`: a step returned a status the journey did not expect (for example a 500).
2. `blocked`: the system refused a step the journey needs (403, 409, 422).
3. `unavailable`: a step the journey needs has no capability (404, 501, 503).
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
together. The first runner, for the motor collision journey, is delivered under #823.
