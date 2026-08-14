# D4-T02 Journey Test Records

## Scope and limitations

These records distinguish controlled API and fixture-based checks from the
claimant-client journey. A passing automated check proves only its stated
boundary; it does not override a reproduced claimant-client failure.

Known claimant journey blockers are tracked in
[#47](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/47).
This record supports, but does not close,
[#41](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/41).

## T02-01A: Clear journey — controlled API path

- **Input:** Create a working claim through `POST /api/v1/claims` with
  `incident_type: "motor"`. Submit: "Another car hit the rear of mine at
  Queen Street and damaged the rear bumper." Confirm
  `incident.description`, `incident.location`, and `loss.description`, then
  request claim creation.
- **Response:** The Agent returns `CONFIRM` and asks the claimant to check the
  structured facts. After confirmation, claim creation returns a claim number,
  `standard_motor_intake` route, next step, and expected timing.
- **State change:** Proposed form fields become confirmed and the workflow
  state becomes `created`.
- **Result:** PASS for the controlled API path.
- **Defect:** This path supplies `incident_type: "motor"` while creating the
  working claim. It does not verify that the claimant client supplies that
  value.
- **Evidence:** `.venv/bin/python -m pytest tests/test_claim_creation_journey.py -v`
  completed with `3 passed`, including
  `test_at01_natural_intake_confirms_then_creates_mock_claim`.

## T02-01B: Clear journey — claimant-client path

- **Input:** In the claimant client, submit: "Another car hit the rear of mine
  at Queen Street and damaged the rear bumper." Confirm the incident, loss,
  and Queen Street location, and select **Create claim**.
- **Response:** Claim creation fails with: "Controlled claim creation is
  currently available only for the motor fixture path."
- **State change:** The claim is not created and the staff workbench displays
  `Incident type: Not set`.
- **Result:** FAIL.
- **Defect:** The claimant client does not preserve or submit the motor incident
  type for this journey, preventing controlled claim creation. See
  [#47](https://github.com/CS778-S2-2026-AWS-Challenge/scenario-08-northwind-fnol-agent/issues/47).
- **Evidence:** The reproduced live result is recorded in
  [Day 4 assembled prototype integration baseline](day4-assembled-prototype-integration-results.md#known-live-journey-blockers).

## T02-02: Clarification journey

- **Input:** Create a motor working claim and submit: "I had an accident, but
  I am not sure what happened or whether my policy covers it."
- **Response:** The current controlled Agent returns `CONFIRM`: "I have
  structured what happened from your description. Please check the highlighted
  facts and correct anything that is not right." It does not ask a focused
  clarification question.
- **State change:** `incident.description` is stored as `proposed`,
  `claim_state.next_action` becomes `CONFIRM`, and coverage remains
  `not_assessed`.
- **Result:** FAIL.
- **Defect:** The controlled Agent has no executable `CLARIFY` branch for this
  material ambiguity. It should name the uncertainty in claimant-safe language
  and request focused clarification before a high-impact decision.
- **Evidence:** `backend/services/agent.py` routes a fresh claim with text input
  through the material-fact confirmation branch; no `AgentAction.CLARIFY`
  proposal is produced by `ControlledAgent`.

## T02-03: Coverage-boundary record

- **Input:** "I am not sure whether my policy covers this accident."
- **Response:** The system returns: "I have structured what happened from your
  description. Please check the highlighted facts and correct anything that is
  not right." It does not state that the incident is covered, not covered,
  approved, or declined.
- **State change:** Coverage remains `not_assessed`; no coverage decision is
  persisted.
- **Result:** PASS for the no-unsupported-conclusion boundary.
- **Defect:** The response is safe but insufficient as a clarification journey:
  it should ask a focused clarification question. This is the defect recorded
  in T02-02.
- **Evidence:** The controlled Agent confirmation branch has no state-change
  permission for `claim_state.coverage`; its state change is limited to
  `claim_state.next_action`.

## T02-04: Professional-review staff-context projection

- **Input:** Load the pre-seeded professional-review claim created by the
  `_create_claim_with_context` test helper, then retrieve it through the staff
  workbench and claimant projection.
- **Response:** Staff can view the shared claim state, structured form,
  evidence, pending items, review signal, internal messages, handoff packet,
  and professional-review queue. The claimant projection does not expose
  internal signals, staff actions, internal messages, or evidence provenance.
- **State change:** The pre-seeded claim is projected in the
  `professional_review` queue. Staff write-back is applied to the shared claim
  state.
- **Result:** PASS for staff-context projection and the claimant visibility
  boundary.
- **Defect:** This is not an end-to-end natural-language professional-review
  journey. `_create_claim_with_context` directly seeds
  `route=professional_review`, `fraud_signal=review_required`, and the internal
  review signal. An executable input-to-Agent-to-professional-review transition
  is still required.
- **Evidence:** `.venv/bin/python -m pytest tests/test_workbench_api.py -v`
  completed with `9 passed`, including:
  - `test_staff_reads_complete_claim_detail_from_shared_state`
  - `test_staff_receives_complete_handoff_packet_while_claimant_projection_is_safe`
  - `test_claimant_projections_do_not_expose_workbench_only_data`
