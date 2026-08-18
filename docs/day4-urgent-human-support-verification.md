# Day 4 Urgent and Human-Support Journey Verification

This record closes the verification scope for issue [#42](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/42) against the tested `main` candidate `c8b4c3427f3e53eb53b58f6616400f6ffe97e18`.

## Command and result

```text
py -3.12 -m pytest tests/test_handoff_api.py tests/test_handoff_queue_fixtures.py tests/test_workbench_api.py::test_staff_receives_complete_handoff_packet_while_claimant_projection_is_safe tests/fixtures/presentation/test_rear_end_handoff.py -q
19 passed in 2.17s
```

## Acceptance evidence

| Journey | Verified result |
| --- | --- |
| Explicit injury or continuing danger | Ordinary intake stops and an urgent handoff is persisted. The claimant guidance says to contact local emergency services themselves; it does not claim that Northwind contacted them. |
| Ordinary non-injury wording | A negative safety statement remains on the ordinary intake path and does not create an urgent handoff. The longer natural-language negation regression is maintained by the Agent-owner work tracked separately in issue #47. |
| Explicit human-support request | The request creates one immediate human-support handoff and preserves confirmed fields, the incident summary, open work, and the next requested action for staff. Repeated requests do not create duplicate handoffs. |
| Staff-facing handoff packet | Staff can read the complete internal packet, including priority, reason, pending items, source references, and requested action. |
| Claimant-safe projection | Claimant responses expose the handoff status and next step without exposing queue, reason codes, packet contents, or internal signals. |
| Rear-end handoff journey | The executable presentation journey preserves the claimant conversation and confirmed context through staff acceptance and subsequent staff handling. |

## Boundary

This is verification evidence only. It does not assert that emergency services were contacted, that a production Northwind policy has been established, or that the separate Agent intent-classification work in issue #47 is complete. All records used by these tests are synthetic fixture data.
