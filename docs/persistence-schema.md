# Persistence Contract

## Status and Boundary

This document defines provider-neutral logical records, access patterns, and consistency
rules. It does not prescribe a Cloudflare, MongoDB, AWS, or fixture physical schema.
Physical mappings belong inside the selected runtime-profile adapters and must preserve
this contract.

The MongoDB repository is selected only by the explicit `local_mvp` development profile. Its
method surface covers Claim, Session, Message, Agent Decision, Evidence metadata,
Retrieval, Review Signal, Handoff, Staff Action, Customer Update, Signal Decision, and
Idempotency records. Mock-backed tests verify document mapping, ownership filters,
relationship checks, revision conflicts, and mutation ordering. The local replica-set smoke
verifies real multi-document writes, restart recovery, and stale-revision refusal. The additional
shared transaction-boundary hardening in PR #288 remains a merge dependency and is not duplicated
here.

The adapter owns bounded environment parsing and verified client construction through
`MongoDBConnectionConfig` and `connect_mongodb_repository`. A connection is exposed to the
repository only after `ping` and index initialisation succeed; failure closes the client and
raises a bounded error without returning the connection URI. The non-secret setting names are:

- `NORTHWIND_MONGODB_URI` (secret-bearing value supplied only through process configuration);
- `NORTHWIND_MONGODB_DATABASE`;
- `NORTHWIND_MONGODB_COLLECTION`; and
- `NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS`.

These connection primitives do not by themselves enable any runtime profile.

`DATA_RUNTIME_PROFILE=mongodb` MUST continue to fail closed until the repository is
verified against a transaction-capable supported MongoDB deployment, the protected
evidence-byte adapter is implemented, and a complete `DataRuntimeBundle` is assembled.
`DATA_RUNTIME_PROFILE=local_mvp` is separately available for the verified local MongoDB + MinIO
development composition. It does not claim Atlas object storage, Atlas Search, or production
provider conformance; policy and claim-history lookups remain synthetic. MongoDB adapter
documents use `record_type` as their internal discriminator so domain fields such as
Evidence `kind` and Retrieval `kind` remain unchanged.

Public APIs expose domain identifiers and typed projections only. They never expose
collection names, table names, partition keys, indexes, bucket keys, vector-index names,
provider payloads, or SDK types.

The TurnPlan, namespaced ActionEnvelope, WorkItem, Model Profile, and complete external
request lifecycle described below are target logical contracts. The current persistence
implementation still stores the legacy Agent Decision shape and must not be represented
as supporting the target records until migrations, repository methods, API projections,
fixtures, and transaction tests change together.

## Logical Record Groups

| Group | Records | Primary ownership |
| --- | --- | --- |
| Customer | authorised identity reference, permitted contact and communication preferences | `customer_id` |
| Claimant auth session | hash of an opaque development/test token, authenticated customer reference, creation, expiry, and revocation timestamps | `token_hash`, linked to `customer_id` |
| Customer memory | source-linked explicit preference or expiring continuity hint, visibility, expiry, correction state | `customer_id`, `memory_id` |
| Claim | Working Claim State, structured facts, independent attributes, lifecycle status, workflow, next action, current staff assignee when allocated, responsibility, retention timestamps, revision | `claim_id`, linked to `customer_id` |
| Work | independent question, evidence, confirmation, professional judgement, external request, and system WorkItems with owner, blocker, due time, sources, and completion evidence | `claim_id`, `work_item_id` |
| Interaction | intent, sessions, messages, compact summaries, unresolved work, prior commitments | `session_id`, optionally linked to `claim_id` |
| Agent turn | TurnPlan, AgentProposal, ExecutionPlan, ActionEnvelopes, ToolRequests and results, TurnResult, policy and Registry versions, usage, latency, limitations | `turn_id`, linked to session and optional Claim |
| Evidence | evidence metadata, provenance, lifecycle state, protected object reference, extracted proposals | `claim_id` and `evidence_id` |
| Retrieval | structured policy/history results, knowledge citations, limitations, source versions | `claim_id` and retrieval identity |
| Review | internal signals, source references, professional decisions, staff actions | `claim_id` and work identity |
| Handoff | transfer packet, priority, queue, owner, status, lifecycle timestamps | `claim_id` and `handoff_id` |
| Follow-up | due time, responsible party, attempt count, channel, outcome, status | `claim_id` and `follow_up_id` |
| Integration | external-service consent, claim-creation result, durable routing operation intent/outcome, routing result, external participant task, idempotency result | `claim_id` and consent or operation identity |
| External request | capability and requirement versions, request type, disclosure manifest, consent and authority, idempotency, provider reference, status, verified response, reconciliation result | `claim_id`, `external_request_id` |
| Configuration | versioned Agent Policy, Registry snapshots, model profiles, knowledge, rule, integration, access, feature, and runtime-profile configuration | configuration type and version |
| Audit | append-only claim, integration, configuration, and access events | event identity and subject |
| Retention | expiry, hold, purge eligibility, deletion or anonymisation result | subject identity and retention job |

Original evidence bytes, policy documents, and other large objects are stored through
the active profile's object or document store. Domain records retain protected references
and checksums rather than embedding those bytes.

## Required Access Patterns

1. Read one claim after verifying customer ownership or authorised staff access.
2. List a customer's working claims in a stable order without exposing another customer.
3. Read the current Working Claim and conditionally write one material revision.
4. Create, pause, close, and resume sessions without copying older Claim State over a
   newer revision; a non-claim session may exist without a `claim_id`.
5. Append and page messages while filtering visibility before projection.
6. Register, update, and list evidence metadata while preserving object provenance.
7. Save structured retrieval results and source-linked review signals atomically.
8. Read staff queues by priority, state, owner, next action, and service timing.
9. Accept and resolve handoffs and staff work through the same claim revision boundary.
10. Record idempotency results by actor, operation, client key, and request fingerprint.
11. Resolve a current task-specific claimant consent before invoking an external participant.
12. Reserve an immutable external-operation identity and fingerprint before invocation, then
    recover its accepted result independently of a later Claim State compare-and-set.
13. Resolve the active configuration version and read its immutable publication record.
14. Read customer memory only through a purpose-limited, visibility-filtered access path.
15. Create and process follow-up tasks by due time, responsibility, priority, and status.
16. Append audit events and query them by authorised subject and time range.
17. Read one complete turn by `turn_id` and distinguish proposal, approval, execution,
    state effect, and final role projection without exposing hidden or restricted data.
18. List open WorkItems by Claim, owner, type, status, blocked action, due time, and
    priority without treating Claim lifecycle as the only work status.
19. Reconcile an external request by Northwind operation identity, idempotency key, or
    provider reference before any retry after an unknown outcome.
20. Resolve one active, evaluated Model Profile by purpose and privacy class without
    returning endpoint credentials to Runtime or a browser.
21. Resolve an unexpired and unrevoked claimant session by token hash without allowing a
    browser-supplied customer identifier to alter the authenticated principal.
22. Read and update the authenticated claimant's approved profile and communication
    preferences by `customer_id` without exposing another Customer record.

## Development/Test Identity Invariants

- Raw claimant access tokens are returned once and are never persisted; repositories retain
  only a one-way token hash.
- A session binds exactly one server-selected `customer_id`, creation time, expiry time, and
  optional revocation time.
- Expired or revoked sessions cannot authenticate and logout is immediately effective.
- Synthetic credential verification and session persistence are fixture capabilities only;
  selecting a production environment fails closed until an approved identity provider and
  durable identity adapter exist.
- Profile and communication preferences are Customer records, not browser-local authority.
- Authentication data cannot grant staff roles, change claim ownership, or enter Claim State.

## Claim Revision and Idempotency

- `WorkingClaim.revision` is the single optimistic-concurrency token for shared material
  claim writes.
- A mutation using a stale expected revision fails without a partial write.
- A successful material mutation advances the revision exactly once.
- An idempotency record identifies an accepted operation and request fingerprint. An
  identical replay returns the current authorised projection; changed input under the
  same key is a conflict.
- External-service consent records are claim-scoped and retain service identity, requested
  action, minimum permitted fields, grant or withdrawal state, actor, and timestamps. A
  consent change advances the Working Claim revision; an adapter result cannot invent or
  reactivate consent.
- The claimant consent mutation atomically stores its idempotency result with the one Claim State
  revision advance. The assessor request uses a separate operation identity so provider retry does
  not replay or rewrite the consent mutation.
- Assessor routing persists its immutable identity, complete request fingerprint, consent and
  authority references, authorised claim revision, and `prepared` state before provider
  invocation. The authority decision and prepared operation are one atomic repository mutation;
  retries never replace the durable decision record. Retryable failure, terminal failure, and
  accepted result are explicit transitions.
- Provider acceptance is durable before the final Claim State compare-and-set. If another claim
  mutation advances the revision first, an unchanged retry reconciles the accepted result into a
  new claim revision without invoking or creating a second external task.
- If the Claim result is durable but the public route-idempotency response is not, an unchanged
  retry derives the same decision identity, verifies its authorised revision, restores the stored
  routing result, and then completes the missing idempotency response.
- Child records must not introduce a second concurrency counter that permits them to
  overwrite shared Claim State.

## Session and Resume Invariants

- The Working Claim is authoritative; sessions hold bounded interaction context only.
- A session may have `interaction_intent = non_claim_intent` and no `claim_id` when the
  conversation has no credible claim purpose.
- Once a session has produced material incident facts, a draft claim may be linked to
  it; later unrelated messages remain session-only and must not overwrite claim facts.
- A session summary records the claim revision it represents. That revision may lag but
  must not exceed the current claim revision.
- Complete messages remain durable outside the bounded summary. Message lists use the stable
  `(created_at, message_id)` ascending order, including when timestamps are equal.
- A message `in_reply_to` reference may identify only a message belonging to the same claim and
  interaction session.
- Resuming creates or activates an interaction session for the same `claim_id`; it does
  not create a duplicate working claim.
- At most one claimant interaction session is active for a working claim unless a later
  approved product contract explicitly changes this rule.
- Resume preserves confirmed facts, evidence records, pending work, and prior
  commitments while using the latest authorised Claim State.

## Claim Lifecycle, Follow-up, and Retention Invariants

- Claim lifecycle status is an enumerated state with approved transitions, not a set of
  unrelated booleans such as `saved`, `active`, and `abandoned`.
- Content branches are not lifecycle states. Activating or correcting motor, collision,
  participant, evidence, support, or authority content cannot silently move lifecycle or
  rewrite a staff decision.
- Several WorkItems may coexist under one lifecycle state. Each item names the exact
  action it blocks; a waiting item cannot imply that unrelated work is blocked.
- A paused or incomplete claim retains the next action, blocking reason, responsible
  party, priority band, last meaningful customer activity, follow-up due time, and expiry
  time needed for safe resume and staff work.
- `waiting_customer`, `waiting_external`, explicit customer withdrawal, and
  timeout expiry remain distinguishable outcomes.
- Follow-up is a separate work record. Agent or staff automation cannot silently create
  an outbound contact without the approved channel, consent, frequency, and authority
  rules.
- Expiry makes a record eligible for retention processing; an Agent turn must not delete
  claim data directly.
- Purge processing must distinguish claim-specific deletion, required audit retention,
  and permitted anonymised aggregates. A `retention_hold` requires a source, reason,
  owner, and review or expiry condition.
- A user-level continuity hint may survive claim purge only when it is purpose-limited,
  source-linked, visibility-controlled, and has an expiry or deletion rule. Full claim
  facts and transcripts must not be copied into Customer.
- A customer deletion request must resolve all records linked by `customer_id`, including
  memory, sessions, follow-up, evidence references, and retention records, subject to a
  documented legal or audit exception.

## Customer Memory Invariants

- Customer Memory is separate from Customer identity and from Claim State.
- Only explicit preferences or bounded, category-level continuity facts with a clear
  product purpose may be stored.
- A single interruption must not create a permanent reliability, fraud, or service-priority
  classification.
- Each memory record retains source, visibility, correction status, created time, and
  expiry or deletion behaviour.
- Memory is never used as an unreviewed substitute for current claim facts, policy
  records, evidence, or professional decisions.

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
- An Agent decision identifies whether its proposal came from `controlled_agent` or
  `model_gateway`. A model-backed decision retains only bounded audit provenance: runtime
  profile, executable prompt identifier, provider-reported model identifier, and provider request
  identifier when supplied.
  These provider references are internal-only and never enter claimant projections.
- Model-authored customer prose and model-proposed internal signals are not persistence
  authority. Claimant-visible response fields are server-rendered after deterministic
  validation, and any non-empty model signal proposal rejects the complete turn before write.

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

## Agent Turn and Action Invariants

- `TurnPlan`, `AgentProposal`, `ExecutionPlan`, and `TurnResult` are separate immutable
  records or immutable revisions. They must not share one mutable status field that makes
  a proposal appear executed.
- One turn may contain several conversation moves and command proposals but exactly one
  primary Runtime control directive.
- Every ActionEnvelope retains stable identity, namespace, registered action name,
  target, proposer, reasons, sources, inputs, preconditions, authority, expected effects,
  visibility, idempotency where applicable, and actual status.
- Rejected proposals remain traceable with a controlled reason but do not advance Claim
  revision. Successful material mutations advance the authoritative Claim revision under
  the existing transaction boundary.
- Tool requests and results retain tool version, purpose, actor and Claim scope, argument
  summary, required authority, disclosure manifest, idempotency, outcome, and diagnostic
  reference. Credentials and unnecessary raw provider payloads are not retained.
- The final role projection is derived after execution. It cannot claim that a proposed,
  requested, queued, failed, or unknown action succeeded.

## Model Profile and External-request Invariants

- A Model Profile stores adapter and endpoint references, provider model identity,
  verified capabilities, data terms, allowed privacy classes and purposes, fallback
  group, evaluation bundle, lifecycle, and secret reference. It never stores plaintext
  credentials.
- The model profile actually used is retained for every invocation, including a qualified
  fallback. Fallback cannot silently widen context, weaken schema requirements, or change
  the active data-runtime profile.
- An external request separates capability discovery, requirements, draft and disclosure
  manifest, authority, submission, tracking, response verification, and Claim
  reconciliation. Provider acknowledgement and completion are separate states.
- A timeout after possible submission records `unknown_outcome`. The same operation
  identity must be used to query status before retry; a new request cannot be created
  until non-submission is confirmed or an idempotent replay is proven safe.
- An external response cannot mutate Claim State until provenance, request linkage,
  schema, current revision, field conflicts, and required authority are validated.

## Configuration and Control Plane Invariants

The fixture configuration repository used by the bounded Admin API stores immutable revisions
behind the same provider-neutral boundary that later profiles must implement. Configuration IDs
use the `cfg_` prefix and audit event IDs use `aud_`; the physical partition and sort-key mapping
is profile-specific and must preserve these access patterns.

Each configuration revision contains `configuration_id`, `domain`, `revision`, `state`,
`impact`, non-secret `values`, protected `secret_references`, `author`, `reason`, optional
`validation_evidence`, `effective_time`, `previous_version`, `rollback_target`, and
`updated_at`. Audit events contain `event_id`, `configuration_id`, `revision`, `actor`,
`action`, `reason`, `outcome`, and `created_at`. Audit events are append-only and are not
deleted or rewritten during withdrawal, supersession, or rollback.

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
- Retention and purge configuration is versioned policy, not an unreviewed database job
  embedded in one provider adapter.
- Field, Content Branch, Lifecycle, Action, Tool, Staff Capability, Model Profile, and
  Error Registry versions are independently identifiable. A Claim and Agent turn retain
  the versions used for their decisions.

## Provider Conformance

Each implemented runtime profile must pass the same repository and behaviour contract
tests for ownership, revision, idempotency, visibility, resume, evidence provenance,
retrieval source preservation, handoff ownership, configuration publication, and error
atomicity.

Candidate physical services and open provider decisions are recorded in
`docs/data-architecture.md`. Availability, schema, identity, region, limits, retention,
transactions, backup, recovery, and migration remain unconfirmed until verified for the
selected profile.
