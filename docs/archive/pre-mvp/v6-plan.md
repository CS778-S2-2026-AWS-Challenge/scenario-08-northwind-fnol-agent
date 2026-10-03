# Agent Runtime v6 Third-party Service Plan

## Purpose

This plan closes the gap between the versioned external-service registry and the claimant
conversation Runtime. A claimant may ask for appropriate outside help at any point in intake.
The Agent may explain the current Claim step and propose that help in the same response, while
the Runtime remains the only authority that records consent, assembles disclosed data, and
dispatches an external operation.

The first acceptance example is a claimant reporting a rear-end collision on Symonds Street and
asking for a damage assessment. The response must retain the current safety question and include
an embedded vehicle-damage-assessment consent card beneath that Agent message. Formal Claim
creation is not a precondition for the offer or for recording consent.

## Confirmed journey

1. The model may return normal claimant-safe prose, the current focused question, and one or more
   registered `external_service_intents` in the same structured proposal.
2. Runtime validates each intent against the External Service Lifecycle Registry, the current
   product family, the published action/tool policy, and the current Claim scope.
3. Runtime persists an `external` WorkItem containing the immutable offer identity, originating
   Agent message, registry version, requested action, disclosure manifest, selected Evidence IDs,
   and disclosure fingerprint.
4. The claimant message projection attaches the resulting supplementary action to its originating
   Agent message. It does not replace `primary_action` and remains recoverable from message history.
5. A claimant confirmation submits only the offer identity and current Claim revision. The server
   reloads the persisted offer and assembles the exact current disclosure; the client cannot widen
   fields, select another provider, or manufacture authority.
6. Runtime records the versioned consent before attempting a side effect. When all service-specific
   requirements are ready, the same operation continues through the registered dispatcher. When a
   required input is not ready, consent remains pending execution and Runtime continues the Claim
   journey without asking for a second consent click.
7. Manual phone and official-link capabilities return their registered contact action and never
   create an ExternalTask. Task-backed capabilities use the existing ExternalTask lifecycle,
   idempotency, unknown-outcome, reconciliation, verification, and audit boundaries.
8. Decline and withdrawal are durable decisions. Withdrawal prevents a request that has not been
   accepted; it does not claim to recall data already accepted by a provider.

## Architecture

### Proposal and policy

`external_service_intents` is a supplementary model output, not a second primary action. The model
selects only a `service_identity` and registered requested action from the capability context.
Prompt wording cannot grant authority. Runtime rejects unknown, unavailable, wrong-family, or
unpublished capabilities and preserves that rejection in the turn trace.

Both current model profiles consume the same prompt version and published Agent policy. The
feature is represented in the feature configuration, action allow-list, tool allow-list, initial
release set, and provider-neutral schema; no provider-specific prompt can silently enable it.

### Persistent offer

The offer is carried by the existing immutable `RuntimeWorkItemRecord(kind="external")`. Typed
metadata records:

- `offer_id` and originating `agent_message_id`;
- `service_identity`, registry version, and requested action;
- canonical Claim field references and explicitly selected Evidence IDs;
- a claimant-readable disclosure manifest and its fingerprint; and
- the related consent and task identities when they exist.

This is unresolved-work evidence, not a second Claim lifecycle or external-task state machine.
Current status is projected from the offer, the authoritative Claim consent records, and any
matching ExternalTask.

### Canonical request assembly

The canonical request-assembly path resolves registered source references against the actual
`WorkingClaim.form` and Evidence repository. Registry entries use canonical field codes such as
`incident.location` and `vehicle.damage_description`; Evidence is selected by stable `evidence_id`, not
by an invented `evidence.damage_photos` field. Only confirmed, permitted Claim values and explicit
Evidence IDs may enter a dispatch payload.

Missing values do not prevent the Agent from offering help. They prevent only preparation or
dispatch, and the card explains what remains necessary without becoming the Claim's primary
question.

### Consent

`ExternalServiceConsent` retains the offer reference, registry version, requested action, exact
disclosure manifest, fingerprint, selected Evidence IDs, claimant actor, status, and timestamps.
Consent is valid only for that immutable scope. A changed registry version or expanded disclosure
requires a new offer and consent. Newly uploaded Evidence never enters an earlier consent scope.

The generic confirmation boundary supports `grant`, `decline`, and `withdraw`. Grant is persisted
before dispatch. Decline closes the offer without a side effect. Withdrawal prevents unsent work;
an accepted provider operation remains visible and is handled by its cancellation contract rather
than being falsely erased.

### Message projection and frontend

`ClaimantMessage` exposes `message_actions[]`. These actions are reconstructed from persisted
Runtime WorkItems and attached only to the Agent message that created them. The current Claim
`primary_action` remains the one main journey action. A safety question, review action, or Claim
creation action therefore coexists with a third-party consent card rather than being displaced.

The claimant client renders every message's supplementary actions beneath that message, restores
them from history, and sends only the chosen offer decision with revision and idempotency headers.
The card exposes purpose, provider, exact shared data, consent state, task state, pending owner,
references, limitations, failure, unknown outcome, and safe recovery as available. It never
renders raw adapter payloads.

## Migration and locality controls

- The assessor capability migrates to the same offer, consent, assembler, and dispatcher path as
  other registered capabilities.
- The former created-Claim-only assessor projection may remain readable for historical records,
  but it is not an offer source or fallback execution path.
- Safety interruption may block an external side effect, but it does not erase a recognised
  service request or its offer.
- Handoff, dynamic-form, Evidence, Claim creation, model selection, and customer-next-step
  semantics remain authoritative in their existing modules.
- No frontend rule derives eligibility, fields, consent validity, or provider status.
- No new Claim State, field vocabulary, provider-success shortcut, or automatic retry policy is
  introduced.

## Implementation sequence

1. Add the typed intent, offer metadata, consent scope, and message-action contracts.
2. Add canonical request assembly and registry validation.
3. Persist message-bound offers in Runtime turn WorkItems and project them in message responses
   and history.
4. Add the generic grant/decline/withdraw API and connect task-backed and manual capability
   dispatch.
5. Update Prompt v6, provider-neutral model schema, feature settings, action/tool policy, and
   initial published release.
6. Render message-bound actions in the claimant client and remove dependence on the latest global
   assessor action for new offers.
7. Retain compatibility reads for historical assessor records while disabling the old eligibility
   gate as a new-offer source.
8. Update API, persistence, OpenAPI, and current engineering documentation in the same change.

## Focused acceptance

- The rear-end-collision example returns one Agent message containing the safety question plus a
  vehicle assessment consent action before Claim creation.
- The offer stays attached to that message after another turn and after history reload.
- The primary safety/review/creation action is not displaced.
- Grant persists the exact versioned scope first and dispatches once when requirements are ready.
- A missing required field leaves one authorised pending offer and later continues without a
  second consent click.
- Decline and pre-submission withdrawal perform no external side effect.
- Scope expansion, registry-version drift, a new Evidence ID, stale revision, cross-Claim offer,
  and idempotency-key reuse fail closed.
- Manual link/phone capabilities create no ExternalTask; task-backed capabilities retain one
  operation identity and preserve unknown-outcome reconciliation.
- Existing safety, handoff, dynamic-form, Evidence, Claim creation, message history, and both
  model-profile contracts remain intact.
