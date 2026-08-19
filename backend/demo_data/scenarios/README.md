# Day 3 Runtime Demo Scenarios

These canonical runtime demo-data records contain synthetic data only and
exercise the stable scenario identifiers from `docs/day3-implementation-map.md`.
They are the source used by the development/test demo seeding workflow.

| Scenario | Coverage |
|---|---|
| `AT-01-clear-motor.json` | Fast journey with confirmed material facts |
| `AT-02-coverage-ambiguity.json` | Ambiguous coverage routed to a professional-review handoff card |
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
