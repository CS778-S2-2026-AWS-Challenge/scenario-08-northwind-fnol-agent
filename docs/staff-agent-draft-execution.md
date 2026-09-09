# Staff Agent Draft Execution

This document defines the combined VP boundary for claimant intake (#573) and Staff Agent
business actions (#579).

## Claimant intake

The claimant message route remains the only writer for natural-language intake. It applies the
registered branch and field contracts, resolves facts with source message references, preserves
proposed/confirmed/disputed states, and returns the backend-owned Dynamic Form projection together
with `customer_next_step`. The projection's requirement counts and missing items are progress
feedback; the client does not calculate completion or branch decisions.

The three VP families (motor, home, and contents) use the same message, fact-resolution, branch,
confirmation, and creation contracts. Family-specific fields and contents items come from the
registered Branch Registry. Ambiguity and contradiction remain visible for clarification or staff
review and never become an automatic fraud, coverage, liability, approval, or rejection decision.

## Staff Agent drafts

Staff Agent output is a persisted proposal, not a business mutation. Each draft receives a stable
`draft_id`. An executable draft may include:

- `claim_id`, restricted to the explicit Claim scope supplied by the staff member;
- a registered Workbench `action_code`;
- a `target_ref` for the exact handoff, signal, WorkItem, collaboration request, or active
  claimant session; and
- a candidate `payload` matching the registered action inputs.

Informational notes and external-request drafts remain non-executable when no registered action is
present. The model must not invent an external provider capability.

## Confirmation and execution

The staff member explicitly confirms a draft through:

`POST /api/v1/workbench/agent/sessions/{session_id}/messages/{message_id}/drafts/{draft_id}/execute`

The endpoint is an adapter only. It reuses the existing Workbench action handlers, which own
permission, claim collaboration, consent, expected revision, idempotency, audit metadata, and
atomic Claim State persistence. A draft cannot bypass those checks or execute from model output
alone. The response contains the authoritative handler result and `outcome: executed` only after
the handler succeeds.

The endpoint reports the underlying bounded outcome for confirmation missing, malformed payload,
unknown action, denied access, stale revision, idempotency conflict, unavailable dependency, or
unknown external result. These outcomes do not advance Claim State unless the authoritative
handler has committed the corresponding result.

## Acceptance evidence

- Existing Claimant API coverage proves motor, home, and contents intake, correction, confirmation,
  Dynamic Form requirements, and claim creation.
- Staff Agent tests prove stable draft identity, explicit confirmation, registered handoff action
  execution, idempotent replay, and no Claim mutation before confirmation.
- The OpenAPI snapshot and API catalogue describe the execution route and the role boundary.
