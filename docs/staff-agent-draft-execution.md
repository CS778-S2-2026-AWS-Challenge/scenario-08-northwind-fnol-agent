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

For a confirmed draft, the Workbench idempotency record also stores the originating Staff Agent
`session_id`, assistant `message_id`, stable `draft_id`, and immutable execution ID in the same
atomic mutation. That mutation also writes the execution record with the registered action,
expected and resulting Claim revisions, and authoritative handler result. The repository accepts
it only when the source resolves to an assistant message in the acting staff member's session and
that message contains the matching Claim-scoped draft. A retry is accepted only when the same
source identifiers and request fingerprint are supplied; the same draft cannot execute again
under another key, and a non-Agent entry point cannot acquire its attribution.

The endpoint returns the persisted record as `runtime_execution`. It first reads the record back
through the staff-scoped repository boundary; missing readback fails closed and cannot produce a
synthetic success response.

The endpoint reports the underlying bounded outcome for confirmation missing, malformed payload,
unknown action, denied access, stale revision, idempotency conflict, unavailable dependency, or
unknown external result. These outcomes do not advance Claim State unless the authoritative
handler has committed the corresponding result.

## Acceptance evidence

- Existing Claimant API coverage proves motor, home, and contents intake, correction, confirmation,
  Dynamic Form requirements, and claim creation.
- Staff Agent tests prove stable draft identity, explicit confirmation, registered handoff action
  execution, idempotent replay with durable source identifiers and execution readback, no Claim
  mutation before confirmation, informational-draft rejection, unknown-action rejection,
  stale-revision rejection, assigned-staff permission denial, dependency-unavailable handling, and
  the post-execution Workbench projection.
- MongoDB contract tests prove owned assistant-draft linkage, role-safe readback, rejection without
  the source message, and immutable single execution for one draft.
- The OpenAPI snapshot and API catalogue describe the execution route and the role boundary.

The backend and claimant API suites provide contract and integration evidence for the three VP
families. A browser-level claimant journey is a separate evidence level and must be recorded only
after the existing customer client is exercised against the running API; component or API tests do
not get relabelled as browser evidence.

## Current evidence boundary

The claimant client now has an integration test that starts an anonymous Claim, consumes a backend
Dynamic Form projection, displays the backend-owned current requirement and progress, and submits a
natural-language-equivalent field correction through the authoritative update route. The backend
journey suite covers motor, home, and contents branch selection, confirmation, correction, and
Claim creation.

The remaining #608 evidence requirement is a full browser journey for each motor, home, and contents
path against the running customer and backend services. The supported in-app browser harness was
unavailable in this environment, so that evidence is intentionally still open and is not represented
as complete by the API or jsdom tests above.
