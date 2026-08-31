# Day 4 Routing and Workbench Write-Back Verification

This record closes the verification scope for issue [#44](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/44) against the tested `main` candidate `fdeecfa1da7f084b80c6833dd0447ddba05dabd3`.

## Commands and results

```text
py -3.12 -m pytest tests/test_integrations.py tests/test_staff_actions_api.py tests/test_workbench_api.py::test_workbench_detail_reads_shared_claim_creation_and_routing_results tests/test_day3_scenarios.py::test_claimant_and_staff_projections_share_state_without_leaking_internal_signal tests/test_policy_history_persistence.py -q
23 passed in 7.12s

py -3.12 -m pytest -q --cov=backend --cov-report=term-missing
189 passed in 45.76s
Total coverage: 90.76%
```

## Acceptance evidence

| Capability | Verified result |
| --- | --- |
| Agent-proposed review signals | Signals proposed in the current Agent decision path retain source references, are visible only to staff, and support the existing staff decision/write-back action without becoming a fraud conclusion. |
| Persisted retrieval review signals | The #176 retrieval boundary persists policy/history records and their sourced `ReviewSignalRecord` values and keeps them out of claimant projections. Connecting these retrieval signals to the staff decision/write-back action remains in issue #136. |
| Controlled claim creation | Creation requires the current revision and an explicit authorised decision. It is idempotent, returns the complete provider result, and rejects stale, changed, or unknown payloads. |
| Assessor routing | Severity alone cannot authorise routing. The controlled route requires `ASSESSOR_RULE_AUTHORISED`, persists the result to the shared claim state, and is visible in workbench detail. |
| Shared state | Claimant and staff projections read the same persisted claim, creation, and routing state rather than maintaining separate editable records. |
| Staff handling | Staff mutations are authenticated, revision-protected, constrained to documented paths, and recorded with actor, outcome, source references, and resulting revision. |
| Claimant update | A completed staff action writes one claimant-safe status and next-step update back to the shared claim. Internal reason codes, signals, and staff action records remain hidden from claimant APIs. |
| Replaceable integrations | The mock claims and assessor adapters preserve the public schema. Conflicting provider replays fail instead of silently overwriting stored results. |

## Boundary

All data used by these tests is synthetic. The verification establishes the current prototype contract and replaceable adapter behaviour. It does not claim that the persisted retrieval-signal path is already staff-decidable, or that a Northwind provider schema, routing policy, or production authority is available.
