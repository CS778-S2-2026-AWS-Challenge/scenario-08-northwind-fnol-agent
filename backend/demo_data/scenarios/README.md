# Day 3 Runtime Demo Scenarios

These canonical runtime demo-data records contain synthetic data only and
exercise the stable scenario identifiers from `docs/day3-implementation-map.md`.
They are the source used by the development/test demo seeding workflow.

| Scenario | Coverage |
|---|---|
| `AT-01-clear-motor.json` | Clear journey with confirmed material facts |
| `AT-02-coverage-ambiguity.json` | Ambiguous coverage with linked policy/history data routed to a typed professional-review handoff card |
| `AT-04-urgent.json` | Injury/danger report with an urgent handoff card |
| `AT-05-human-request.json` | Explicit human-support request with a standard-priority handoff card |
| `AT-06-pending-evidence.json` | Claimant-owned future evidence, expected timing, and non-blocking work |
| `AT-08-resume.json` | Cross-session summary, unresolved work, pending evidence, and prior commitment |
| `AT-12-signal-writeback.json` | Shared claim state with an internal-only review signal |
| `AT-10-controlled-assessor.json` | Created claim, assessor route, evidence state, and next responsible action |
| `AT-13-staff-action-lifecycle.json` | Completed assign, review, resolve, and claimant-safe write-back audit trail |

Validate the reusable scenario records from the repository root:

```powershell
python scripts/run_scenarios.py
```

The loader rejects broken claim/session links. Claimant API tests also verify
that storage provenance and internal-only messages do not cross the claimant
visibility boundary.

## Linked MVP Record Graph

AT-02 is the bounded structured-data example for issue #251. Its synthetic
`linked_records` baseline connects one customer and Working Claim to two typed
retrieval records (policy and relevant claim history), the complete evidence set,
one handoff, and the complete scenario message set. The loader rejects missing,
duplicate, cross-claim, or wrong-type identifiers and requires the handoff packet
to reference the same policy, history, and evidence records.

The staff Workbench receives policy/history detail only from the claim-detail API.
Claimant projections do not include retrieval records, provider references, claim
history, internal messages, or the staff handoff packet. Neither page embeds the
fixture identifiers or record payloads; they discover claims and details through
the existing list/detail APIs.
