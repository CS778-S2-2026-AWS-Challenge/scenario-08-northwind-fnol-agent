# Verified Demonstration Evidence

This directory contains the visual evidence required by issue [#56](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/56).

## Tested candidate

- Commit: `c8b4c3427f3e53eb53b58f6616400f6ffe97e18`
- Fixture: `PRES-01-rear-end-handoff`
- Data classification: synthetic prototype data only
- Executable verification: `py -3.12 -m pytest tests/fixtures/presentation/test_rear_end_handoff.py -q`
- Result: `1 passed in 0.27s`

The live capture used a freshly reset in-memory repository and the claimant and staff applications from the tested commit. No database record, hidden-data repair, production identity, or real claimant information was used.

## Expected journey

1. The claimant reports a rear-end collision at Queen Street with rear-bumper damage, no injury, and no continuing danger.
2. The Agent proposes the incident, type, location, and loss fields for confirmation.
3. The claimant says the police report will be ready next week. The evidence remains `pending_generation` and does not block unrelated current work.
4. The claimant requests a person. The Agent creates one standard human-support handoff and promises that the saved report will travel with it.
5. Staff receive the confirmed facts, pending evidence, conversation, reason, requested action, and next step, then accept the handoff as `stf_demo`.
6. The claimant sees the accepted Northwind-support state without seeing the staff assignee, internal queue, reason codes, or handoff packet.

## Captures

| File | Observable result | SHA-256 |
| --- | --- | --- |
| [PRES-01-claimant-handoff-queued.png](PRES-01-claimant-handoff-queued.png) | The claimant sees the natural-language Agent response, confirmed structured facts, pending police report, and queued human-support state. | `521121d7352a174396a9c5f113921230634e96d07e496098272a1b07a4d8a962` |
| [PRES-01-staff-handoff-accepted.png](PRES-01-staff-handoff-accepted.png) | The workbench shows one synthetic claim, `stf_demo` assignment, confirmed facts and provenance, pending evidence, the complete accepted handoff packet, and the ordered communication history. | `8a30cc3f91b2ebf985da0c7e3b13164ba13da02c5a2d5471e1cdce09b992ac7f` |
| [PRES-01-claimant-staff-assisting.png](PRES-01-claimant-staff-assisting.png) | After refresh, the claimant sees `Accepted by Northwind support` and the claimant-safe next step. No staff identifier or internal handoff detail is exposed. | `220934b003a72dac543760df2bfa44ca47b3f9f6e69558724880834d4d7b9aef` |

## Evidence boundary

The screenshots demonstrate the tested prototype behaviour only. `stf_demo`, `cus_demo`, generated claim identifiers, fixture timestamps, and all incident details are synthetic. The captures do not establish a Northwind production workflow, service level, provider schema, or emergency-service action.
