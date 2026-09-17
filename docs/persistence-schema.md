# Persistence Contract

## Status and Boundary

This document defines provider-neutral logical records, access patterns, and consistency
rules. It does not prescribe a Cloudflare, MongoDB, AWS, or fixture physical schema.
Physical mappings belong inside the selected runtime-profile adapters and must preserve
this contract.

The MongoDB repository is selected only by the explicit `local_mvp` development profile. Its
method surface covers Claim, Session, Message, applied Runtime turn records and compatibility Runtime Trace, Agent Decision, Branch Evaluation, Audit Event, Evidence metadata,
External Task, external request, and task-to-evidence link records, Retrieval, Review Signal, Handoff, Staff
Action, Customer Update, Signal Decision, and Idempotency records. Mock-backed tests verify
document mapping, ownership filters,
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

The TurnPlan, AgentProposal, ExecutionPlan, namespaced ActionEnvelope, ToolResult, TurnResult,
and claimant-question WorkItem records are implemented as one atomic Runtime turn bundle. The
records are immutable execution evidence and never become a second Claim State. Repository
readback is ownership-filtered and idempotent in both Fixture and Mongo adapters. The external-task
slice stores the task's claim, service/action, source class, operation and delivery state,
failure/provider reference, timestamps, one immutable originating task per evidence item, and
one `erq_` request per task. The request records its purpose, disclosed field names, independent
Northwind-authority and claimant-consent references, authorised Claim revision, preparation
time, first send time, and stable operation identity. The controlled assessor path also stores one
returned result per task, its source and receipt time, linked Evidence identifiers, verification
state, verification time, and checked Claim revision. Later provider attempts and reconciliation
records remain target contracts.

## Logical Record Groups

| Group | Records | Primary ownership |
| --- | --- | --- |
| Customer | authorised identity reference, permitted contact and communication preferences, active state, revision, and update time | `customer_id` |
| Identity record | protected identity-document reference, masked value, type, issuer, verification state, dates, provenance, and revision | `identity_id` (`idn_`), linked to `customer_id` |
| Payment destination | protected account reference, masked account number, type/name, verification state, dates, and revision | `payment_destination_id` (`pyd_`), linked to `customer_id` |
| Policy summary | bounded policy identity, product family, display status, effective dates, and provenance | `policy_id` (`pol_`), linked to `customer_id` |
| Claimant auth session | `ias_` session identity, hash of an opaque development/test token, authenticated customer reference, revision, creation, expiry, revocation, and update timestamps | `session_id`, linked to `customer_id`; token lookup uses `token_hash` |
| Staff account | local/runtime staff identity, salted password hash, display name, roles, active state, revision, and update time | `staff_id` |
| Staff auth session | `ias_` session identity, hash of an opaque staff token, authenticated staff reference, revision, creation, expiry, revocation, and update timestamps | `session_id`, linked to `staff_id`; token lookup uses `token_hash` |
| Customer memory | source-linked explicit preference or expiring continuity hint, visibility, expiry, correction state | `customer_id`, `memory_id` |
| Asset | account-owned typed vehicle, property, or contents details, revision, active state, and timestamps; Policy association is deferred until an owned `pol_` resource exists | `asset_id` (`ase_`), linked to `customer_id` |
| Claim | Working Claim State, structured facts, independent attributes, lifecycle status, optional source-linked terminal disposition, workflow, next action, current staff assignee when allocated, responsibility, retention timestamps, revision | `claim_id`, linked to `customer_id` |
| Claim asset snapshot | immutable approved asset details selected for one Claim revision, source asset/revision, provenance, and capture time | `snapshot_id` (`cas_`), linked to `claim_id`, `customer_id`, and `asset_id` |
| Work | independent question, evidence, confirmation, professional judgement, external request, and system WorkItems with owner, blocker, due time, sources, and completion evidence | `claim_id`, `work_item_id` |
| Interaction | intent, sessions, messages, compact summaries, unresolved work, prior commitments | `session_id`, optionally linked to `claim_id` |
| Staff Agent interaction | staff-owned persistent sessions, session-bound published model profile, explicitly scoped questions, source-aware answers, and drafts with stable identity; executable drafts carry a registered action proposal but remain non-executing until staff confirmation | `staff_id`, `session_id`, `message_id`, and `draft_id`; Claim IDs are per-message scope only |
| Staff Agent execution | immutable readback evidence for one explicitly confirmed draft and its registered Workbench handler result | `execution_id = sax_{draft_id}`; linked to the owned assistant message, exact draft, Claim, action, target, expected/resulting revision, and idempotency record |
| Agent turn | Target TurnPlan/AgentProposal/ExecutionPlan/ActionEnvelopes plus the implemented bounded Runtime Trace, ToolRequests and results, TurnResult, policy and Registry versions, selected external-service lifecycle coordinates, usage, latency, limitations | `turn_id`/`trace_id`, linked to session and optional Claim |
| Evidence | evidence metadata, provenance, lifecycle state, protected object reference, extracted proposals | `claim_id` and `evidence_id` |
| Participant | repeatable role, relationship, bounded contact/vehicle facts, contact consent, provenance, and revision | `participant_id` (`par_`), linked to `claim_id` and `customer_id` |
| Item-Evidence association | immutable same-Claim relationship and purpose connecting one ContentsItem to one Evidence record | `association_id` (`iea_`), linked to `claim_id`, `item_id`, and `evidence_id` |
| Mitigation | typed emergency-repair state, bounded summary, responsibility, Evidence and WorkItem references, provenance, and revision | `mitigation_id` (`mit_`), linked to `claim_id` |
| Retrieval | structured policy/history results, knowledge citations, limitations, source versions | `claim_id` and retrieval identity |
| Review | internal signals, source references, professional decisions, staff actions | `claim_id` and work identity |
| Handoff | transfer packet, priority, queue, owner, status, lifecycle timestamps, and support continuation target (`resume_workflow_state`, `resume_next_action`) | `claim_id` and `handoff_id` |
| Follow-up | due time, responsible party, attempt count, channel, outcome, status | `claim_id` and `follow_up_id` |
| Integration | published provider configuration references, adapter capability/health projection, external-service consent, claim-creation result, durable routing operation intent/outcome, routing result, external participant task, returned task result and verification, idempotency result | integration identity, `claim_id`, task, result, or consent/operation identity |
| External request | implemented purpose, disclosed field names, consent and authority, preparation and first send identity, controlled assessor result and verification; target capability/requirement versions, attempts, and reconciliation | `claim_id`, `request_id`, linked to `task_id` |
| Configuration | versioned Agent Policy, Registry snapshots, model profiles, knowledge, rule, integration, access, feature, and runtime-profile configuration | configuration type and version |
| Branch evaluation | immutable branch/form calculation evidence, selected family, active branches, field selection states, and Claim revision precondition | `claim_id`, `evaluation_id` |
| Audit | append-only claim, integration, configuration, account, and access events | event identity and subject |
| Retention | expiry, hold, purge eligibility, deletion or anonymisation result | subject identity and retention job |

Original evidence bytes, policy documents, and other large objects are stored through
the active profile's object or document store. Domain records retain protected references
and checksums rather than embedding those bytes.

## Audit Event Contract

The provider-neutral structural envelope is defined by `AuditEventEnvelope` in
`backend/domain/audit.py`. Its generated JSON Schema is committed at
`docs/contracts/audit-event.schema.json`; run `py -3.12 scripts/export_audit_contract.py`
to regenerate it, or add `--check` to detect drift. The snapshot is a mechanical shape
check and does not replace this semantic contract.

Each event is an immutable fact, not a second Claim State record. The envelope records a
controlled event type and outcome, the logical subject, actor and authentication source,
bounded reason and source references, applicable permission and consent references,
visibility, correlation or idempotency identity, the resulting Claim revision when the
subject is a claim, and the server-created timestamp. Raw provider payloads, secrets,
tokens, and unrestricted model context are excluded.

The initial event vocabulary is intentionally bounded to consent, permission, action,
and access outcomes. New event types or changes to field meaning require an explicit
contract update; additive optional fields are structural changes detected by CI.

The Fixture and MongoDB repositories implement provider-neutral immutable append and
authorised subject/time-range reads for this envelope. A Claim mutation may persist its
idempotency record, applied Branch Evaluation, and claim-scoped audit facts in one atomic
repository boundary. The implemented claimant assessor-consent mutation records a
`consent.granted` fact with the authenticated claimant actor and authentication source,
the consent identity/state, bounded reason/source reference, idempotency identity, and
resulting Claim revision. The controlled assessor-routing preparation records the
Northwind `permission.authorised` fact in the same repository boundary as the authority
decision and prepared operation, including the active claimant consent reference and
authorised Claim revision. These audit records use the audit-only visibility boundary
and are not added to claimant or staff API projections by #415.

The existing configuration-only `backend.domain.configuration.AuditEvent` projection
remains compatible with the Admin API and separate from this cross-domain repository
envelope. #415 does not redefine that API projection or claim that every target action,
failure, access, or configuration event is already wired.

Control Plane access policies are persisted as versioned `configuration` records with
`domain=access`. Their values contain a role, actor type, scopes, visibility classes, and an
optional protected credential reference; account password hashes and bearer tokens remain in the
identity stores and are never copied into Control Plane records. Administration audit search reads
the append-only audit collection through a bounded, filterable projection.

## Required Access Patterns

1. Read one claim after verifying customer ownership or authorised staff access.
2. List a customer's working claims in a stable order without exposing another customer.
3. Read the current Working Claim and conditionally write one material revision.
4. Create, pause, close, and resume sessions without copying older Claim State over a
   newer revision; a non-claim session may exist without a `claim_id`.
5. Append and page messages while filtering visibility before projection.
6. Register, update, and list evidence metadata while preserving object provenance.
7. List uploaded Evidence across a customer's Claims through a claimant-scoped,
   visibility-filtered history query without exposing adapter-owned storage keys.
8. Save structured retrieval results and source-linked review signals atomically.
9. Read staff queues by priority, state, owner, next action, and service timing.
10. Accept and resolve handoffs and staff work through the same claim revision boundary.
11. Record idempotency results by actor, operation, client key, and request fingerprint.
12. Persist an applied namespaced Runtime turn atomically with its claimant/agent messages,
    Claim revision, Session activity, Runtime trace, target turn records, WorkItems, and
    idempotency response.
13. Resolve a current task-specific claimant consent before invoking an external participant.
14. Reserve an immutable external-operation identity and fingerprint before invocation, then
    recover its accepted result independently of a later Claim State compare-and-set.
15. Resolve the active configuration version and read its immutable publication record.
16. List administration audit events by bounded actor, subject, event type, and time filters without
    exposing unrestricted claimant or provider payloads.
17. Read customer memory only through a purpose-limited, visibility-filtered access path.
18. Create and process follow-up tasks by due time, responsibility, priority, and status.
19. Append audit events and query them by authorised subject and time range.
20. Read one complete turn by `turn_id` and distinguish proposal, approval, execution,
    state effect, and final role projection without exposing hidden or restricted data.
21. List open WorkItems by Claim, owner, type, status, blocked action, due time, and
    priority without treating Claim lifecycle as the only work status.
22. Reconcile an external request by Northwind operation identity, idempotency key, or
    provider reference before any retry after an unknown outcome.
23. Resolve one active, evaluated Model Profile by purpose and privacy class without
    returning endpoint credentials to Runtime or a browser.
24. Resolve an unexpired and unrevoked claimant session by token hash without allowing a
    browser-supplied customer identifier to alter the authenticated principal.
25. Read and update the authenticated claimant's approved profile and communication
    preferences by `customer_id` without exposing another Customer record.
26. List external tasks for one authorised Claim in stable `(created_at, task_id)` order and map
    each task to its single request and single-origin evidence links without exposing another
    Claim.
27. Read active Evidence reuse links by target Claim and Evidence identity, and list all links for
    one claimant without crossing customer scope.
28. Atomically apply one claimant Evidence reuse or removal with the target Claim revision,
    idempotency record, Branch Evaluation, and append-only audit event.
29. Append an immutable branch evaluation for a Claim revision and list evaluations in creation
    order without allowing an evaluation to overwrite Claim State.
30. Resolve an unexpired and unrevoked staff session from the independent staff identity store
    without accepting claimant credentials or browser-supplied roles.
31. Create, list, and resume Staff Agent sessions by authenticated `staff_id` without exposing
    another staff member's sessions.
32. Append one Staff Agent question and answer atomically, resolve retries by
    `(staff_id, session_id, client_message_id)`, and preserve the explicit zero-to-five Claim scope
    used for that turn. Persist stable draft identities and route an explicitly confirmed draft
    through the existing revision-checked Workbench action handler; do not grant the model direct
    mutation authority.
33. Create a unique Customer or Staff account through its identity repository without exposing the
    password hash or allowing an administration retry to create a duplicate account.
34. Conditionally update approved Customer or Staff account fields by account revision; a stale
    write returns the current revision without changing the record.
35. List identity sessions for exactly one Customer or Staff account in stable newest-first order
    without returning bearer values or token hashes.
36. Resolve and revoke one active identity session by opaque `ias_` ID and expected revision; a
    session under another account is not exposed and a retry cannot reactivate it.
37. Receive one accepted assessor task's returned report through the installed adapter, store its
    bytes under the task-linked Evidence identity, recover an interrupted unchanged retry, and
    verify the immutable result against the current Claim revision without promoting Claim facts.
38. List authorised Claims by the server-projected completed, abandoned, or closed disposition
    without scanning action history or inferring terminal state from a missing Session.
39. Resolve and atomically reopen one eligible abandoned/closed Claim by staff actor, exact action,
    target, expected revision, and idempotency key while preserving the active-session pointer.
40. Search Sessions within one authorised Claim by registered Session and message filters while
    examining at most 100 Sessions and 200 messages per Session, stopping once the requested result
    limit is satisfied, and returning unavailable when the examined-set bound cannot prove a
    complete result (`SEARCH_SCOPE_EXCEEDED`). Read at most the requested newest 50 messages for
    one explicit Session.
41. Create, read, update, soft-deactivate, and cursor-page assets by authenticated `customer_id`
    using optimistic asset revision and create idempotency, without cross-customer discovery.
    Create, update, and soft-deactivate persist one bounded Asset-scoped audit fact in the same
    authoritative mutation.
42. Atomically select an active owned asset and persist the immutable Claim asset snapshot,
    proposed registered facts, resulting Claim revision, applied Branch Evaluation, and
    idempotency response. Revalidate owner, active state, revision, and copied details inside the
    authoritative write. A changed Asset returns its current revision; an unavailable Asset is
    concealed. A terminal Claim rejects the selection. Any rejected result leaves the Claim,
    snapshot, Branch Evaluation, idempotency, and audit records unchanged. A successful selection
    persists one bounded Claim-scoped audit fact in the same authoritative mutation.
43. List Claim asset snapshots in stable `(captured_at, snapshot_id)` order after claimant
    ownership or Workbench staff authority has been established.
44. Create, revise, list, mask, and retire account Identity Records and Payment Destinations by
    owner while resolving protected values only inside separately authorised adapters.
45. List/select bounded Policy Summaries by account and product family without treating display
    status as a coverage decision or exposing provider credentials.
46. Create/list/revise Participants by Claim and role after Claim authorization, with contact
    masking and contact-consent enforcement before any external use.
47. Append/list immutable same-Claim ContentsItem-to-Evidence associations and reject links when
    either side belongs to another Claim or customer.
48. Create/revise/list emergency-repair mitigation records and their Evidence/WorkItem links in
    the same authoritative Claim mutation when Claim State also changes.

## Asset Record Mapping

- `asset:{asset_id}` stores the current `AssetRecord`; `asset_id` uses `ase_` and is globally
  opaque. Reusable contents details are limited to description, category, brand, and model;
  serial number and value are not stored in the Asset or copied into its Claim snapshot. Logical
  lookup/index: `(record_type, customer_id, active, updated_at, _id)`.
- `claim_asset_snapshot:{snapshot_id}` stores immutable `ClaimAssetSnapshot`; `snapshot_id`
  uses `cas_`. Logical lookup/index: `(record_type, claim_id, captured_at, _id)` with
  `customer_id` retained for ownership enforcement.
- Fixture and MongoDB adapters implement the same port. MongoDB selection uses one transaction;
  Fixture uses one Claim mutation lock. No adapter may reconstruct a historical snapshot from
  the current asset.
- Existing records require no backfill. Assets and snapshots are additive. A future provider
  migration copies IDs, revisions, timestamps, lifecycle state, and snapshots exactly, then
  verifies owner-scoped counts and snapshot hashes before cutover. It must not infer a Policy
  relationship from claimant text; that association requires an owned `pol_` record.
- The proposed Profile migration is not executable while #918 remains open. Existing Profiles
  remain valid under the current contract; a later approved migration must define the
  transitional validity state before it can make `legal_name` required. It must never guess date
  of birth, address, identity, payment, policy, Participant, ContentsItem metadata, or Evidence
  associations.
- Protected values migrate through the approved encryption/tokenisation adapter; raw values,
  provider credentials, and protected references never enter migration logs or verification
  reports. Failed verification leaves the old source authoritative and performs no cutover.

## Development/Test Identity Invariants

- Raw claimant access tokens are returned once and are never persisted; repositories retain
  only a one-way token hash.
- A session binds one opaque `ias_` identity to exactly one server-selected account, revision,
  creation time, expiry time, update time, and optional revocation time.
- Expired or revoked sessions cannot authenticate and logout is immediately effective.
- Synthetic credential verification and session persistence are fixture capabilities only;
  selecting a production environment fails closed until an approved identity provider and
  durable identity adapter exist.
- Profile and communication preferences are Customer records, not browser-local authority.
- Authentication data cannot grant staff roles, change claim ownership, or enter Claim State.
- Staff password hashes and session hashes remain in the staff identity store; they are not Claim,
  claimant session, or Workbench projection fields.
- Customer account active state is persisted in the claimant identity store and staff account
  active state is persisted in the independent staff identity store. Administration reads and
  updates these records through their repository interfaces; no Control Plane route writes Claim
  State or Workbench records.
- Customer and Staff account writes use monotonically increasing revisions. Session revocation
  advances only the targeted session revision and preserves its prior creation and expiry times.
- Existing local SQLite identity databases are upgraded in place with account revisions,
  timestamps, opaque session IDs, and session revisions. The migration preserves account/session
  relationships and assigns each legacy session one stable `ias_` ID before creating its unique
  lookup index.
- Staff logout revokes the server-side session immediately. The local adapter does not by itself
  establish production IdP, MFA, recovery, or per-Claim entitlement readiness.

## Claim Revision and Idempotency

- `WorkingClaim.revision` is the single optimistic-concurrency token for shared material
  claim writes.
- A mutation using a stale expected revision fails without a partial write.
- A successful material mutation advances the revision exactly once.
- An Asset selection revalidates the exact Asset type, display name, and typed details copied into
  its immutable snapshot inside the authoritative write. Fixture and MongoDB reject any mismatch
  with the same typed repository conflict and persist no Claim, snapshot, Branch Evaluation, or
  idempotency change.
- An idempotency record identifies an accepted operation and request fingerprint. An
  identical replay returns the current authorised projection; changed input under the
  same key is a conflict.
- A Workbench mutation idempotency record also retains the Action Registry version, exact
  `action_code`, and exact `target_ref` resolved before execution. These fields preserve the
  runtime authorization decision with the existing atomic Claim mutation; they do not create a
  second action-state record or concurrency token.
- When a Workbench mutation originates from a confirmed Staff Agent draft, the same atomic
  idempotency record additionally retains `staff_agent_session_id`, `staff_agent_message_id`,
  `staff_agent_draft_id`, and `staff_agent_execution_id`. The same mutation writes an immutable
  `StaffAgentExecutionRecord` containing the registered action, target, expected and resulting
  Claim revisions, confirmation state, authoritative result, and stable source references.
  Persistence resolves the source to an existing staff-owned session and assistant message, then
  verifies that the message contains exactly one matching Claim-scoped draft. Replaying with a
  different draft, reusing the key through a non-Agent entry point, or executing the same draft
  under another key is an idempotency conflict rather than a second execution or attribution.
- External-service consent records are claim-scoped and retain service identity, requested
  action, offer reference, registry version, exact permitted fields, claimant-readable disclosure
  manifest, disclosure fingerprint, selected Evidence IDs, grant/decline/withdraw state, actor,
  and timestamps. A
  consent change advances the Working Claim revision; an adapter result cannot invent or
  reactivate consent.
- The claimant consent mutation atomically stores its idempotency result, applied Branch
  Evaluation, `consent.granted` audit fact, and the one Claim State revision advance. The assessor
  request uses a separate operation identity so provider retry does not replay or rewrite the
  consent mutation.
- Assessor routing persists its immutable identity, complete request fingerprint, consent and
  authority references, authorised claim revision, and `prepared` state before provider
  invocation. When the controlled rule creates the authority decision, that decision, prepared
  operation, and `permission.authorised` audit fact are one atomic repository mutation; retries
  never replace the durable decision record. Retryable failure, terminal failure, and accepted
  result are explicit transitions.
- Provider acceptance is durable before the final Claim State compare-and-set. If another claim
  mutation advances the revision first, an unchanged retry reconciles the accepted result into a
  new claim revision without invoking or creating a second external task.
- A controlled assessor result is fetched through the installed adapter only for an accepted,
  assigned `P3-ASSESSOR` task. The task identity, Claim identity, provider acknowledgement, source
  class, source timestamp, and explicit `simulation_only` label are validated before persistence.
- Returned report bytes are stored through the active Evidence storage profile under an immutable,
  claim-scoped final key. The Evidence record retains the storage key, checksum,
  source system, source reference, source timestamp, and simulation-only label; the result retains
  only provider-neutral provenance, summary, linked Evidence identities, and verification fields.
- Result receipt completes the task's immutable `assessment_report` Evidence link and advances the
  Working Claim revision only to bind the Evidence lifecycle. It does not change Claim facts,
  workflow state, coverage, repair authority, or the claimant-visible external-service state. A
  first receipt requires the current Working Claim revision; an identical replay resolves its
  stored operation before applying that precondition again.
- One deterministic result identity exists per task. An unchanged retry reuses the stored bytes,
  Evidence, Claim binding, and checked result; conflicting content, origin, or task provenance is
  rejected. The Evidence provenance retains a hash of the result-receipt idempotency scope, never
  the raw `Idempotency-Key`, so a changed replay is rejected after process restart. A retry after
  storage or Claim binding but before result persistence resumes without a second Claim revision.
- A returned result begins unverified and is checked through the authoritative external-result
  verification rule against its task, immutable Evidence link, Evidence ownership, and the current
  Claim revision. The controlled fixture result becomes `review_required`; no result record can
  directly promote provider content into Claim State.
- If the Claim result is durable but the public route-idempotency response is not, an unchanged
  retry derives the same decision identity, verifies its authorised revision, restores the stored
  routing result, and then completes the missing idempotency response.
- Child records must not introduce a second concurrency counter that permits them to
  overwrite shared Claim State.
- `WorkingClaim.contents_items` is an optional embedded list of source-aware `ContentsItem`
  records. `item_id` is unique within the Claim; the Claim revision remains the only optimistic
  concurrency token. The list is persisted by each provider through the existing Claim record
  serialization boundary. Item-to-Evidence associations are not represented by this slice and
  must use a separate immutable Evidence contract when added.
- A Branch Evaluation is evidence of a deterministic calculation, not a second Claim State. It
  records separate Field Registry and branch-rule versions, rule/source coordinates, the Claim
  revision it evaluated, and the resulting revision.
- An applied evaluation is written atomically with the resulting Claim revision for Agent turns,
  form updates and confirmations, session resume, evidence updates, handoff creation, claimant
  consent changes, and integration results. An evaluation based on another revision cannot be
  attached to the mutation.
- A material recalculation reads the newest applied evaluation at or before the pre-mutation Claim
  revision. When a previously active or candidate conditional branch loses support, the new
  evaluation records the registered suspended or exited transition with the earlier rule and
  source references plus the correction source. The earlier evaluation remains immutable.
- The standalone Branch Evaluation write accepts only non-applied evaluation evidence calculated
  against the stored current Claim revision. It cannot publish an `applied` record; that status is
  valid only inside the atomic Claim-mutation boundary.
- Evaluation identities and payloads are immutable in both fixture and MongoDB repositories. An
  older record remains audit evidence but is ineligible for a current Dynamic Form projection;
  later status reporting must not rewrite the original calculation.

## Session and Resume Invariants

- The Working Claim is authoritative; sessions hold bounded interaction context only.
- A session may have `interaction_intent = non_claim_intent` and no `claim_id` when the
  conversation has no credible claim purpose.
- Once a session has produced material incident facts, a draft claim may be linked to
  it; later unrelated messages remain session-only and must not overwrite claim facts.
- A session summary records the claim revision it represents. That revision may lag but
  must not exceed the current claim revision.
- A verified rolling summary is an immutable record with `summary_id`, `claim_id`, `session_id`,
  `source_message_ids`, `covered_message_range`, `generator_profile_and_version`,
  `claim_revision_at_generation`, `verified_against_claim_revision`, `summary`, and `created_at`.
  An identical idempotent replay is accepted; different content under the same identity is
  rejected. A summary that conflicts with current Claim State is omitted and recorded as a
  `summary_state_mismatch`; it never overwrites Claim facts.
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
- Session question accounting persists `question_budget`, `question_turn_count`,
  `requested_fact_count`, `repeated_question_count`, `post_session_follow_up_required`, and an
  append-only `question_history`. A new session for the same Claim carries these values forward;
  it cannot reset the claimant-effort boundary.
- Each question-history record retains its stable identity, trigger message, registered field
  codes, purpose, repeat marker, and accepted time. Claimant projections expose counters and the
  remaining budget but not the detailed history; the Workbench projection may expose it to
  authorised staff.

## Staff Agent Session Invariants

- A Staff Agent session is owned by one authenticated `staff_id`. It is separate from claimant and
  Claim-bound staff conversation sessions and does not inherit the currently visible Claim tab.
- Every staff question stores the explicitly supplied `claim_ids`; an empty list is a deliberate
  general scope. Scope is never inferred from text, prior turns, navigation state, or open tabs.
- One turn permits at most five unique Claim IDs. A generated draft that references a Claim outside
  that scope rejects the complete turn before either message is saved.
- The staff question and assistant answer are persisted atomically. Their common creation time is
  ordered causally as staff question then assistant answer rather than by random record ID.
- `client_message_id` is unique within the staff-owned session. An identical retry restores the
  original pair; changed content or Claim scope under the same identity is an idempotency conflict.
- Assistant records retain bounded provider model/request references and source references. They
  do not retain credentials, hidden reasoning, unrestricted provider payloads, or data from an
  unselected Claim.
- Advice and drafts are not business-state authority. Sending, assignment, Claim mutation,
  third-party contact, Signal decision, and other effects require a separate Runtime-authorised,
  revision-checked and audited operation.
- A confirmed Staff Agent draft is passed as explicit source metadata to the existing Workbench
  action handler. The handler persists that source metadata together with its normal action,
  revision, idempotency, and audit boundary; an execution response alone is not considered durable
  attribution.
- The immutable execution identity is derived from the draft identity. It can be stored only when
  the referenced assistant message belongs to the same staff-owned session and contains one draft
  whose Claim, registered action, and target match the execution. A missing message, a staff-role
  message, a cross-session reference, or a changed draft contract rejects the complete mutation.
- A successful execution response is built from repository readback of the persisted execution
  record. Claimant routes never expose Staff Agent execution evidence or its internal source links.
- The Staff Claim search boundary derives lifecycle, active queue, and effective assignee from the
  Working Claim plus its current Evidence and handoff records. The MongoDB adapter stores that
  derived state in an adapter-owned `staff_search` projection on the Claim document. It contains
  only `claim_id`, customer/external references, created/incident dates, product family, lifecycle,
  effective assignee, queue, and `updated_at`; it is not part of `WorkingClaim` or any API response.
  Claim, Evidence, and handoff writes refresh the projection in the same transaction or write
  boundary, and repository initialisation backfills pre-contract Claim documents before serving
  searches. MongoDB indexes every registered derived search field and applies all filters plus a
  database-side limit without per-Claim Evidence or handoff reads. Fixture and MongoDB behavior
  remains equivalent. The dispatcher receives only the bounded lightweight candidates and never
  enumerates or constructs full Workbench Claim projections.
- Staff Session search is Claim/customer scoped before any Session or Message read. Repository
  adapters apply exact Session ID, start date, and status predicates at their indexed Session
  boundary, evaluate actor and closed typed text only within a maximum of 100 candidate Sessions
  and 200 messages per Session, and stop as soon as the requested result limit is satisfied. Exceeding
  either examined-set limit fails closed as unavailable with `SEARCH_SCOPE_EXCEEDED`; it cannot be
  reported as no result.
  Session read queries only the requested newest message window. Its Staff Agent projection
  contains allow-listed Session identity/status/timestamps and closed `{type: text, text: ...}`
  content; customer identity, model/session internals, and undeclared nested Message fields remain
  persistence-only.

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
- Uploading a registered requirement, or replacing failed or invalid claimant material, updates
  the original claimant-owned Evidence record. The mutation preserves `evidence_id`, `created_at`,
  `needed_for`, `related_fields`, `claimant_note`, ownership, and visibility; it does not create a
  second record that leaves the requirement outstanding.
- `material_version` identifies the current file generation beneath that stable requirement. A
  replacement advances it by exactly one and appends the prior generation to typed
  `material_history`, including its condition, file state and metadata, references, complete
  provenance, processing and extraction decisions, and any proposed Claim fields sourced only by
  that generation. Fixture and MongoDB persistence reject a shortened or rewritten history.
- A replacement starts the new generation without the prior file's references, checksum,
  processing state, extraction state, fact decisions, or lifecycle transition history.
  Requirement-origin provenance such as `reported_in_message_id` and `captured_at` remains on the
  current stable requirement. A current Claim field is withdrawn only when it is still `proposed`,
  has an image or document source, and all of its source references identify the replaced
  generation. Confirmed, disputed, and multi-source fields remain current.
- An extracted field names both the stable `evidence_id` and
  `evidence:{evidence_id}:material:{material_version}`. Fact decisions require the current
  generation reference so an older material cannot be mistaken for the replacement.
- A `processing` or `failed` file remains pending or attention-required in the
  authoritative Claim aggregation; only a `ready` file can contribute received
  Evidence. Retry reuses the same Evidence identity and revision-checked
  mutation rather than creating a duplicate record.
- Account history actions preserve the original Evidence identity. Reuse stores an
  `EvidenceClaimLink` containing source Claim, target Claim, customer, lifecycle,
  and timestamps; it never duplicates the object or its metadata as a new source
  record. The target Claim projection includes only active links and recomputes
  its evidence summary from the linked source records.
- Removing source Evidence marks its claimant-history state removed while keeping
  the immutable record, material history, provenance, and audit trail. Removing a
  reused item writes a detached link and leaves the source Claim unchanged. Both
  operations advance only the target Claim revision and are persisted atomically
  with idempotency, Branch Evaluation, and audit data.
- Evidence action writes require the authenticated claimant to own both Claims and
   the source Evidence. The compare-and-set revision check occurs in the same
   transaction as the relation or history-state change; retries with the same key
   replay the stored typed result, while a different request under that key is a
   conflict.
- Evidence action authorization is grounded in immutable Runtime records: the persisted
   `AgentProposalRecord` stores the target Evidence and source Claim for the exact action, and
   the claimant confirmation is a later claimant-visible `MessageRecord` in the same active
   session. Public Evidence mutations reject references that exist only in the request body;
   fabricated or cross-session references fail before the Claim, link, history, audit, or
   idempotency mutation begins.
- Pending, invalid, unofficial, and not-yet-generated evidence remain distinct states.
  `EvidenceStatus` carries the business condition of the material and
  `EvidenceFileStatus` the upload and processing lifecycle alone, so the two
  vocabularies cannot drift into describing the same thing differently. A condition
  that is a statement about a second record or a claim fact — conflict, supersession,
  established unavailability — is carried by a typed `EvidenceReference` with its own
  unresolved or resolved state, reason, and timing, never by the status alone.
  References are staff-visible only: a claimant is told a check is in progress, not
  which side is doubted.

Anonymous browser sessions may own a temporary conversation Claim, but Evidence
upload mutations require an authenticated claimant. Selecting a file before
login is not a persistence operation; promotion transfers the existing Claim
and its records only after authentication, and abandoned selections leave no
Evidence record or protected object.

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
- A successful multimodal Runtime trace may retain the exact selected Evidence ID, media type,
  and `submitted` outcome. It never retains raw bytes, object URLs, storage keys, or provider
  payloads. Any proposed form field or contents item derived from that attachment retains the
  Evidence ID as its source reference and remains unconfirmed until the ordinary fact-confirmation
  path accepts it.
- A v7 Runtime trace records only bounded configuration and performance metadata:
  `release_set_id`, Request Profile and provider capability versions, Prompt bundle and fragment
  references, schema and route, context load decisions, request budgets, cache layout,
  `prefix_fingerprint`, `tool_manifest_id`, resolved-reference count, invocation/tool counts,
  output tokens, cache read/write tokens, cache-miss reason, first-token and total latency,
  `summary_state_mismatch`, and SLO outcome. Prompt text, resolved contents, raw provider payloads,
  credentials, and unrestricted customer data are excluded.
- Persisted Runtime and ToolResult `tool_call_id` values are bounded provider-neutral correlation
  identifiers. Provider call IDs, thought signatures, response handles, and other continuation
  material remain inside the turn-scoped provider exchange and are never persisted or encoded into
  that identifier.
- Model-authored customer prose and model-proposed internal signals are not persistence
  authority. Claimant-visible response fields are server-rendered after deterministic
  validation, and any non-empty model signal proposal rejects the complete turn before write.
- A structured form field retains an immutable assertion list plus one
  `current_assertion_id`. Assertions preserve reported wording, normalized value, source
  references, relation, status, temporal precision, optional reason code, and creation time.
  Equivalent repetition and compatible refinement retain history without creating a false
  conflict; explicit correction supersedes the former current assertion; a material conflict
  remains disputed until claimant clarification or authorised staff review.
- `WorkingClaim.contents_items` uses the same history-preserving rule through immutable item
  assertions and stable item IDs. Correcting an item replaces its current projection without
  deleting the previous assertion or creating a duplicate item.
- Agent decisions persist validated context-tool results and any discrepancy candidates used by
  Runtime review. A discrepancy candidate is internal evidence of conflicting sources only; it
  does not set `fraud_signal`, make a fraud conclusion, or enter claimant projections.

## Handoff and Staff-work Invariants

- A handoff retains immutable identity, type, reason, priority, requested action, source
  context, transfer packet, and creation time.
- Policy and claim-history context in the transfer packet references authoritative persisted
  Retrieval records by stable `retrieval_id`; the packet does not duplicate policy wording,
  claim-history facts, or mutable provider output as a second source of truth.
- Transfer-time Review Signal provenance retains only relevant stable signal/source references.
  Derived Staff Tags retain the minimum immutable Registry coordinate needed to reconstruct their
  basis: tag code, Registry version, and source references. Current mutable tag and signal state is
  recomputed from authoritative Claim-linked records.
- The transfer packet does not persist a second mutable current-responsibility or ownership field.
  Current responsibility remains authoritative in live Claim and Workbench state.
- Policy/history absence remains distinguishable from provider or source unavailability. A failed
  or unavailable required retrieval must remain explicit in durable handoff context rather than
  being represented as an unexplained empty reference list.
- Lifecycle changes may update status, owner, and applicable timestamps through a
  revision-checked claim mutation.
- Acceptance records one owner. Active work cannot be reassigned by a blind overwrite.
- Repeated support requests reuse an applicable active handoff rather than creating
  competing ownership.
- Staff write-back records actor, reason, outcome, evidence references, and a separate
  claimant-safe update.
- Every Workbench handoff, signal, WorkItem, message, and ownership mutation first resolves the
  exact current projected action. Its idempotency record stores the registry version, action code,
  and target alongside the resulting response.
- `WorkingClaim.terminal_disposition` is either null or one embedded authoritative record with
  `value`, registered `reason_code`, non-empty immutable `source_refs`, typed `recorded_by`,
  `recorded_at`, and `recorded_revision`. It does not replace `claim_state`. `completed` requires a
  created external Claim result; `abandoned` and `closed` cannot coexist with one.
- Successful external Claim creation writes the created result and `completed` disposition in the
  same one-revision Claim mutation, referencing the authorising decision and external Claim.
- Reopen clears only an eligible `abandoned`/`closed` disposition. The Fixture and MongoDB
  `save_claim_mutation_with_audit` boundary accepts the authenticated operation actor (claimant or
  staff), requires the same Claim and active-session pointer, and atomically stores the resulting
  Claim, actor-scoped idempotency response, and claim-revision-linked audit fact. It does not grant
  authority; the service must resolve `claim.reopen` and primary ownership before calling it.

## Agent Turn and Action Invariants

- `TurnPlan`, `AgentProposal`, `ExecutionPlan`, and `TurnResult` are separate immutable
  records or immutable revisions. They must not share one mutable status field that makes
  a proposal appear executed.
- One turn may contain several conversation moves and command proposals but exactly one
  primary Runtime control directive.
- A message-bound external-service offer is an existing `RuntimeWorkItemRecord(kind="external")`,
  not a second Claim or external-task state machine. Its typed metadata retains the offer ID,
  originating Agent and claimant message IDs, service and requested action, registry version,
  exact disclosure fields and selected Evidence IDs, readable disclosure manifest, and scope
  fingerprint. Message history reconstructs supplementary actions from these immutable WorkItems
  plus the authoritative Claim consent and ExternalTask records.
- A claimant TurnPlan records every external-service lifecycle input selected for that turn as a
  bounded coordinate: registry version, service identity, operation status, optional result stage,
  and optional result-verification outcome. These immutable coordinates describe the model input
  and do not replace the external task, result, or assessor-routing records. When an accepted
  assessor task and `WorkingClaim.assessor_routing` share the same provider reference, the stored
  operation coordinate is the registry-projected `queued` or `assigned` value actually supplied to
  the model; a non-matching routing record leaves the coordinate at `accepted`.
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
- Accepted reconciliation reads the existing `tsk_` task, its single sent `erq_` request, and the
  matching assessor operation before contacting the status-check adapter. A confirmed provider
  acknowledgement atomically advances that task and operation to `accepted`, records the pending
  assessment Evidence and its immutable task link, and advances the Claim revision with the same
  routing result. A stale revision, changed identity, malformed answer, or inconclusive check
  writes none of those records. An unchanged replay reads the settled records and does not repeat
  the status check. `unknown_outcome` cannot become `retryable_failure`; a confirmed non-submission
  requires a separate durable reconciliation record before it can permit another attempt.
- When an authenticated Workbench staff mutation performs that reconciliation, the same Fixture
  lock or MongoDB transaction also checks the staff presence revision, assigns an unowned Claim to
  that staff member, stores one completed task-linked `external_reconciliation` StaffAction, and
  stores the exact action-code/target idempotency response. Failure of any presence, ownership,
  revision, identity, lifecycle, or idempotency guard writes none of the settlement bundle.
- One prepared `erq_` request carries a dispatch reservation. Runtime must hold it before any
  provider call, and the reservation is taken by an atomic compare-and-set on the stored request
  rather than by a check made before the write, so exactly one of two concurrent callers may
  dispatch and the other fails before the provider is reached. It preserves the existing task,
  request, and operation identity; no second task or operation is created to resolve a race, and
  there is no uniqueness rule over `(claim_id, service_identity, requested_action)`. An attempt
  that settles with a known outcome releases the reservation, acceptance and an unusable provider
  answer included, so a settled request never records a dispatch still in progress and a failure
  that definitely never reached the provider may be retried on the same identity. An attempt whose outcome is not
  established keeps it, which is why a reserved request can never fall back to a sendable
  `prepared` state; establishing that outcome is reconciliation's work. The reservation records the
  operation identity the attempt dispatches under, so a request holds that identity once its
  dispatch is reserved rather than only once it is sent, and an attempt interrupted between the two
  still names the operation it must be reconciled against.
- An external response cannot mutate Claim State until provenance, request linkage,
  schema, current revision, field conflicts, and required authority are validated.
- An external task uses an opaque `tsk_` identifier and remains separate from Claim State. Its
  integration source, status, and timestamps are stored with the claim association. A
  task keeps its original claim, service, action, source class, and creation time across status
  updates, and a changed state must advance `updated_at` so a stale concurrent write fails. Before
  Fixture or MongoDB accepts a new or changed task, its service identity must exist in the
  canonical External Service Lifecycle Registry, permit `ExternalTask` persistence, allow the
  persisted status, and agree with the request provenance derived from integration source and
  delivery. Historical unknown records remain readable as legacy/unavailable projections, but
  cannot be created or advanced through the repository write contract. A
  task-to-evidence link is accepted only when the named Evidence record exists under the same
  claim and customer. It is immutable for `(claim_id, evidence_id)` and cannot name a task on
  another claim; repeated material cannot acquire a second external origin.
- An implemented external request uses an opaque `erq_` identifier derived deterministically
  from the reserved assessor operation identity so crash recovery and explicit retry cannot mint
  a second request. The request and task must agree on claim, service, and action. Persistence
  verifies the parent claim/customer, task, named claimant consent, Northwind authority, and
  authorised revision before accepting it. One task has at most one request.
- Request preparation is immutable. Its stakeholder, purpose, disclosed field names,
  authorisation pair, authorised revision, and preparation time cannot be rewritten. The only
  permitted update records the first `sent_at` and the already-reserved operation identity;
  neither field can be cleared or replaced. `sent_at` records that Northwind handed the request
  to the selected service entry. Provider receipt remains the separate task `delivery` state and
  requires named delivery evidence.

## Configuration and Control Plane Invariants

The configuration repository stores immutable revisions behind a provider-neutral boundary.
Developer/test mode may use an in-memory implementation; the normal local/runtime path uses a
SQLite implementation selected by `NORTHWIND_CONTROL_PLANE_DB_PATH`. Configuration IDs
use the `cfg_` prefix and audit event IDs use `aud_`; the physical partition and sort-key mapping
is profile-specific and must preserve these access patterns.

Each configuration revision contains `configuration_id`, `domain`, `configuration_key`, `revision`, `state`,
`impact`, non-secret `values`, protected `secret_references`, `author`, `reason`, optional
`validation_evidence`, `effective_time`, `previous_version`, `rollback_target`, and
`updated_at`. Single-instance domains use `configuration_key=default`; Integration records use
their registered `service_id`. Active publication and rollback access patterns are scoped by
`(domain, configuration_key)`. Records written before this field existed derive the Integration
key from `values.service_id` and otherwise use `default`. Audit events contain `event_id`,
`configuration_id`, `revision`, optional
`previous_revision`, `actor`, `action`, `reason`, `outcome`, top-level `changed_fields`, and
`created_at`. `changed_fields` records field names only and never duplicates configuration or
secret values. Audit events are append-only and are not
deleted or rewritten during withdrawal, supersession, or rollback.

Active configuration lookup inspects only the latest immutable revision of each logical
`configuration_id`. A historical published revision is not active after a later revision withdraws
or supersedes it. The in-memory and SQLite repositories use the same rule, so fixture execution
cannot revive a historical publication that the normal persistence adapter would exclude.

Configuration approval records use `apr_` identifiers and contain
`approval_id`, `configuration_id`, `configuration_revision`, `reviewer`, `decision`, `reason`,
and `created_at`. One immutable decision is allowed for a configuration revision. Approval records
are stored separately from configuration revisions and are read only for the matching revision;
they never contain configuration values, secret values, or Claim State. A rejected decision is
written atomically with the next draft revision and its audit events. The normal local SQLite
repository stores these records in `configuration_approvals` beside the configuration and audit
tables.

Release Set records use `rel_` identifiers and contain `release_set_id`, `environment`,
`runtime_profile`, `revision`, `state`, immutable `configuration_refs` (configuration ID plus
revision), service-keyed immutable `integration_refs` (configuration ID plus revision),
product-keyed immutable `knowledge_refs` (knowledge ID plus revision), `author`,
`reason`, optional validation evidence, effective time, previous release set, rollback target, and
`updated_at`. A Runtime Snapshot is a read projection of one published Release Set, its
referenced published configuration revisions, selected Integration revisions, and selected
published knowledge versions; it
is not an independent mutable source of configuration truth. Release Set validation verifies that
each Integration and knowledge reference exists, matches its service or product key, and is
published. Release Set audit
events use `aud_` identifiers and are append-only. The SQLite implementation persists these
records and idempotency keys in the same Control Plane database path. The repository must support
lookup of the active Release Set by `(environment, runtime_profile)`, immutable revision reads,
optimistic-concurrency writes, idempotent transitions, and atomic supersede/publication or
rollback/publication.

Integration health-check records use `ihc_` identifiers and persist only the registered
integration ID, bounded health/source/implementation result, latency, failure code, and check
timestamp. They may reference an `opr_` operation record that owns the health-check execution
status. They are operational evidence, not Claim State or external-task records.

Control Plane operation records use `opr_` identifiers and are stored in
`control_plane_operations`. Each record contains its operation kind, subject type and ID, typed
state, monotonic revision, bounded progress, status URL, optional bounded result, optional stable
error code, and created/updated timestamps. State updates use the revision as an optimistic
concurrency guard. Operation records remain separate from Claim State and do not carry credentials,
provider payloads, or unrestricted personal data.

A `model_invocation` operation stores only its purpose, nullable provider model identifier,
nullable provider-reported input/output/total token counts, measured latency, outcome, and stable
failure code. It does not store the prompt, claimant or staff message, provider request identifier,
credential, or raw response. Aggregate cost is not persisted as a second source of truth. The Admin
service calculates it from these immutable usage records and the active published `operational`
configuration. That configuration is a normal single-instance configuration record whose closed
values contain currency, unique per-model input/output rates in currency microunits per million
tokens, one rate-limit window, and token, cost, and rate-limit alert thresholds.

Evaluation evidence uses `eval_` identifiers and is stored in `control_plane_evaluations`. Each
immutable record identifies its purpose, model version, optional knowledge/rule/configuration
versions, dataset and fixture versions, source versions, bounded scenario outcomes, metrics,
threshold, and completion/error state. Evaluation records are evidence for publication and
operations; they are not Claim State, do not contain prompts or provider payloads, and are never
updated in place.

Knowledge source metadata uses `knw_` identifiers and is stored in
`control_plane_knowledge_sources`. A row represents one immutable `(document_id, version)`
candidate and stores only governed metadata, lifecycle/revision state, checksum, chunk count,
operation reference, validation evidence, and version links. Source bytes, chunks, and indexes
remain in the configured knowledge object store. The repository enforces unique document/version
identity and optimistic revision writes; publication supersedes the prior published version for
that document while retaining its record. Knowledge records never contain Claim State, claim
history, staff decisions, credentials, or provider payloads.

Agent instruction, tool-permission, controlled-rule, and feature settings are stored as separate
versioned `configuration_records` domains (`agent_instruction`, `agent_tool_policy`, `agent_rule`,
and `feature`). Each component keeps its own immutable revisions and lifecycle/audit history, so a
tool-permission change cannot silently rewrite instructions or feature settings. High-impact
components use the existing independent approval record and publication guard; no component may
write production Claim State.

A published v7 Release Set is valid only when it atomically fixes the complete Prompt fragment
manifest and bodies, route/catalogue/budget rules, every registered Request Profile, every schema
those profiles reference, provider capabilities for the exact model catalogue, all v7 feature
flags, and one cache layout version. An incomplete or incompatible set fails resolution; Runtime
does not repair it by combining another release or falling back to v6.

Model records use `domain=model` and `configuration_key=profile_id`, so one published Release
Set can bind `qwen-local`, `nowcoding-gpt55`, `bedrock-nova2-lite`, and
`google-gemini35-flash-lite` without overwriting any profile.
Claimant profiles must declare `structured_output=true`. Tool and continuation capabilities are
profile-specific and are checked before a route can send work to provider transport. A Session
stores the selected profile ID and Runtime resolves that exact key for every turn.
The deployment binding manifest is not persisted catalogue state. It contains only non-secret
connection metadata and credential environment-variable names used to reject unapproved model
configurations before publication. The active Release Set remains the authority for which matched
profiles are selectable.

An `AgentDecisionRecord` may retain a `runtime_configuration` provenance projection for the exact
turn. It contains the Release Set ID, environment, runtime profile, each selected configuration ID
and revision, and each selected knowledge ID, revision, and external version. It does not copy
configuration values, system instructions, knowledge content, endpoint data, or secret references.
The record is an audit coordinate into immutable Control Plane history rather than a second source
of runtime configuration truth.

Access policies use the same `configuration_records` table with `domain=access`. Their closed
values contain the named role, actor type, scopes, visibility classes, active flag, and optional
protected credential reference. They describe an administration policy; they do not replace the
identity stores, assign roles by browser input, or grant permission until a published policy is
resolved by a server-side authorization boundary.

Admin list and detail responses may add an `allowed_actions` projection containing the registered
action code, availability, expected revision, and a bounded reason. This field is not persisted.
The application service derives it from the latest resource revision, lifecycle state, immutable
approval records, and authenticated principal on every read. A cached or client-supplied action
projection never grants mutation authority and cannot replace the endpoint's state, identity, and
revision checks.

Staff presence is stored as a provider-neutral `staff_presence` record keyed by the authoritative
staff ID. It contains `online`, `available`, server-owned `last_seen_at`, `expires_at`, `revision`,
and `updated_at`. Presence is a short-lived eligibility lease, not account enablement and not
Claim State. Fixture and MongoDB adapters implement the same optimistic-revision read/write
contract. Claim acceptance continues to use the existing atomic Claim/handoff/idempotency
mutation, so presence does not introduce a second assignment or ownership truth. The acceptance
guard advances the accepted staff presence revision in both Fixture and MongoDB adapters; this
provider-neutral lease revision is the transaction conflict point.
Staff logout revokes the server-side auth session even when this best-effort presence cleanup
cannot be persisted; presence failure must never leave the bearer session active.
An acceptance using a stale presence revision is rejected before the Claim assignment is stored.

The development/test validation seed uses the provider-neutral `ValidationSeedGraph` boundary.
It writes three Claim graphs, their active Sessions, Messages, Evidence metadata, the current
staff presence lease, and one Idempotency record as one operation. Fixture persistence snapshots
and restores all affected stores on failure; MongoDB uses the existing transaction boundary.
The seed reuses the logical records above and adds no fields, provider keys, object-storage
references, or alternate Claim schema. A repeated key replays the stored response, while a
different key requires an empty Claim queue.

- Draft configuration is separate from the active published version.
- Runtime reads resolve only the latest active `published` record for a `(domain, configuration_key)` and fail closed
  when no publication exists; drafts and unverified provider records are never runtime fallback.
  Knowledge reads resolve the exact product-keyed version selected by the active Release Set and
  never fall back to a different published version while that Release Set is active.
- Publication records author, reason, validation evidence, approver when required,
  effective time, previous version, and rollback target.
- Published versions are immutable. Rollback publishes or reactivates an approved prior
  version and preserves the intervening audit history.
- Secret values are stored in an approved secret manager. Configuration stores only a
  secret reference and safe metadata.
- Selecting a data runtime profile is a deployment-level configuration change. A process
  uses one complete profile and cannot mix provider stores silently.
- A `data_profile` configuration revision stores only the closed provider-neutral fields
  `data_runtime_profile` and `object_storage_adapter`. The compatibility matrix permits
  `fixture` with either adapter and requires `s3_compatible` for `local_mvp`, `cloudflare`,
  `mongodb`, and `aws`; unverified cloudflare, mongodb, and aws profiles remain draft-only
  until their complete provider bundles are verified.
- An `integration` configuration revision stores provider-neutral metadata only: registered
  `service_id`, capability, source class, enabled flag, and bounded health-check timeout. The
  service ID must match the runtime registry; provider payloads and secret values remain outside
  the record. Each service uses its `service_id` as the publication key, so publishing one
  Integration does not supersede another service.
- Integration health-check records use `ihc_` identifiers and persist only the registered
  integration ID, bounded health/source/implementation result, latency, failure code, and check
  timestamp. They are operational evidence, not Claim State or external-task records.
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

## P17.1 Incomplete Claim Checkpoint

The explicit incomplete-Claim checkpoint is a provider-neutral atomic mutation. It does not add a
second Claim State.

For Claim revision `N`, the checkpoint persists together:

- the same authoritative `WorkingClaim` at revision `N + 1`, with `active_session_id` cleared;
- the previously active Session changed to `paused`, with its recovery snapshot aligned to revision
  `N`;
- bounded Session recovery context containing `interrupted_at`,
  `last_meaningful_activity_at`, an exact
  `last_meaningful_activity_source_ref`, and a plain-language
  `resume_point`;
- exactly one open Claim-scoped Follow-up for purpose `resume_incomplete_claim`; and
- the idempotency record for the claimant, route, key, accepted revision, Claim, Session, and
  Follow-up identity.

Follow-up IDs use the `fup_` prefix. The minimum P17.1 record persists stable identity, Claim,
source Session, purpose, source references, responsible party, channel, due time, status, attempt
count, contact-permission condition, optional outcome, and timestamps. `pending` means P17.1 has
an authorised current channel; `blocked` means contact is not authorised and therefore has no
channel or schedule; `resolved` records that the claimant resumed. An authenticated in-app
recovery record does not grant email, SMS, or phone authority. An anonymous browser interruption
is persisted as `blocked` / `not_authorised` rather than as executable outbound work.

The Fixture and MongoDB adapters enforce at most one open (`pending` or `blocked`) Follow-up for
the same Claim and purpose. A stale revision, mismatched Claim/Session/customer, conflicting
idempotency identity, invalid contact-authority condition, or second open Claim+purpose record
fails before any bundle member becomes authoritative. The Fixture profile serializes material
Claim mutations and repeats the authoritative revision and duplicate checks while that mutation
lock is held. Two callers that both pass an optimistic read therefore cannot commit two recovery
bundles. When a new claimant Session replaces an existing active Session, the stored active-session
pointer is revision-checked and the prior Session closure is committed in the same activation
mutation; a stale activation therefore cannot overwrite a pause checkpoint or its recovery context.

`last_meaningful_activity_at` is selected from durable claimant-authored messages or accepted
claimant business actions such as authoritative structured-form or contents updates and explicit
consent. Reads, polling, streaming, and an arbitrary Session activity timestamp do not qualify.
The paired `last_meaningful_activity_source_ref` identifies the exact durable source selected for
the recovery checkpoint. Explicit form and contents confirmations append a revision-scoped
confirmation source reference in the same Claim mutation that records their confirmation timestamp,
so recovery chronology never pairs a later confirmation time with an earlier proposal source.

A Claim is eligible for a recovery checkpoint only when its authoritative workflow is not
`created` and `customer_next_step.can_resume=true`. Claimant and Workbench incomplete projections
use that same rule together with the absence of an authoritative active Session and the presence
of a relevant paused recovery checkpoint and open recovery Follow-up.

Resume continues to create a new active interaction Session for the same Working Claim. The same
atomic session-activation mutation marks the open recovery Follow-up `resolved`, so Workbench no
longer exposes stale follow-up work after claimant recovery. The paused Session and recovery
context remain historical continuity evidence and never supersede the latest Working Claim.

P17.1 does not implement notification delivery, retry cadence, attempt processing, abandonment,
escalation, purge, anonymisation, or retention transitions; those remain owned by later P17
slices.

## P17.2 Bounded Terminal Disposition and Reopen Slice

This bounded slice adds the authoritative terminal fact required by Workbench without implementing
the remaining follow-up policy, notification, automatic abandonment/expiry, retention, purge, or
anonymisation work.

`WorkingClaim.terminal_disposition` is optional and embedded in the Claim record so the existing
Claim revision remains its only concurrency token. Its values are `completed`, `abandoned`, and
`closed`. The registered reasons are `CLAIM_CREATED`, `ABANDONMENT_POLICY_APPLIED`, and
`AUTHORISED_CLOSURE`; the latter two reserve the source-linked persistence vocabulary but do not
authorise or implement a policy writer. Every record has at least one immutable source reference,
a typed actor, a timezone-aware recording time, and the Claim revision at which it was recorded.

Successful Claim creation writes `completed` in the same Claim compare-and-set as the external
Claim result. Workbench reads the persisted record directly and never derives terminal placement
from workflow text, session absence, or action history. `purged_or_anonymised` is not represented
by this field and remains outside listable Workbench data.

MongoDB deployments upgraded from a version before this contract use
`scripts/backfill_terminal_dispositions.py` to repair only legacy created Claims whose persisted
external result, source revision, stable external reference, and unique authorised creation
decision prove the missing disposition. The command is read-only unless `--apply` is supplied,
uses a revision-checked conditional update, and refuses incomplete or contradictory provenance.
This schema repair preserves the Claim revision and update time because it records the terminal
fact at the original creation revision rather than introducing a new Claim mutation.

The `claim.reopen` mutation is staff-scoped and stores, in one Fixture lock or MongoDB transaction:

- the same Claim at revision `N + 1` with only `terminal_disposition` cleared;
- the unchanged authoritative `claim_state` and `active_session_id`;
- an idempotency record keyed by authenticated staff actor, route, key, request-plus-revision
  fingerprint, exact action registry version/code/target, and first response; and
- an internal append-only `action.completed` audit event with the staff authentication source,
  prior terminal sources, permission result, submitted reason, idempotency key, and resulting Claim
  revision.

Only a primary owner with an exact non-blocked action may call this boundary. `completed`, a created
external Claim, or an underlying `created` workflow cannot be reopened. Failed authorization,
validation, revision, idempotency, or ownership checks write none of the bundle.
