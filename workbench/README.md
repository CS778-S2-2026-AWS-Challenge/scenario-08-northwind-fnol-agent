# Northwind Claims Workbench

This React/Vite application is the supported, componentised staff client. It replaces the retired
static employee frontend.

## About this client

Supported deep links include `/workbench/claims/{claim_id}`, `/workbench/conversations/{session_id}`,
and `/workbench/agent/sessions/{session_id}`.

## Current application boundary

- The new client uses real staff login/session routes and never embeds the synthetic bearer token.
- Queue and Claim detail tags are rendered only from the backend Staff Tag Registry projection;
  the client uses backend tag codes for filtering and never activates a tag itself.
- The queue uses the backend cursor and bounded page size rather than slicing a local database
  mirror.
- Opening a Claim never accepts or changes it. Handoff acceptance and resolution remain explicit,
  revision-checked actions with separate internal results and claimant-safe updates.
- Claim tabs persist locally without opening duplicate contexts for one Claim.
- Claim details use overview, conversation, dynamic-field, evidence, reference, signal, and
  activity sections with progressive disclosure. Evidence file bytes are read only after an
  explicit staff request.
- Signal decisions and staff actions use the audited backend APIs. The client does not turn an
  Agent proposal or a risk signal into a business decision.
- Completed, abandoned, and closed queues come from server-published filter metadata and remain
  reachable when no active Claims exist. Terminal list/detail views retain their authoritative
  disposition context. Only the exact current `claim.reopen` action can return an abandoned or
  closed Claim to its server-projected active queue; the client reloads the Claim projection and
  reports the returned queue and revision.
- Staff Agent sessions are private to the authenticated staff identity and persist independently
  of Claim tabs. Every question explicitly attaches zero to five Claims; the client never infers
  scope from the current page. The Agent can use selected Claim context and authorised knowledge
  to provide advice and editable drafts, but it cannot execute a business action.
- Staff Agent turns require the configured model-gateway runtime. In controlled mode the API
  returns `503 DEPENDENCY_UNAVAILABLE` rather than fabricating an answer.

The retired static employee frontend has been removed. Add all staff-facing product behaviour
under `workbench/src/` and its tests.
