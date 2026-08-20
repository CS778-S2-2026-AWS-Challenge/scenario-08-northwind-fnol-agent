# Persistence Contract

## Status and Boundary

This document defines provider-neutral logical records, access patterns, and consistency
rules. It does not prescribe a Cloudflare, MongoDB, AWS, or fixture physical schema.
Physical mappings belong inside the selected runtime-profile adapters and must preserve
this contract.

Public APIs expose domain identifiers and typed projections only. They never expose
collection names, table names, partition keys, indexes, bucket keys, vector-index names,
provider payloads, or SDK types.

## Logical Record Groups

| Group | Records | Primary ownership |
| --- | --- | --- |
| Customer | authorised identity reference, permitted contact and communication preferences | `customer_id` |
| Claim | Working Claim State, structured facts, independent attributes, workflow, next action, revision | `claim_id`, linked to `customer_id` |
| Interaction | sessions, messages, compact summaries, unresolved work, prior commitments | `claim_id` and `session_id` |
| Evidence | evidence metadata, provenance, lifecycle state, protected object reference, extracted proposals | `claim_id` and `evidence_id` |
| Retrieval | structured policy/history results, knowledge citations, limitations, source versions | `claim_id` and retrieval identity |
| Review | internal signals, source references, professional decisions, staff actions | `claim_id` and work identity |
| Handoff | transfer packet, priority, queue, owner, status, lifecycle timestamps | `claim_id` and `handoff_id` |
| Integration | claim-creation result, routing result, external participant task, idempotency result | `claim_id` and operation identity |
| Configuration | versioned model, knowledge, rule, integration, access, feature, and runtime-profile configuration | configuration type and version |
| Audit | append-only claim, integration, configuration, and access events | event identity and subject |

Original evidence bytes, policy documents, and other large objects are stored through
the active profile's object or document store. Domain records retain protected references
and checksums rather than embedding those bytes.

## Required Access Patterns

1. Read one claim after verifying customer ownership or authorised staff access.
2. List a customer's working claims in a stable order without exposing another customer.
3. Read the current Working Claim and conditionally write one material revision.
4. Create, pause, close, and resume claim-scoped sessions without copying older Claim
   State over a newer revision.
5. Append and page messages while filtering visibility before projection.
6. Register, update, and list evidence metadata while preserving object provenance.
7. Save structured retrieval results and source-linked review signals atomically.
8. Read staff queues by priority, state, owner, next action, and service timing.
9. Accept and resolve handoffs and staff work through the same claim revision boundary.
10. Record idempotency results by actor, operation, client key, and request fingerprint.
11. Resolve the active configuration version and read its immutable publication record.
12. Append audit events and query them by authorised subject and time range.

## Claim Revision and Idempotency

- `WorkingClaim.revision` is the single optimistic-concurrency token for shared material
  claim writes.
- A mutation using a stale expected revision fails without a partial write.
- A successful material mutation advances the revision exactly once.
- An idempotency record identifies an accepted operation and request fingerprint. An
  identical replay returns the current authorised projection; changed input under the
  same key is a conflict.
- Child records must not introduce a second concurrency counter that permits them to
  overwrite shared Claim State.

## Session and Resume Invariants

- The Working Claim is authoritative; sessions hold bounded interaction context only.
- A session summary records the claim revision it represents. That revision may lag but
  must not exceed the current claim revision.
- Complete messages remain durable outside the bounded summary.
- Resuming creates or activates an interaction session for the same `claim_id`; it does
  not create a duplicate working claim.
- At most one claimant interaction session is active for a working claim unless a later
  approved product contract explicitly changes this rule.
- Resume preserves confirmed facts, evidence records, pending work, and prior
  commitments while using the latest authorised Claim State.

## Evidence Invariants

- Evidence metadata and original bytes are separate.
- A protected object reference is adapter-owned and never appears in claimant responses.
- Extraction produces source-linked proposals; it does not confirm a claim fact.
- Evidence lifecycle writes preserve ownership, checksum, provenance, and permitted
  visibility.
- Pending, incomplete, unofficial, and not-yet-generated evidence remain distinct states.

## Retrieval and Review Invariants

- Structured policy/history results and knowledge citations preserve source, version,
  retrieval time, limitations, and visibility.
- Raw provider payloads and discarded provider-only fields are not persisted as domain
  facts.
- A retrieval and any directly derived review signal are saved atomically.
- Saving retrieval evidence does not itself advance claim revision or make a high-impact
  decision.
- Staff decisions are separate immutable records and retain the source references that
  motivated the review.

## Handoff and Staff-work Invariants

- A handoff retains immutable identity, type, reason, priority, requested action, source
  context, transfer packet, and creation time.
- Lifecycle changes may update status, owner, and applicable timestamps through a
  revision-checked claim mutation.
- Acceptance records one owner. Active work cannot be reassigned by a blind overwrite.
- Repeated support requests reuse an applicable active handoff rather than creating
  competing ownership.
- Staff write-back records actor, reason, outcome, evidence references, and a separate
  claimant-safe update.

## Configuration and Control Plane Invariants

- Draft configuration is separate from the active published version.
- Publication records author, reason, validation evidence, approver when required,
  effective time, previous version, and rollback target.
- Published versions are immutable. Rollback publishes or reactivates an approved prior
  version and preserves the intervening audit history.
- Secret values are stored in an approved secret manager. Configuration stores only a
  secret reference and safe metadata.
- Selecting a data runtime profile is a deployment-level configuration change. A process
  uses one complete profile and cannot mix provider stores silently.
- Administrative configuration must not provide unrestricted direct edits to production
  Claim State.

## Provider Conformance

Each implemented runtime profile must pass the same repository and behaviour contract
tests for ownership, revision, idempotency, visibility, resume, evidence provenance,
retrieval source preservation, handoff ownership, configuration publication, and error
atomicity.

Candidate physical services and open provider decisions are recorded in
`docs/data-architecture.md`. Availability, schema, identity, region, limits, retention,
transactions, backup, recovery, and migration remain unconfirmed until verified for the
selected profile.
