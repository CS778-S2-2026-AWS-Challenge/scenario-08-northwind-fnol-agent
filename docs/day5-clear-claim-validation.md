# Day 5 clear-claim validation

Issue: #141

This validation covers the `Ysoseri1224` ownership slice: a real claimant and
controlled Agent path for the clear minor motor journey. It uses the canonical
`AT-01-clear-motor-creation` fixture and the production-shaped FastAPI routes
with the in-memory fixture adapters.

## Demonstration path

Run `tests/test_clear_claim_claimant_agent.py`.

The executable journey proves, twice in one test run:

1. The claimant describes the incident in natural language and receives an Agent
   response linked to that claimant turn.
2. The Agent proposes the expected fields with the fixture's source and
   `proposed` state, and assigns confirmation to the claimant.
3. Claimant confirmation changes those same fields to `confirmed` without
   changing their source.
4. A claimant correction changes only `incident.description`; the inferred
   location and loss facts remain intact and retain their `inference` source.
5. The claimant view preserves source references for the unchanged inferred
   facts; the directly corrected field follows the current form-patch contract.
6. The controlled creation route proceeds only after the corrected form is
   confirmed and returns the fixture-backed claim result and next step.
7. The observable actions, next-step statuses, form values, sources, and mock
   creation result are identical across both runs.
8. The Agent response is checked for claimant-safe wording and does not expose
   internal signal, provider metadata, or authority details.

Generated identifiers and timestamps are intentionally excluded from the
repeatability comparison because they are runtime values rather than journey
outcomes.

## Boundary

This test does not replace the independent source and confirmation review owned
by `bdfa123` in PR #200. It verifies the claimant-facing interaction and the
Agent-to-API path; it does not claim that a production model, AWS service, or
Northwind policy rule is configured.
