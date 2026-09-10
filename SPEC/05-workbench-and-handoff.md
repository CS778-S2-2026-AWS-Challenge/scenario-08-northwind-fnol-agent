# Workbench, Handoff, and Administration

The staff `@Agent` entry point below is a target product capability. Its bounded authority,
source visibility, and proof requirements are defined in
[Agent Runtime Target](../docs/design/agent-runtime/agent-runtime-target.md).
The current Workbench transport remains governed by `docs/api.md` and the implementation
status is recorded in [Agent Runtime Progress](../docs/status/agent-runtime-progress.md).

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

## Staff context and actionability

The Workbench exposes enough context for authorised staff to understand and progress a
Claim without reconstructing it from raw records. The following matrix defines the stable
product-behaviour boundary. Exact transport fields and routes remain defined in
`docs/api.md`; the visual ordering and progressive-disclosure rules remain defined in
`docs/frontend-and-runtime-quality-standard.md`, especially sections 5.3 through 5.5.

| Context | Staff-visible boundary | Actionability boundary | Hidden or unavailable boundary |
| --- | --- | --- | --- |
| Claim, lifecycle, and next step | Show the current Claim identity, lifecycle/workflow state, incident summary, revision, and claimant-safe next step. | Material changes use registered actions against the current Claim revision. | Derived lifecycle, queue, and next-step projections are not manually maintained as a second status record. |
| Ownership, priority, and current work | Show the current responsibility, assignee where applicable, priority projection, current work item, timing, and primary blocker. | Assignment, collaboration, transfer, return, and related ownership changes use authorised actions. | Staff do not infer ownership or priority from tags, timestamps, field counts, or provider names. |
| Structured facts and fields | Show the relevant structured facts with status, source context, and unresolved gaps. | Field or state write-back uses an approved registered action and the current revision. | No direct database mutation or client-authored fact authority is permitted. |
| Conversation and sessions | Show Claim-linked claimant/staff sessions, messages, recent claimant activity, and continuity context required for the work. | Staff communication uses the authorised Claim-linked messaging boundary. | Server visibility rules exclude restricted or internal-only content from claimant projections, and staff must not create an orphan conversation as a substitute for a Claim-linked session. |
| Evidence and materials | Show evidence state, condition, source/provenance, related Claim context, and processing or availability limitations. | Evidence may support an authorised Claim action but does not mutate Claim State by itself. | Missing, unusable, failed, conflicting, and unavailable evidence remain distinguishable rather than collapsing into an empty state. |
| Policy, history, knowledge, and retrieval | Show source-linked retrieval results, applicable limitations, and whether the result is empty, partial, ambiguous, or unavailable. | Retrieval supports staff understanding or an explicitly registered action; it is not itself a Claim decision. | A retrieval result cannot silently become a confirmed Claim fact or override structured customer records. |
| Tags and review signals | Show authorised staff tags and review signals with their sources and current review state. | Supported signal decisions use registered staff actions and professional authority. | Internal review and fraud semantics remain staff-only and are not presented as confirmed business conclusions without the required decision. |
| Handoff context | Show the handoff packet, reason, requested action, current responsibility, transfer-time source references, and unresolved gaps needed to continue work. | Accepting, resolving, or otherwise changing a handoff uses authorised actions with revision and authority checks. | Handoff context preserves source references without copying live Workbench state into a second Claim authority. |
| External and third-party work | Show purpose, participant/service identity, disclosed-data scope, authority and consent state, submission/tracking state, returned result, provenance, verification, pending owner, failure, and limitation. | Preparing, sending, reconciling, retrying, or applying an external result remains governed by the registered action, Northwind authority, claimant consent where required, and current Claim revision. | Staff access or request preparation is not disclosure authority. Unknown, fixture-only, simulated, or unavailable provider capability remains explicit. |
| Work items and allowed actions | Show the current work item, server-projected primary action, allowed actions, required inputs, confirmation, expected effects, source references, and current revision. | The exact non-blocked registered action projected for the current target and revision is the executable boundary. | The client does not derive permission from role, queue, tags, text, array order, or a visible control, and a blocked action remains blocked. |
| Customer updates and activity | Show claimant-safe updates plus authorised activity and audit context needed to understand what changed. | Claimant communication or update requires the applicable authorised action and resulting Claim projection. | Internal reasoning, restricted provider payloads, and staff-only audit detail remain outside the claimant projection. |
| Incomplete and recovery context | Show the approved P17 recovery projection for an interrupted Claim when available. | P15 consumes the lifecycle and recovery behaviour owned by P17; it does not define follow-up, abandonment, retention, or purge transitions. | An interim or incomplete projection must not become a private recovery contract or second source of truth. |
| Staff Agent | Within explicitly attached Claim scope, staff may use natural language to read, summarise, compare, retrieve, explain, propose next steps, inspect handoffs, and draft communication from authorised context. | Output distinguishes source-linked facts, limitations, recommendations, drafts, pending actions, and executed results. Read-only assistance has no business side effect. Sending a message, mutating Claim State, changing ownership, disclosing data, or executing an external action still requires a registered action, fresh authority and revision validation, required confirmation, idempotency, and audit. | Staff Agent does not gain authority from natural-language intent, does not expand Claim scope implicitly, and does not privately implement business actions. Issue #579 owns implementation of Staff Agent business actions. |

## Staff Agent Entry

The dedicated Workbench Staff Agent session invokes the Agent within the current staff
member's identity, role, Claim scope, and task. It is not a fixed natural-language command
set. Staff may ask open questions or combine supported capabilities such as reading and
summarising a Claim, explaining gaps, comparing evidence, retrieving and explaining policy,
proposing next steps, drafting communication, inspecting handoff quality, or preparing an
external request. Claimant conversations do not expose an `@agent` command.

The Agent keeps source-linked facts, limitations, recommendations, drafts, pending actions,
and executed results distinguishable. Suggested UI actions may aid discovery, but staff
remain free to use natural language. Read-only assistance has no business side effect.
Sending communication, mutating Claim State, changing ownership, disclosing data, or
executing an external action requires a registered action, fresh authority and revision
validation, any required confirmation or stronger approval, idempotency where applicable,
and audit evidence.

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
