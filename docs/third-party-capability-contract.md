# Third-party capability contract

The canonical third-party catalogue is `external-service-lifecycle.v1` in
`backend/domain/external_service_registry.py`. Claimant UI, Workbench and the
Agent Runtime consume the projection derived from that registry; none of them
maintains a second service list or invents provider states.

Each capability declares its product families, purpose, access form, required
Claim fields, disclosure fields, provider identity, official contact (when the
provider publishes one), adapter kind, result semantics and limitation. The
disclosure list is the minimum payload boundary. Consent and Northwind authority
are still checked by the existing external-task contract before a side effect.

Capabilities with `uses_external_task=true` use the existing append-only
ExternalTask/ExternalTaskResult lifecycle. A provider acknowledgement is not a
completed service; accepted, queued, assigned, result received, verification and
write-back remain separate meanings. Timeout or partial delivery follows the
existing unknown-outcome and reconciliation rules, and retries keep the same
operation identity.

Capabilities with `uses_external_task=false` are manual or official information
paths. The projection may contain an official URL or phone number, but selecting
the link or number does not create an ExternalTask and Northwind does not claim
that the external organisation accepted or completed work. Police 105 and
traffic-crash guidance are examples of this boundary.

The Runtime may propose only registered `external_service.*` operations. The
registry-backed dispatcher validates the service identity and operation, rejects
task operations for manual capabilities, and returns a typed unavailable result
when no adapter is configured. Adapter output is returned as provider evidence;
the model cannot turn an unavailable, acknowledged or unverified response into a
Claim fact or a completed booking.

The v8 model sees the bounded registered service toolbox regardless of family, excluding open
handoffs and services with existing operations. The context key `eligible_services` names this
read-only list; presence grants no eligibility or permission. No candidate-catalogue record or
lifecycle is introduced. After validating field changes, Runtime resolves the accepted same-turn
family using the existing fact-resolution rules, or the persisted confirmed family, and queries
`eligible_service_ids` again. Registry, family, lifecycle and cooldown filters remain authoritative.
Before the incident description is confirmed (a same-turn confirmation counts), only a service
the claimant explicitly requests in the current message is eligible: on the model path, a
`claimant_request_quote` found verbatim in that message.
Unsupported or disputed family assertions cannot unlock services. Only
the reducer creates offers. A suggestion grants neither consent nor dispatch authority. Pattern
selection remains only for explicit renewed intent during cooldown and the no-model path.
If no capability is eligible, chat continues without a fabricated offer or execution claim.

| Contract | Producer | Authority boundary |
| --- | --- | --- |
| Eligible capability | Runtime `eligible_service_ids` | Family, confirmed incident description (or explicit request), lifecycle, availability and suppression filters. |
| Service suggestion | Model `V8ServiceSuggestion` | Advisory subset of the eligible identities. |
| Offer | Reducer / external Runtime WorkItem | Bound to the actual Agent message and disclosure fingerprint. |
| Consent | Claimant | Existing scoped `ExternalServiceConsent`; never inferred from prose. |
| ExternalTask | Dispatcher | Created only after existing consent and execution checks. |

Declined or withdrawn services cannot produce new offers for the next three claimant turns. A renewed explicit
request can restore eligibility during that cooldown, but cannot bypass an open handoff:
every new service suggestion is suppressed while support remains open. A renewed offer receives
a new offer ID/disclosure binding and requires a fresh consent; the old consent remains history
and its offer cannot be reused to request dispatch. Consent mutations recompute claimant progress.

The registry projects `presentation` from access form and operation status: `info_link`,
`action_button`, `consent_request`, `tracked_task`, `agent_assisted`, or `status_update`.
The frontend consumes that value rather than guessing from provider fields. New polymorphic
rendering is outside this change. The frontend unknown-family catalogue still contains only
cross-family manual, link or phone guidance and does not open automatically. The model toolbox
is separate: a source-backed family proposal can unlock a matching offer in that same turn.
Without an accepted family the message offer set remains empty. The independent Staff Assistance
entry is not a third-party catalogue item and stays available.

Conversation commit and external dispatch are separate outcomes. An adapter rejection,
unavailability, or exception is recorded as the corresponding external-task failure and emits a
privacy-safe diagnostic containing correlation IDs and controlled codes, not claimant text or
provider payloads. It must not convert a committed message turn into a failed chat request. An
unknown outcome still uses the canonical reconciliation rule and the same operation identity; it
is never automatically retried.

The claimant projection is intentionally limited to service purpose, public
contact, disclosure requirements and the current server-declared action. The
Workbench receives the same catalogue plus its existing staff-only operation,
authority, delivery, audit and verification records. Role-specific detail is a
projection concern, not a frontend inference.

Provider partnership credentials are configuration concerns and are not stored
in this registry or exposed to models. A local adapter can reproduce a provider's
published request and response contract while the integration is being deployed;
switching to an authorised provider changes adapter configuration, not the Claim,
consent, lifecycle or UI contract.
