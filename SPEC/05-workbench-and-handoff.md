# Workbench, Handoff, and Administration

The staff `@Agent` entry point below is a target product capability. Its bounded authority,
source visibility, and proof requirements are defined in [Agent Runtime Target](../docs/agent-runtime-target.md).
The current Workbench transport remains governed by `docs/api.md` and the implementation
status is recorded in [Agent Runtime Progress](../docs/agent-runtime-progress.md).

## Claim Operations Workbench

The Staff Workbench is a role-safe projection of shared Claim State, evidence,
decisions, handoffs, staff actions, and events. It must not become a second status record
that staff manually reconcile.

It supports:

- prioritised queues for urgent, untriaged, ready, awaiting-evidence, professional-review,
  handoff, and created/routed work;
- filtering by state, signal, priority, owner, next action, and service timing;
- claim detail showing facts, sources, evidence, conflicts, pending work, handoff context,
  and relevant communication;
- assignment, acceptance, completion, return, and transfer of staff work;
- confirmation, dismissal, override, and resolution of supported review signals;
- source-preserving professional decisions; and
- authorised write-back to shared Claim State and an appropriate claimant update.

Queues, priority, owner, and next action are calculated from the Claim lifecycle,
WorkItems, applicable service timing, content branches, and staff decisions. Staff may
record decisions and complete work, but they do not maintain a competing queue truth.

Sensitive signals, internal reasons, provider payloads, and staff-only notes must not be
exposed in claimant responses.

## Open Staff Agent Entry

`@Agent` invokes the Agent within the current staff member's identity, role, Claim scope,
and task. It is not a fixed natural-language command set. Staff may ask open questions or
combine supported capabilities such as reading and summarising a Claim, explaining gaps,
comparing evidence, retrieving and explaining policy, proposing next steps, drafting
communication, inspecting handoff quality, or preparing an external request.

The Agent returns source-linked facts, limitations, proposals, and required authority.
Suggested UI actions may aid discovery, but staff remain free to use natural language.
Read-only assistance has no business side effect. Sending communication, mutating Claim
State, disclosing data, or executing an external action requires a registered action,
fresh authority validation, and any required confirmation or stronger approval.

## Handoff Packet

A standard or urgent handoff includes:

- a concise incident summary and confirmed material facts;
- structured facts and their provenance;
- available evidence and lifecycle state;
- missing, pending, conflicting, or uncertain information;
- relevant policy, history, or knowledge evidence and limitations;
- reason, priority, current responsibility, and requested action;
- prior customer communication and promised next step; and
- the source references needed to inspect disputed or high-impact content.

The receiving person should not need to read the full conversation or repeat confirmed
questions before understanding the requested work.

## Shared Claim Coordination

Approved assessors, repairers, and other participants may receive task-specific views and
write authorised results back to the same claim context. Each transfer records
responsibility, permitted data, expected output, timing, and status. External participant
access is incremental product scope and requires a confirmed integration and authority
contract.

External coordination is a lifecycle rather than one generic request. The system keeps
capability discovery, requirement loading, request preparation, request classification,
authority and consent checks, submission, tracking, response verification,
reconciliation, safe retry, cancellation, and failure escalation distinguishable. An
unknown submission outcome is checked by idempotency key or provider reference before
any retry.

## Administration and Control Plane

The Control Plane is separate from claim operations. It manages:

- data runtime profiles and provider capability checks;
- model endpoints, capabilities, routing, limits, and evaluation;
- knowledge sources, versions, metadata, ingestion, indexing, testing, publication, and
  withdrawal;
- Agent instructions, controlled business rules, feature configuration, and tool access;
- integrations, identities, roles, health, cost, and audit history; and
- draft, validation, approval, publication, and rollback of configuration.

It must not provide unrestricted direct editing of production Claim State. High-impact
configuration changes require stronger permission and an approval policy defined by
Northwind.

## Claim Creation and Routing

When creation conditions are satisfied, the system creates and routes a claim through a
fixture or configured claims service. The claimant receives the creation state, provider
reference when available, pending work, responsibility, expected timing, and a way to
resume. Routing or assessor actions require explicit authority and are not mechanically
derived from one severity label.
