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

Service selection is a Runtime responsibility. One shared per-turn family resolution filters the
registry, and bounded intent recognition selects the exact service identity before model output is
validated. The model does not echo or authorise service IDs. If no registered capability matches,
the conversation may continue without an offer and without executional wording.

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
