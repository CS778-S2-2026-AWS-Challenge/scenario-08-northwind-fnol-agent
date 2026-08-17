# Day 3 Scenario Fixtures

These fixtures contain synthetic data only and exercise the stable scenario
identifiers from `docs/day3-implementation-map.md`.

| Fixture | Coverage |
|---|---|
| `AT-01-clear-motor.json` | Fast journey with confirmed material facts |
| `AT-02-coverage-ambiguity.json` | Ambiguous coverage routed to a professional-review handoff card |
| `AT-04-urgent.json` | Injury/danger report with an urgent handoff card |
| `AT-05-human-request.json` | Explicit human-support request with a standard-priority handoff card |
| `AT-06-pending-evidence.json` | Future evidence that does not block unrelated work |
| `AT-08-resume.json` | Cross-session summary, unresolved work, pending evidence, and prior commitment |
| `AT-12-signal-writeback.json` | Shared claim state with an internal-only review signal |

Run the reusable fixture check from the repository root:

```powershell
python scripts/run_scenarios.py
```

The loader rejects broken claim/session links. Claimant API tests also verify
that storage provenance and internal-only messages do not cross the claimant
visibility boundary.
