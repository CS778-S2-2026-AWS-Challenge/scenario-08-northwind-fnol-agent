## Claim decision frontend alignment

This document aligns the Workbench and claimant frontend work with the authoritative Claim decision contract delivered by #1146. It is a consumer guide, not a second backend contract. The backend API and persistence documents remain authoritative.

The contract was verified against merged `origin/main@8f709b2e6a799ef50dc0112e3abfd60603dde6f2` on 2026-10-01. The implementation is deliberately limited to one terminal staff decision for an eligible externally created Claim.

## Consume the published contract

Use the existing Workbench Claim detail as the source for the current Claim revision, ownership, decision projection, and allowed action. For the complete request and response reference, see [`docs/api.md`](api.md). For the persistence authority and immutability rules, see [`docs/persistence-schema.md`](persistence-schema.md).

The frontend should follow this read and write sequence:

1. Read `GET /api/v1/workbench/claims/{claim_id}`.
2. Read `revision`, `claim_decision`, current ownership, and `allowed_actions` from that response.
3. Render the decision control only when the registered action has `action_code: claim.record_decision` and is available as `confirmation_required`.
4. Submit the decision to `POST /api/v1/workbench/claims/{claim_id}/decisions` with the current numeric revision in `If-Match` and a new actor-scoped `Idempotency-Key`.
5. Treat the `201` response as the authoritative decision resource and refetch the Workbench Claim after the existing realtime invalidation event.

The backend still enforces every permission and state rule when the request arrives. `allowed_actions` is a UI projection and is not a substitute for server authorization.

## Submit the exact request

The request body contains only the fields below. Unknown fields are rejected.

```json
{
  "decision": "approved",
  "claimant_explanation": "Your claim has been approved.",
  "internal_note": "Reviewed against the applicable policy wording."
}
```

The request rules are:

| Field | Required | Frontend responsibility |
| --- | --- | --- |
| `decision` | Yes | Send exactly `approved` or `rejected`. |
| `claimant_explanation` | Required for `rejected`; optional for `approved` | Require non-empty claimant-safe text for rejection. Approval may omit it and receives the server default `Your claim has been approved.`. |
| `internal_note` | No | Send only staff-written internal context. Never render it in claimant UI. |

The request must include these headers:

| Header | Rule |
| --- | --- |
| `If-Match` | Send the numeric `revision` read from the same Workbench Claim detail. |
| `Idempotency-Key` | Generate a key for the logical attempt and keep it stable only while retrying the same claim, actor, and payload. Do not reuse it for another payload or Claim. |
| `Authorization` | Use the existing authenticated Workbench staff session. Do not put actor identity in the JSON body. |

The server derives `decided_by` and `decided_at`. The client must not send, calculate, or display client-authored values for either field as authority.

## Render the response safely

The successful `201` response is the full Workbench decision resource:

```json
{
  "decision": "rejected",
  "internal_note": "The exclusion was verified against the applicable policy wording.",
  "claimant_explanation": "The policy does not cover this loss.",
  "decision_id": "cdec_5a4c0ef19dd8ad4470a1",
  "claim_id": "clm_01J4Y7Q2AW",
  "decided_by": "stf_01J4Y82HDS",
  "decided_at": "2026-10-01T10:00:00Z",
  "source_claim_revision": 8
}
```

Workbench may show the complete record to an authorised staff user. Claimant detail and list responses expose only this safe projection:

```json
{
  "claim_decision": {
    "decision": "rejected",
    "decided_at": "2026-10-01T10:00:00Z",
    "claimant_explanation": "The policy does not cover this loss."
  }
}
```

The claimant projection never contains `internal_note`, `decided_by`, permission data, or staff-only reasons. Do not infer claimant visibility from the Workbench response shape. Use the claimant API response as the visibility boundary.

## Handle errors and retries

The frontend must use the stable error `code`, not message text, to choose its behavior. The relevant outcomes are:

| Code | Meaning | Required frontend behavior |
| --- | --- | --- |
| `ACCESS_DENIED` | The principal lacks the required staff role, Workbench write access, or current primary ownership. | Stop the action, refetch the Workbench Claim if appropriate, and show the existing authorization state. Do not retry unchanged. |
| `CLAIM_NOT_READY_FOR_DECISION` | The Claim is not an externally created Claim with `workflow_state=created` and terminal `COMPLETED / CLAIM_CREATED`. | Remove or disable the decision control after refetching. Do not invent a new frontend status. |
| `CLAIM_ALREADY_DECIDED` | Another final decision already exists. | Refetch and render the authoritative existing decision. Do not offer a second decision. |
| `REVISION_CONFLICT` | The supplied `If-Match` revision is stale. | Refetch the Claim, discard the stale form revision, and require an explicit new confirmation before resubmitting. |
| `IDEMPOTENCY_CONFLICT` | The same actor, route, and key was reused with a different payload. | Do not retry with that key. Start a new logical attempt only after reviewing the current Claim state. |
| `VALIDATION_ERROR` | The body or required headers do not satisfy the contract. | Show field-level validation and keep the decision uncommitted. |
| `RESOURCE_NOT_FOUND` | The authorised resource cannot be resolved. | Use the existing Workbench not-found behavior; do not expose claimant data. |

An exact retry with the same actor, Claim, key, and payload returns the original `201` resource. It does not create another decision, Claim revision, audit event, or realtime event. After an ambiguous network failure, reload authoritative server state first. Do not blindly submit a second key while the first outcome is unknown.

## Keep state scoped to the active Claim

The frontend must scope form state, pending state, errors, confirmation state, and idempotency keys to the active `claim_id`. When the operator switches Claims or restores another Claim, clear the previous Claim's unsent explanation, pending request, and action error before rendering the new Claim.

Use a pessimistic decision flow:

1. Disable duplicate submission and show an accessible pending state.
2. Require explicit confirmation for this high-impact irreversible action. Rejection must use the Workbench's existing confirmation convention.
3. Send the request once with the current revision and idempotency key.
4. On success, replace local state with the server response and refetch the Claim projection.
5. On conflict or an ambiguous failure, refetch first and then decide whether to show the action, the existing decision, or a retry affordance.

The realtime event is an invalidation signal. Refetch the documented Claim endpoint; do not treat event metadata as the decision record.

## Stay inside the frontend slice

The frontend implementation owns only the presentation and consumption of the published contract:

- Render the authoritative decision in Workbench detail and claimant-safe decision text in claimant views.
- Submit `approved` and `rejected` through the published endpoint.
- Handle loading, validation, authorization, revision-conflict, idempotency-conflict, already-decided, and ambiguous-network states.
- Add frontend component/API tests for Claim switching, duplicate clicks, safe visibility, and conflict recovery.
- Keep the UI aligned with the [Frontend and Runtime Quality Standard](frontend-and-runtime-quality-standard.md), including accessible high-impact confirmation and announced async errors.

The frontend must not make any of the following changes:

- Do not add a second approval or rejection field, local terminal status, or alternate endpoint.
- Do not reinterpret FNOL `workflow_state=created` or terminal `COMPLETED / CLAIM_CREATED` as approval.
- Do not send `decided_by`, `decided_at`, `decision_id`, `source_claim_revision`, or a client-owned Claim revision.
- Do not add approved amount, currency, payment, settlement, reversal, appeal, or multi-stage review UI.
- Do not expose `internal_note`, staff actor identity, permission data, or staff-only reason detail to claimants.
- Do not execute this action through the Staff Agent or allow Agent output to approve or reject a Claim.
- Do not modify backend repositories, persistence schema, shared backend models, audit rules, or realtime authority to make the UI work.

## Acceptance checklist

Before presenting the frontend slice for review, verify the following against the real API contract:

- The decision control appears only for the registered, available `claim.record_decision` action.
- Approval without `claimant_explanation` displays the server default after `201`.
- Rejection cannot submit empty or whitespace-only claimant-safe text.
- A stale `If-Match` response reloads the Claim instead of overwriting it.
- Exact retry does not duplicate the UI record or create a second visible decision.
- Reusing an idempotency key with changed input produces a clear conflict path.
- Claim switching cannot carry explanation, error, pending, or decision state into another Claim.
- Claimant views show only `decision`, `decided_at`, and `claimant_explanation`.
- Workbench views may show `internal_note`, `decided_by`, and `source_claim_revision` only in the authorised staff surface.
- No payment or provider side effect is implied by an approval.

This alignment note does not authorize changes outside the frontend slice. Any new backend field, error, permission, visibility rule, persistence behavior, or action beyond this document requires a new bounded contract decision before implementation.
