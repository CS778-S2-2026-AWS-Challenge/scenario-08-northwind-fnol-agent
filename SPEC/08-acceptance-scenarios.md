# Acceptance Scenarios

Sprint 1 must demonstrate each scenario with repeatable input and observable state changes.

| ID | Scenario | Required observable result |
|---|---|---|
| AT-01 | Clear minor motor incident | Focused questions, form confirmation, fast progress, and mock claim creation |
| AT-02 | Ambiguous policy wording or applicability | Evidence and uncertainty shown; context transferred for professional judgement |
| AT-03 | Complex event or conflicting evidence | Conflict recorded, no unsupported conclusion, and professional review requested |
| AT-04 | Explicit injury or continuing danger | Normal intake interrupted, bounded safety guidance shown, and urgent handoff created |
| AT-05 | Claimant requests a person | The agreed first-request rule is followed and context is preserved through transfer |
| AT-06 | Police document not yet generated | Evidence marked pending; unrelated safe actions progress; later submission explained |
| AT-07 | Image contains incident information | Extracted facts remain proposed until the claimant confirms or corrects them |
| AT-08 | Claimant returns after ten days | Claim snapshot, unresolved work, and prior commitment resume without restarting |
| AT-09 | Relevant history supports a fraud review signal | Evidence-linked signal enters professional review without alleging fraud |
| AT-10 | Controlled assessor scenario | Claim is created and routed; mock assessor action and expected timing are visible |
| AT-11 | Multiple state dimensions coexist | Pending evidence does not erase clear coverage or incorrectly block the next action |
| AT-12 | Internal signal enters the workbench | Staff inspect evidence, decide the signal, complete an action, and update shared state |

## Cross-scenario Conditions

- The claimant can inspect and correct structured facts.
- Policy, history, evidence, and session data participate through defined interfaces in at least one relevant path.
- Customer and staff views apply the correct visibility boundary to the same claim state.
- Handoffs contain enough confirmed context to avoid recollecting known material facts.
- Claim creation returns a visible identifier, route, status, next step, and expected timing.
- Token and human-effort measurements can be inspected.
- No path uses real personal data, secrets, unsupported coverage decisions, or fraud conclusions.

These prototype scenarios do not replace the challenge's final evaluation set of five motor, three home, and two contents scenarios, nor its staff review and completion targets.

## Open Production Rules

Coverage, severity, fraud-review, assessor, urgent escalation, and first human-request triggers remain controlled prototype rules until Northwind data, policy authority, user research, and mentor feedback support production decisions.
