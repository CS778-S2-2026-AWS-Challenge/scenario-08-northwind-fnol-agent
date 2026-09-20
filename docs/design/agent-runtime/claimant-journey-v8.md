# Claimant Journey v8

This document publishes the repository-facing v8 contract. The detailed frozen
implementation specification remains the design source used for this PR; this
file records the public boundaries needed by repository consumers.

## Turn contract

One claimant turn may contain facts, a family result, a grouped next question,
eligible service suggestions, a safety or handoff signal, and a truthful reply.
Runtime validates the proposal and reduces it with the current Claim revision.
Intake is always retained as an intent even when the message also asks for
external help. `TurnTask` is audit classification only.

The model never authorises coverage, liability, fraud, settlement, or an external
side effect. Runtime owns field status, permissions, consent, lifecycle status,
revisions, idempotency, terminal protection, and the audit trace.

## Progress and confirmation

Branch requirements are computed by one `_required_set` implementation and are
classified as confirmed, recorded pending confirmation, or missing. A claimant
grounded normalised value keeps claimant provenance. Inferred, disputed, and
authority-sensitive values require confirmation; pending confirmation does not
prevent the next useful question but can prevent final creation.

Conversational confirmation and `POST /claims/{id}/form/confirmations` share the
same bound confirmation record. The record stores the displayed field set and
value fingerprint. The turn reducer compares it with the revision before the
new claimant message was persisted, then uses the final CAS to protect against
concurrent changes.

## Safety and external services

An open handoff continues to accept claimant messages and returns an Agent
reply. It may record facts and ask a non-blocking question. It suppresses all
new third-party suggestions until the handoff is resolved. Declined or withdrawn
offers are suppressed for three claimant turns; an explicit renewed request can
create a new offer identity. Consent, withdrawal, dispatch, result and handoff
mutations recompute the claimant next step.

Unknown family closes the automatic service catalogue while retaining the
Northwind Staff Assistance entry. Manual/link/phone third-party entries such as
Police 105 remain separate catalogue items and do not become automatic message
offers. Presentation is declared by the service registry and rendered by the
claimant surface.

## Recovery and terminal lifecycle

The claimant model-dependency failure rule is the first registered
`RecoveryPolicyRegistry` entry. The inbound message/checkpoint is preserved
before provider execution. The original idempotency key replays the original
response. Explicit retry goes through `submit_message` with a new attempt
identity linked to the accepted inbound message; no retry endpoint is added.

Created and other protected terminal Claims cannot regress to an in-progress
workflow state after a form correction. Existing external-task, WorkItem,
handoff, consent and audit records remain authoritative for their own data.

## Provider profiles

The claimant default is `openrouter-gpt4o-mini` (`openai/gpt-4o-mini`). Gemini
remains available for comparison and applicable multimodal checks. Qwen is a
local optional profile and is excluded from live provider evidence when offline.
The default profile is non-reasoning and receives no reasoning parameter.

Text and lookup turns use the 4500-token budget; media turns use 5500. The
limits are derived from the v8 bounded response fields and are checked with
maximum legal fixtures. Provider failure telemetry records status and error type
without storing prompts, claimant text, credentials, or raw provider responses.
