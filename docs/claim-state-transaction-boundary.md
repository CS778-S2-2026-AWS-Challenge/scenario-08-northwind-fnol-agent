# Shared Claim State Transaction Boundary

## Purpose

This document defines the provider-neutral transaction boundary for the shared Northwind
FNOL Claim State. It is the Day 1 contract for Issue #237 and the implementation input
for the Week 4 messaging, connected-state, and validation work in #248, #257, and #267.

The contract defines source-of-truth ownership, revision semantics, cross-record links,
write ordering, idempotency, visibility responsibilities, and failure atomicity. It does
not prescribe a MongoDB, DynamoDB, Cloudflare, or other provider transaction API.

## Source of Truth

`WorkingClaim` is the single authoritative current FNOL state for a claim.

Its optional `terminal_disposition` is the authoritative source-linked completed, abandoned, or
closed fact. It remains part of the same Claim record and revision; lifecycle projections, missing
Sessions, free text, and action history cannot substitute for it.

Sessions, messages, evidence, retrievals, handoffs, staff work, claimant updates, and
integration records are durable child or evidence records. They may carry a snapshot of
the claim revision that produced or consumed them, but they do not own a competing
current Claim State.

A frontend, Workbench, Agent context, session summary, external adapter, or provider
record must never overwrite a newer `WorkingClaim` merely because its local snapshot is
older.

## Identity and Ownership Keys

| Record | Required ownership/link |
| --- | --- |
| Working Claim | `claim_id` + authoritative `customer_id` |
| Session | `claim_id`, `session_id`, same `customer_id` as the claim |
| Message | `claim_id`, `session_id`; actor/visibility appropriate to the route |
| Agent decision | `claim_id`, `session_id`, `trigger_message_id`, resulting claim revision |
| Evidence | `claim_id`, `evidence_id`, source/provenance kept separately from object bytes |
| Retrieval / review signal | `claim_id`, retrieval identity, source references |
| Handoff | `claim_id`, `handoff_id`, immutable reason/type/creation context plus lifecycle owner/status |
| Staff action / customer update | `claim_id`, work identity, staff actor and source references; session identity only when the operation is interaction-scoped |
| Idempotency record | authenticated `actor_id`, route/operation, key, request fingerprint, affected `claim_id`, relevant child identities |

A mutation must validate these links before writing any member of the bundle. A record
with the correct identifier but the wrong claim, customer, session, actor boundary, or
idempotency link is an invalid bundle rather than a partial success.

## Revision Contract

`WorkingClaim.revision` is the only optimistic-concurrency token for material shared
Claim State changes.

For a material mutation starting from revision `N`:

```text
expected_revision = N
new WorkingClaim.revision = N + 1
```

Rules:

- the repository compares `expected_revision` with the currently stored claim before any
  bundle member is committed;
- a stale expected revision fails with `RevisionConflict(current_revision)`;
- a valid material mutation advances the claim exactly once, never zero times and never
  by more than one revision;
- child records do not maintain a second concurrency counter that can overwrite the
  claim independently;
- `WorkingClaim.active_session_id` may change only through the explicit claimant-session
  lifecycle mutations: resume/start may establish a new active Session, while the
  pause/checkpoint mutation may clear the current active Session; every other material
  mutation must preserve the stored authoritative active-session pointer;
- a session `context_revision` may identify the claim snapshot it represents but cannot
  supersede `WorkingClaim.revision`;
- non-material evidence retrieval may be persisted without advancing Claim State when it
  only records sourced information and does not apply a material claim decision.

## Mutation Families

The provider-neutral repository exposes explicit atomic mutation families instead of a
sequence of unrelated `save_*` calls.

| Mutation | Atomic bundle | Required revision behaviour |
| --- | --- | --- |
| Resume/start claimant session | claim + new/updated session + optional prior-active Session closure + idempotency | claim `N -> N+1`; session linked to the same claim/customer; one active claimant session; may establish the new `active_session_id`; when replacing an active Session, closing that prior Session occurs inside the same revision-checked atomic bundle |
| Pause/checkpoint claimant session | claim + paused session + bounded recovery context + initial Follow-up + idempotency | claim `N -> N+1`; source session must be the current active session; clears `active_session_id`; creates one Claim-scoped Follow-up for the interruption |
| Message-only claimant continuation | claim + session + message + idempotency | claim `N -> N+1`; session context updated to the resulting claim revision; stored `active_session_id` is preserved |
| Validated Agent turn | claim + session question accounting + claimant message + Agent message + decision + applied Branch Evaluation + optional handoff/evidence + idempotency | claim `N -> N+1`; all trigger/reply/decision/evaluation links agree; stored `active_session_id` is preserved; failed retrieval or validation writes none of the bundle |
| Evidence state mutation | claim + evidence + idempotency | claim `N -> N+1`; evidence belongs to the claim and active interaction boundary; stored `active_session_id` is preserved |
| Handoff mutation | claim + handoff + idempotency | claim `N -> N+1`; handoff identity and idempotency handoff reference agree; stored `active_session_id` is preserved |
| Staff write-back | claim + one or more authorised staff/handoff/message/customer-update records + idempotency | claim `N -> N+1`; all supplied records belong to the claim; non-interaction staff records may be session-agnostic, while staff messages bind the active session and staff actor; stored `active_session_id` is preserved |
| Reopen terminal Claim | claim + staff-scoped idempotency response + internal audit event | claim `N -> N+1`; exact `claim.reopen` action/target/revision and primary ownership are re-resolved; only `terminal_disposition` is cleared; retained `claim_state` and `active_session_id` are preserved |
| Retrieval + directly derived review signals | retrieval + zero or more source-linked review signals | no claim revision change merely for recording evidence; the bundle itself is atomic |

A caller must not emulate these bundles by writing the claim first and then appending
child records one at a time.

## Validation and Commit Order

Every material mutation follows this logical order regardless of physical provider:

1. **Resolve current claim** and verify the caller is permitted to operate on it.
2. **Check expected revision** against the stored `WorkingClaim.revision`.
3. **Validate next revision** is exactly `expected_revision + 1` and, unless this is a
   dedicated resume/start or pause/checkpoint Session-lifecycle mutation, validate the
   proposed `active_session_id` equals the stored authoritative pointer.
4. **Validate cross-record ownership and links** for claim/customer/session/message/
   decision/evidence/handoff/staff records.
5. **Validate idempotency identity**: actor, operation/route, key, fingerprint, claim and
   applicable child identifiers must describe the same operation.
6. **Reject conflicting replay** before any new state is written.
7. **Commit the entire bundle atomically** using the selected provider's transaction or
   equivalent conditional-write mechanism.
8. **Expose the resulting authoritative projection** only after the commit succeeds.

Steps 2-6 are preconditions. Failure at any one of them leaves the repository identical
to the pre-mutation snapshot.

## Idempotency Contract

An idempotency identity is scoped to the authenticated actor, operation/route, and client
key. It also stores a fingerprint of the accepted request and links to the affected claim
and relevant child records.

- same actor + route + key + same request may return the recorded authoritative result;
- same actor + route + key + changed request is an `IdempotencyConflict`;
- where the operation contract includes the expected Claim revision in its fingerprint (including
  `claim.reopen`), changing `If-Match` under the same key is changed input rather than a stale retry;
- a key cannot be reused to attach a result from another claim or from another relevant
  session/message/handoff child;
- a session-agnostic operation leaves the session identity empty rather than fabricating
  an interaction-session dependency;
- a failed precondition does not reserve a new idempotency result;
- a retry after a partial external dependency failure must not create a second durable
  domain operation when the first operation was already committed.

Idempotency does not replace revision checking: the first unseen request must still be
valid against current Claim State.

## Session and Message Ordering

`WorkingClaim` remains authoritative when a session is resumed or messages are appended.

- at most one claimant interaction session is active for a claim under the current
  contract;
- only explicit claimant-session lifecycle mutations may change the authoritative
  `active_session_id`: resume/start establishes a new active Session and pause/checkpoint
  clears the interrupted active Session; message, Agent, evidence, handoff, and staff
  mutation families must reject an attempted session-pointer switch before any write;
- message ordering is deterministic by accepted timestamp with a stable identifier as a
  tie-break where needed;
- a resume package may be older than the claim, but the resumed interaction loads the
  latest claim before deciding the next action;
- a stale session summary, stale UI revision, or previously rendered Workbench detail
  cannot roll the claim back;
- an Agent decision links to the claimant message that triggered it and records the
  resulting revision;
- the applied Branch Evaluation names the same resulting revision, while form and contents
  assertion histories retain the source message or validated retrieval reference;
- question counters and history are part of the session in the same Agent-turn mutation and do
  not advance when the Claim, messages, or decision fail to commit;
- a staff message is interaction-scoped: it uses the active session, retains
  `ActorType.STAFF`, and binds its session/message identities in the same staff mutation
  that advances the claim revision.

## Handoff and Staff Coordination

A handoff is a child work record, not a second claim status store.

- its immutable identity/reason/type/source packet remains linked to one claim;
- acceptance/resolution/status/owner changes that materially affect shared work are
  revision-checked claim mutations;
- one staff mutation may atomically store the updated handoff, staff action, customer-safe
  update, shared message, or signal decision that belong to the same operation;
- staff actions, customer updates, and signal decisions that do not belong to a claimant
  interaction may use an empty idempotency `session_id`; they still require the same
  authoritative `claim_id`, staff actor identity, and relevant child identity;
- when a staff mutation includes a message, the message must be a staff-authored record
  on the claim's active session and the idempotency session/message links must match it;
- claimant-visible updates are separate from internal reason/result data even though both
  may be committed in one transaction;
- a failed staff or handoff mutation leaves the claim and every supplied child record at
  the previous snapshot.
- terminal reopen is a staff mutation with no new child work record: it atomically clears the
  embedded terminal record, stores the first Workbench response, and appends one internal audit
  fact carrying the prior terminal sources and resulting revision.

## Visibility Boundary

Atomic persistence does not imply common visibility.

The repository stores authoritative records, while API/service projections enforce
claimant-visible, shared, internal-only, and restricted administration boundaries.
Persisting an internal review signal, staff action, or handoff context in the same
provider transaction as a claim update does not make that record claimant-visible.

Likewise, visibility filtering must not create a second mutable claim copy. Claimant and
Workbench responses are projections of the same committed state.

## External Side Effects

A provider transaction can protect Northwind-owned records but cannot assume a remote
claims system, assessor, storage provider, or handoff dispatcher participates in the same
transaction.

Application orchestration therefore distinguishes:

1. durable Northwind intent/state;
2. external invocation;
3. provider result/failure record or bounded fallback;
4. idempotent recovery/replay.

Where the existing contract persists a durable local handoff before dispatch, a dispatch
failure must retain that one handoff and report the bounded fallback rather than rolling
back into "no request". Where an external operation must happen before applying a result,
a failure must not fabricate a successful Claim State transition.

No provider-specific SDK object or remote transaction handle crosses the repository
boundary.

## Failure Matrix

| Failure | Required repository result |
| --- | --- |
| Claim missing / ownership link invalid | no bundle member written |
| Stale `expected_revision` | `RevisionConflict`; no bundle member written |
| Proposed revision is not exactly `expected + 1` | invalid bundle; no bundle member written |
| Non-session mutation proposes a different `active_session_id` | invalid bundle; no bundle member written |
| Child belongs to another claim/session/customer | invalid bundle; no bundle member written |
| Idempotency record points to another claim/child | invalid bundle; no bundle member written |
| Same key with changed fingerprint | `IdempotencyConflict`; no new bundle member written |
| Duplicate client message / operation identity | idempotent replay or conflict according to the operation; never a second domain action |
| Provider transaction fails before commit | pre-mutation snapshot remains authoritative |
| External dependency fails after durable local intent | keep the committed local intent and expose the documented retry/fallback state; do not duplicate on recovery |

## Issue #237 Baseline Audit and Current Provider Status

The implementation audit that motivated Issue #237 was performed on the historical
baseline `main@8834fdd7720ef454de188934319165aa483a857d`. At that baseline, the repository
already had the correct mutation-family shape and several strong guards:

- `save_session_mutation` requires one revision advance and validates claim/customer/
  session/idempotency links before writing;
- `save_agent_turn` validates claimant/Agent actors, trigger/reply relationships,
  decision linkage, optional handoff/evidence ownership, and idempotency identities;
- retrieval and directly derived review signals are persisted as one non-revisioning
  evidence bundle;
- existing tests prove stale session mutations and inconsistent Agent-turn bundles do not
  partially write state.

The historical baseline fixture adapter was not yet fully uniform. The Day 1 audit found:

- `save_message_mutation` did not yet enforce the complete claim/session/customer/
  context/idempotency relationship set;
- `save_staff_mutation` did not yet require exactly-one claim revision advance or fully
  bind its idempotency record to the mutated claim and any interaction-scoped child;
- `save_agent_turn`, `save_evidence_mutation`, and `save_handoff_mutation` validated many
  relationships but did not all explicitly reject a proposed claim revision jump greater
  than one.

Those were implementation gaps in the historical fixture runtime, not reasons to
redefine the contract. The #237 implementation hardens those preconditions and adds
adversarial snapshot tests.

Current `main` contains the MongoDB persistence foundation and the separately merged #304
connection/lifecycle hardening. The #237 branch adds bounded logical checks to that
adapter so child mutations cannot replace the authoritative active-session pointer and
message mutations require an ACTIVE matching session. These `mongomock`-backed contract
checks are not evidence of real Atlas transaction rollback/concurrency or complete
provider/runtime conformance. The full MongoDB runtime remains outside this issue and
must not be inferred from logical adapter tests.

## Repeatable Acceptance Checks

The #237 implementation is complete when another contributor can repeat tests proving:

1. every material mutation accepts `N -> N+1` and rejects a revision jump;
2. stale expected revision leaves claim, child records, and idempotency state unchanged;
3. all non-session material mutation families reject a proposed `active_session_id`
   change, while dedicated resume/start and pause/checkpoint mutations respectively
   establish and clear the authoritative active Session;
4. cross-claim/customer/session/message/handoff/idempotency links fail before any write;
5. an invalid Agent or staff bundle does not leave a message, decision, update, handoff,
   or idempotency record behind;
6. session-agnostic staff work remains valid without inventing a claimant-session link,
   while staff messages require a staff actor and the active interaction session;
7. retrieval + review-signal atomicity remains source-preserving without advancing claim
   revision merely for retrieval;
8. existing claimant ownership, role-safe projection, resume, handoff, staff-writeback,
   and canonical-scenario regressions remain green;
9. MongoDB logical contract tests prove the same active-session preservation invariant
   without presenting `mongomock` as live Atlas transaction evidence.

A green provider-specific happy-path test alone is insufficient. The acceptance result
must include failure atomicity and cross-record mismatch cases.

## P17.1 Recovery Follow-up Clarification

The pause/checkpoint mutation binds its idempotency request fingerprint to the accepted Claim
revision and persists one open recovery Follow-up per Claim and purpose. The Follow-up carries its
purpose, source references, channel/due metadata, attempt count, and explicit contact-permission
condition; a browser-anonymous claimant without an authorised durable channel is `blocked`, not
scheduled.

Activating a new claimant Session for a Claim with an open `resume_incomplete_claim` Follow-up
must resolve that Follow-up in the same provider-neutral mutation. A resolved historical record no
longer makes the Claim incomplete and does not prevent a later interruption from creating a new
open record for the same purpose. Claimant and Workbench incomplete state use one accepted
predicate: the Claim is not `created`, `customer_next_step.can_resume=true`, there is no
authoritative active Session, and a relevant paused recovery checkpoint plus open recovery
Follow-up exist. The checkpoint records the exact durable source reference for its latest
qualifying claimant message or accepted claimant business action.
