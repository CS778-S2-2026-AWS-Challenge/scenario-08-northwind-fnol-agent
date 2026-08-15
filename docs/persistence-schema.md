# Persistence Schema Draft

## Status and Boundary

This is a Sprint 1 design draft for the persistence boundary. It is a logical
model, not confirmation of an AWS table, index, region, identity, or service
configuration. Those facts remain open until the provided environment is
inspected.

The public API exposes domain identifiers and typed records only. It never
exposes partition keys, sort keys, index names, table names, object keys, or
provider payloads. Route handlers depend on `PersistenceRepository` rather
than a DynamoDB SDK.

## Logical Item Layout

The draft uses one logical record collection. A future adapter may use one or
more physical stores if it preserves these access patterns and repository
methods.

| Record | Logical partition | Logical sort | Required parent |
|---|---|---|---|
| Working claim | `CLAIM#<claim_id>` | `CLAIM` | customer ownership in the item |
| Session | `CLAIM#<claim_id>` | `SESSION#<session_id>` | claim and customer |
| Message | `CLAIM#<claim_id>` | `MESSAGE#<created_at>#<message_id>` | claim and session |
| Agent decision | `CLAIM#<claim_id>` | `DECISION#<created_at>#<decision_id>` | claim, session, and trigger message |
| Evidence | `CLAIM#<claim_id>` | `EVIDENCE#<evidence_id>` | claim |
| Handoff | `CLAIM#<claim_id>` | `HANDOFF#<created_at>#<handoff_id>` | claim |

Customer claim listing needs a logical customer lookup:
`CUSTOMER#<customer_id>` with `CLAIM#<created_at>#<claim_id>` ordering. Whether
this is implemented as a DynamoDB secondary index or another query mechanism
is intentionally undecided.

The key templates are implemented in
`backend/repositories/key_layout.py`. They are adapter internals and are not
part of HTTP request or response models.

## Required Access Patterns

1. Read one claim after verifying the authenticated customer owns it.
2. List a customer's working claims ordered by creation time.
3. Read one session under its claim and retain its resume revision.
4. Append and page messages for one claim/session, filtering visibility before
   claimant projection.
5. Save and restore the validated Agent decision associated with a trigger
   message, including its authority outcome and resulting claim revision.
6. Read or list evidence under a claim without returning another customer's
   records.
7. Save a material claim revision only when the expected revision still
   matches; otherwise return a repository revision conflict.
8. Record idempotency results using actor, route, and client key.
9. Read handoff priority, owner, status, reason, and transfer packet under the
   claim, then persist lifecycle changes with the same expected claim revision
   used for the associated shared-state write.

## Record Rules

- All identifiers are server-generated except a claimant's retry key.
- Every child record carries its `claim_id`; messages also carry
  `session_id`.
- `MessageVisibility.INTERNAL_ONLY` is never returned by claimant APIs.
- Evidence stores metadata, provenance, processing state, and a secure object
  reference owned by the adapter. File bytes and signed upload URLs are not
  stored in the domain record.
- Claim and child writes must preserve ownership and optimistic-concurrency
  checks at the repository boundary.
- Complete messages remain durable; session summaries are bounded resume
  context, not a replacement for message history.
- Agent decisions preserve the proposal, reason codes, authority validation,
  proposed form changes, and resulting revision. A review-required or blocked
  high-impact proposal is recorded without applying its high-impact state change.

## Session snapshots, resume, and revision invariants

- `WorkingClaim` is the authoritative current FNOL state. Session records do
  not own a private copy of Claim State and must not overwrite newer claim
  state during resume.
- A `SessionRecord` stores bounded interaction context: its compact summary,
  unresolved questions, pending items, prior commitments, and the claim
  revision represented by that context. Complete messages remain durable
  records outside the bounded session snapshot.
- `SessionRecord.context_revision` is the `WorkingClaim.revision` from which
  the bounded session context was captured or last synchronised. It may lag
  the current claim revision, but it must never be greater than the current
  claim revision.
- `context_revision` is provenance for resume context, not an optimistic-lock
  token. Material Claim State writes use `WorkingClaim.revision` and the
  repository expected-revision check.
- Resuming an existing working claim continues the same `claim_id`. A new
  interaction session may be created, but resume must not create a duplicate
  working claim or replace confirmed claim facts with an older session
  snapshot.
- At most one claimant session for a working claim is active at a time, and
  `WorkingClaim.active_session_id` identifies that active interaction.
- Historical paused or closed sessions may retain an older
  `context_revision`. Recovery logic may use their bounded context as input,
  but the current `WorkingClaim` remains authoritative when the two differ.
- Future persistence adapters must preserve these invariants without exposing
  provider keys or creating a second concurrency model beside
  `WorkingClaim.revision`.

## Handoff persistence, ownership, and revision invariants

- A `HandoffRecord` is a claim-scoped durable child record. Priority, queue,
  support need, reason codes, reason, requested action, transfer packet,
  ownership, status, and lifecycle timestamps are persisted rather than kept
  only in a workbench projection.
- `WorkingClaim.revision` remains the single optimistic-concurrency token for
  handoff lifecycle changes. Accepting, continuing, cancelling, or resolving a
  handoff must use the current claim revision and advance that revision exactly
  once when shared state changes. There is no independent handoff revision
  counter.
- The revision returned by handoff mutation responses is therefore the parent
  `WorkingClaim.revision` produced by that material handoff write. This keeps
  the handoff and shared Claim State in one concurrency domain.
- A newly requested or queued handoff has no staff owner. Acceptance assigns an
  owner and records `accepted_at`. Once an owner is persisted, later active
  work must be performed by that owner and the owner cannot be replaced by a
  blind record overwrite.
- Allowed lifecycle movement is `requested -> queued -> accepted ->
  in_progress -> resolved`, with cancellation permitted before acceptance.
  Repeated in-progress writes may retain `in_progress`; resolved and cancelled
  records are terminal.
- Handoff identity, type, priority, queue, support need, reason, requested
  action, source context, transfer packet, and creation timestamp are immutable
  after creation. Lifecycle writes may update status, owner, and the applicable
  acceptance or resolution timestamps only.
- Direct `save_handoff` writes may seed a new record or repeat an identical
  record, but they must not overwrite an existing handoff. Material lifecycle
  changes must go through a revision-checked mutation.
- Idempotency metadata for a handoff mutation identifies the same
  `handoff_id`. A repeated claimant support request reuses the existing active
  handoff where applicable instead of creating a second record with competing
  ownership.
- A future persistence adapter must enforce the same revision, ownership, and
  transition invariants even if its physical transaction or conditional-write
  mechanism differs from the fixture repository.

## Unknowns and Next Decision Points

- AWS identity provider, table/index availability, region, throughput model,
  retention, encryption, and object storage are unconfirmed.
- The physical mapping, serialization format, pagination token, retry policy,
  and transaction support must be selected after AWS access is inspected.
- A future DynamoDB adapter must implement `PersistenceRepository` and its
  contract tests without changing route handlers or claimant projections.
