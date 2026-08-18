# D4-T02 Journey Test Records

These records close the verification scope for issue [#41](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/41) against `main` candidate `20a10e8de0ceb0ebfd9ffbd5ef8e5a6a763d9995`.

## Commands and results

```text
py -3.12 -m pytest tests/test_claim_creation_journey.py tests/test_claim_api.py::test_confirmed_intake_field_is_not_asked_again tests/test_handoff_api.py tests/test_workbench_api.py tests/test_integrations.py tests/test_day3_scenarios.py::test_claimant_and_staff_projections_share_state_without_leaking_internal_signal -q
33 passed in 4.76s

py -3.12 -m pytest -q --cov=backend --cov-report=term-missing
181 passed in 32.76s
Total coverage: 90.64%
```

## T02-01: Clear motor journey

- **Input:** Create a working claim without `incident_type`, then submit the clear rear-end motor description from `AT-01-clear-motor-creation`.
- **Response:** The Agent returns `CONFIRM` and proposes `incident.description`, `incident.location`, `loss.description`, and `incident.type=motor`. After confirmation, the next step is `ready_to_create`; controlled claim creation returns a claim number, route, next step, and expected timing.
- **State change:** All proposed material facts become confirmed, the claim incident type becomes `motor`, and successful creation changes the workflow state to `created`.
- **Result:** PASS. This includes the claimant-client regression fixed by PR #170; the path no longer depends on supplying `incident_type` when the working claim is created.
- **Defect:** None reproduced on the tested candidate.

## T02-02: Guided clarification journey

- **Input:** Submit a synthetic incident description, confirm it, then provide `A synthetic car park in Auckland.` and `A synthetic rear bumper was scratched.` in response to the next required fields.
- **Response:** The next step advances from incident description to `incident.location`, then to `loss.description`. After all three are confirmed, an additional note produces `UPDATE` rather than asking for a confirmed field again.
- **State change:** Description, location, and loss are persisted as separately confirmed fields with their source references. The final confirmation reaches `ready_to_create`.
- **Result:** PASS. The controlled guided flow requests the next missing material fact and does not re-ask a confirmed one.
- **Defect:** None reproduced within this deterministic guided-intake scope.

## T02-03: Professional-review handoff context

- **Input:** Submit an explicit injury or continuing-danger report, or explicitly request a person after confirming an incident description.
- **Response:** The Agent selects `URGENT_HANDOFF` for the explicit safety case or `HANDOFF` for the human request. Staff receive the incident summary, confirmed form snapshot, pending items, source references, reason, priority, and requested action. Claimant responses expose only the safe handoff status and next step.
- **State change:** One persisted handoff is created, urgency and workflow state are updated where applicable, and the workbench projects the same shared claim state in the professional-review path.
- **Result:** PASS. The receiving staff view has the context required to continue without reconstructing the report.
- **Defect:** None reproduced. Production urgency thresholds and staffing rules remain outside the prototype contract.

## T02-04: Coverage boundary

- **Input:** Load the synthetic `AT-02-coverage-ambiguity` scenario and read its claimant and staff projections.
- **Response:** The claimant receives a plain-language professional-review next step. Staff receive the internal review context and source references. Neither projection states that coverage is approved, declined, or finally determined.
- **State change:** Coverage remains `needs_review`; the internal signal remains evidence for staff review rather than a coverage or fraud conclusion.
- **Result:** PASS for the no-unsupported-conclusion and role-visibility boundary.
- **Defect:** The scenario starts from controlled synthetic review state; it does not prove a production policy decision or unrestricted natural-language coverage classifier.

## Evidence boundary

All data is synthetic. These records verify the current deterministic prototype, shared-state projections, and authority boundaries. They do not establish Northwind production coverage rules, emergency processes, provider schemas, or model-level semantic intent recognition.
