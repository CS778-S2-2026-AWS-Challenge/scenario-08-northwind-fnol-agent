## Purpose

This document defines the pre-account migration design for the implemented MongoDB
operational store. It is the authoritative design input for the local rehearsal in
`#992`. It is not evidence that a DynamoDB adapter, AWS account, table, or deployment
exists.

The mapping is derived from the current domain records, `PersistenceRepository`
protocol, and `MongoDBRepository` implementation at `origin/main`
`e4a3f498d054154462d43f390ec72ed8267b5c16`. It preserves provider-neutral record
identity, ownership, ordering, uniqueness, revision, idempotency, audit, and atomic
write boundaries. It does not define a new API field, state, permission, lifecycle,
or business rule.

## Migration boundary

The source for #991 and #992 is the `northwind_records` MongoDB collection used by
the local MVP profile. The target design is one DynamoDB operational table. S3
Evidence objects and policy-knowledge objects are handled by their own storage
preparation work; this document carries only their protected references and metadata.

The following adjacent stores are explicitly excluded:

| Source | Status | Treatment |
| --- | --- | --- |
| SQLite claimant identity and claimant auth sessions | Implemented, separate authority | No DynamoDB target is assigned by #991. |
| SQLite staff identity and staff auth sessions | Implemented, separate authority | No DynamoDB target is assigned by #991. |
| SQLite Control Plane configuration, release, operation, integration, and knowledge administration | Implemented, separate authority | No DynamoDB target is assigned by #991. |
| MinIO Evidence bytes and knowledge objects | Implemented local object-store boundary | Metadata references remain in scope; object transfer is not. |
| Customer memory, Mitigation, and Retention records | Contract-only concepts without implemented MongoDB records | Excluded from #991 and #992. |

`PolicyNumberRecord` is not part of the policy/history retrieval source. It is an
implemented, account-owned MongoDB `policy` record and is in scope. Policy/history
retrieval records remain separate `retrieval` records, and governed RAG knowledge
remains outside the operational table.

The excluded record inventory is explicit so a rehearsal cannot infer a target from
documentation alone:

| Excluded record or family | Actual source/status | Exclusion reason |
| --- | --- | --- |
| `CustomerAccountRecord` | SQLite claimant identity store | Account authority is outside the MongoDB operational boundary. |
| `ClaimantAuthSessionRecord` | SQLite claimant identity store | Bearer/authentication state and token material require a separate security placement decision. |
| `StaffAccountRecord` | SQLite staff identity store | Staff identity and role authority are outside the MongoDB operational boundary. |
| `StaffAuthSessionRecord` | SQLite staff identity store | Staff bearer/authentication state is not migration input. |
| Control Plane configuration, approval, release, Runtime Snapshot, integration, operation, evaluation, and knowledge-administration records | SQLite Control Plane stores | Configuration authority and secret references retain their separate repository boundary. |
| Customer memory | No implemented source model or repository method | Contract-only wording cannot create migration data. |
| Mitigation | No implemented source model or repository method | Contract-only wording cannot create migration data. |
| Retention record | No implemented source model or repository method | Contract-only wording cannot create migration data. |
| Governed policy-knowledge documents and chunks | MinIO/object-store knowledge source | Bedrock Knowledge Bases preparation owns document/chunk migration; these are not `policy` account records. |

## Implemented source inventory

Every MongoDB `record_type` currently emitted by `MongoDBRepository` appears below.
The identity is the domain identity that must remain authoritative, not the current
MongoDB `_id` string. `C` means a canonical entity item. `R` means a base-table access
reference written in the same transaction as its canonical item where the runtime
contract requires atomic visibility.

| MongoDB record | Authoritative identity | Ownership and current reads | DynamoDB canonical item and access references | Lifecycle and atomicity |
| --- | --- | --- | --- | --- |
| `claim` | `claim_id` | Claim owner; get by ID; list globally or by customer in `updated_at` descending order; Workbench search | `C(Claim)`, Claim `OWNER`, customer/global/search `R` items | Revision compare-and-set authority for Claim State and workflow. Split large collections as defined below. |
| `session` | `session_id` | Required Claim and customer scope; get active/by ID; list by Claim `started_at`; staff search by ID/date/status | `C(Session)`; Claim/session and date/status `R` items | Current contract has no non-Claim Session. Session changes participate in Claim mutation transactions. |
| `message` | `message_id` | Required Claim/session scope; list `(created_at, message_id)`; lookup by `client_message_id` within Claim | `C(Message)`; session-order `R`; deterministic client-ID lookup item | Stable ID and client-ID reuse must conflict unless the complete stored record is identical. |
| `conversation_summary` | `summary_id` | Required Claim/session scope; latest by creation order | `C(ConversationSummary)`; session summary-order `R` | Immutable verified summary; never overwrites another summary identity. |
| `follow_up` | `follow_up_id` | Claim scope; list by creation; lookup open purpose/source Session | `C(FollowUp)`; Claim-order `R`; open-purpose and source-session lookup items | At most one open `(claim_id, purpose)` and one `(claim_id, source_session_id)`; lifecycle updates replace the same identity. |
| `agent_decision` | `decision_id` | Required Claim/session/trigger-message scope; get by ID or trigger; list by Claim | `C(AgentDecision)`; Claim-order and trigger lookup `R` | Immutable execution evidence inside Agent-turn atomic writes. |
| `branch_evaluation` | `evaluation_id` | Claim scope; list by `created_at` | `C(BranchEvaluation)`; Claim-order `R` | Immutable; evaluated/resulting revisions must retain current validation. |
| `runtime_trace` | `trace_id` | Required Claim/session/trigger scope; get by ID or trigger | `C(RuntimeTrace)`; Claim/session and trigger lookup `R` | Compatibility record remains separate and immutable. |
| `turn_plan` | `turn_id` | Required Claim/session/trigger scope; first Runtime record for turn reconstruction | `C(TurnPlan)`; trigger and turn-bundle `R` | Immutable; Claim scope is required in the implemented claimant Runtime path. |
| `agent_proposal` | `proposal_id` | Required Claim/session/turn scope | `C(AgentProposal)`; turn-bundle `R` | Immutable constituent of one Runtime turn. |
| `execution_plan` | `execution_plan_id` | Required Claim/session/turn scope | `C(ExecutionPlan)`; turn-bundle `R` | Immutable constituent of one Runtime turn. |
| `action_envelope` | `envelope_id` | Required Claim/session/turn scope; list for turn | `C(ActionEnvelope)`; turn-order `R` | Immutable; each envelope remains an individual record. |
| `tool_result` | `result_id` | Required Claim/session/turn scope; list for turn | `C(ToolResult)`; turn-order `R` | Immutable; raw provider payloads and credentials remain excluded. |
| `turn_result` | `result_id` | Required Claim/session/turn scope | `C(TurnResult)`; turn-bundle `R` | Immutable terminal constituent of one Runtime turn. |
| `runtime_work_item` | `work_item_id` | Required Claim and turn scope; Session scope exists only where the current containing Runtime variant supplies and validates it; list by Claim in `updated_at` order and by turn | `C(RuntimeWorkItem)`; Claim and turn-order `R` | Individual mutable Runtime work record; never collapsed into the turn item or assigned a universal Session requirement. |
| `asset` | `asset_id` | Customer-owned; list by active state and `updated_at` | `C(Asset)`; customer active/all `R` | Revisioned account data; remains outside Claim-owner promotion. |
| `claim_asset_snapshot` | `snapshot_id` | Required Claim/customer scope; list `(captured_at, snapshot_id)` | `C(ClaimAssetSnapshot)`; Claim-order `R` | Immutable snapshot tied to source Asset and Claim revisions. |
| `motor_other_driver` | `participant_id` | Required Claim/customer scope; one current record per Claim | `C(MotorOtherDriver)`; Claim singleton lookup item | Stable participant identity plus uniqueness on `claim_id`. |
| `contents_item_evidence_association` | `association_id` | Required Claim/customer/item scope; page by `(created_at, association_id)` | `C(ContentsEvidenceAssociation)`; Claim/item page `R`; tuple uniqueness item | Immutable; `(claim_id, item_id, evidence_id)` is also unique. |
| `evidence` | `evidence_id` | Required Claim owner; get/list by Claim and claimant-source customer history | `C(Evidence)` plus material-version child items; Claim/customer `R` | Stable identity; current material changes while prior material history remains append-only. |
| `evidence_claim_link` | Stable domain identity `link_id`; enforced lookup/uniqueness tuple `(target_claim_id, evidence_id)` | Customer-owned cross-Claim link; direct lookup by target Claim/Evidence tuple and listing by target Claim | `C(EvidenceClaimLink)` keyed by `link_id`; deterministic target/Evidence uniqueness and lookup item; source/target Claim `R` | The tuple item conditionally names exactly one `link_id`. Reusing either the stable ID with different content or the tuple for another stable ID conflicts. Link lifecycle updates the same `link_id`; source Evidence and both Claims must remain customer-authorized. |
| `external_task` | `task_id` | Required Claim/customer scope; get/list by Claim | `C(ExternalTask)`; Claim-order `R` | Stable identity; immutable identity fields and governed lifecycle transitions. |
| `external_task_request` | `request_id`; current MongoDB storage also enforces one canonical request per `task_id` | Required Claim/task/customer scope; get/list by Claim and task | `C(ExternalTaskRequest)`; Claim/task `R`; task uniqueness item | Preparation/reservation/send state updates the same request. Preserve current task-level uniqueness. |
| `external_task_result` | `result_id` | Required Claim/task/customer scope; list by `received_at` | `C(ExternalTaskResult)`; Claim-order `R`; task uniqueness item | Immutable first canonical result; `(claim_id, task_id)` remains unique. |
| `external_task_evidence_link` | `(claim_id, evidence_id)`; `task_id` is relationship data, not identity | Required Claim/task/Evidence scope; list by Claim in `linked_at` order | Deterministic `(claim_id, evidence_id)` `C(ExternalTaskEvidenceLink)`; Claim/task `R` | Immutable provenance link with no invented link ID. The tuple permits only one external-task origin for an Evidence item in a Claim; a different `task_id` at the same tuple conflicts. |
| `assessor_routing_operation` | `operation_id` | Required Claim scope; get by operation and reconcile against external task | `C(AssessorRoutingOperation)`; Claim-order `R` | Immutable identity fields; governed operation status updates same identity. |
| `handoff` | `handoff_id` | Required Claim/customer scope; get/list by `created_at`; contributes queue projection | `C(Handoff)`; Claim-order and queue `R` | Updates same identity; creation/change can be part of Claim/idempotency/audit transactions. |
| `retrieval` | `retrieval_id` | Required Claim/customer scope; list by source retrieval time | `C(Retrieval)`; Claim-order `R` | Policy and Claim-history variants retain their existing source/citation fields. |
| `review_signal` | `signal_id` | Required Claim/customer scope; list by `created_at` | `C(ReviewSignal)`; Claim-order `R` | Stored atomically with its Retrieval bundle; immutable identity. |
| `signal_decision` | `signal_decision_id` | Claim/staff scope; list by `created_at` | `C(SignalDecision)`; Claim-order `R` | Immutable staff decision evidence inside a Claim mutation. |
| `staff_action` | `action_id` | Claim/staff scope; get/list by `created_at` | `C(StaffAction)`; Claim-order and assignee `R` | Lifecycle updates same identity inside revision/idempotency/audit boundaries. |
| `customer_update` | `update_id` | Claim scope; list by `created_at` | `C(CustomerUpdate)`; Claim-order `R` | Immutable claimant-safe update written with its staff mutation. |
| `collaboration_request` | `request_id` | Claim/staff scope; list by `created_at` | `C(CollaborationRequest)`; Claim-order and target staff `R` | Status updates same identity inside ownership mutation. |
| `claim_coworker` | `coworker_id` | Claim/staff scope; list active by `granted_at` | `C(ClaimCoworker)`; Claim active/all `R` | Grant/revoke updates same identity; active projection changes atomically. |
| `staff_presence` | `staff_id` | Staff scope; get/list by staff ID | `C(StaffPresence)`; staff listing `R` | Revision compare-and-set lease record; expiry does not become Claim state. |
| `staff_agent_session` | `session_id` | Staff-owned; list by `staff_id` in `updated_at` descending order | `C(StaffAgentSession)`; staff session-order `R` | Stable identity; account/auth authority remains in SQLite. |
| `staff_agent_message` | `message_id` | Staff/session scope; list by `created_at`; lookup by `(staff_id, session_id, client_message_id)` | `C(StaffAgentMessage)`; session-order `R`; deterministic client-ID lookup item | Stable ID and client-ID reuse conflict unless exact stored content matches. |
| `staff_agent_execution` | `execution_id` | Staff/session/message/draft and Claim scope; get by execution ID | `C(StaffAgentExecution)`; Claim and staff-session `R` | Immutable confirmation/execution evidence written with the authorized Claim mutation. |
| `audit_event` | `event_id` | Exact subject plus time; admin filters by event type, subject type, actor, and time | `C(AuditEvent)`; subject/global/event/subject-type/actor time-order `R` | Append-only. Stable ID reuse with different content is a conflict. |
| `realtime_sequence` | singleton `global` | Internal global sequence allocator | `pk=SYSTEM#REALTIME`, `sk=COUNTER` | Conditional counter update; not an API record. |
| `realtime_event` | `event_id`; unique global `sequence` | Global replay after cursor, high watermark, and live watch | `pk=SYSTEM#REALTIME`, `sk=EVENT#{sequence20}#{event_id}` | Append-only and allocated atomically with the domain mutation and counter. |
| `idempotency` | exact triplet `(actor_id, route, key)` | Resolve one request fingerprint and typed stored result; enumerate Claim/actor records only for atomic ownership promotion | Deterministic hashed `C(Idempotency)` plus Claim/actor `R`; governed promotion aliases are target-only adapter metadata | Conditional create on authoritative key; no GSI uniqueness. Original actor, route, key, fingerprint, result, and provenance remain immutable through promotion. |
| `policy` | `policy_id` | Customer-owned account record; active/all list by `(created_at, policy_id)` | `C(PolicyNumber)`; customer active/all `R` | Revisioned account data. Distinct from RAG policy/history retrieval. |
| `identity_document` | `identity_id` | Customer-owned protected account record; active/all list by creation order | `C(IdentityDocument)`; customer active/all `R` | Preserve ciphertext and mask only; revision compare-and-set. |
| `payment_destination` | `payment_destination_id` | Customer-owned protected account record; active/all list by creation order | `C(PaymentDestination)`; customer active/all `R` | Preserve ciphertext and mask only; revision compare-and-set. |

The inventory contains 45 implemented MongoDB record types. #992 must fail if the
source collection contains an unknown `record_type`, if an inventory row cannot resolve
its authoritative identity, or if a row is silently dropped.

## Current access and write contract

The target adapter must support these repository operations without a table `Scan` on a
request path. Authorization is evaluated before existence and is separate from physical
query capability.

| Query family | Current ordering or identity | Target query plan and consistency |
| --- | --- | --- |
| Entity get | Stable domain ID | Strongly consistent `GetItem` on `C` item; Claim-scoped reads first strongly read Claim `OWNER`. |
| Customer Claims | `updated_at` descending, then stable ID | Strongly consistent `Query` on `ACCESS#CUSTOMER_CLAIMS#{customer}`. Never change to `created_at`. |
| Internal Claim list | `updated_at` descending, then stable ID | Strongly consistent `Query` on `ACCESS#CLAIMS#ALL`. |
| Workbench Claim search | Claim/external/customer reference, created date, incident date, product family, lifecycle state, assignee, queue; `updated_at` descending | Exact base-table partition for global and every listed field/value. For multiple filters, query the most selective exact partition, apply the remaining exact filters, and stop at the requested limit, partition exhaustion, 500 examined projections, or 10 DynamoDB pages, whichever occurs first. |
| Claim Sessions | `started_at`, with exact ID/date/status staff filters | Claim session-order partition plus exact date and status partitions. Actor and `message_contains` retain the current bounded fan-out over candidate Sessions and their bounded Message sets; exceeding the current examination limits fails rather than scanning. |
| Session Messages | `(created_at, message_id)`; recent reads reverse then restore ascending order | Strongly consistent `Query` on one session-order partition with cursor/limit. |
| Message client identity | `(claim_id, client_message_id)` | Strongly consistent deterministic lookup item; conditional creation enforces uniqueness. |
| Staff Agent Sessions | `staff_id`, `updated_at` descending | Strongly consistent `Query` on a staff session-order partition. |
| Staff Agent Messages | `(staff_id, session_id)`, `created_at` | Strongly consistent `Query` on a staff Agent session partition. |
| Staff Agent client identity | `(staff_id, session_id, client_message_id)` | Strongly consistent deterministic lookup item; conditional creation enforces uniqueness. |
| Claim child lists | Existing record-specific time/ID order | Strongly consistent `Query` on a type-specific Claim access partition; canonical records are fetched with strongly consistent `BatchGetItem`. |
| Account data | Customer plus record type and active/all state | Strongly consistent `Query` on customer/type partitions preserving the current timestamp and ID tie-break. |
| Exact-subject audit | `(subject_type, subject_id, claim_id)` and `(created_at, event_id)` | Strongly consistent `Query` on exact subject partition with time range in the sort key. |
| Admin audit | Optional event type, subject type, actor, time; ascending time | Query global or the most selective exact filter partition, filter remaining exact values, and stop at the requested limit, partition exhaustion, 500 examined projections, or 10 DynamoDB pages, whichever occurs first. No table scan. |
| Realtime | One global cursor and total order | Strongly consistent `Query` on `SYSTEM#REALTIME`, strictly after the zero-padded sequence. |
| Idempotency | Exact actor/route/key triplet | Strongly consistent `GetItem` on its deterministic authoritative key. |

Unsupported query behavior is explicit: free-text Claim search, substring Claim search,
arbitrary date ranges beyond the registered date keys, and sorting by an unregistered
field are not introduced by this target. New combinations require a repository-contract
change before adding a projection. Filter expressions must not be used as a substitute
for an unbounded access path.

The 500-item and 10-page ceilings are initial AWS adapter design bounds, not new public
pagination promises. Reaching either ceiling before the requested result is complete fails
closed as an unavailable/bounded-search outcome; it never returns a partial result as if it
were complete. The Backend owner must reconcile that outcome with an existing public error
and register the same constants in repository conformance tests before the AWS profile can
be enabled. Changing either bound requires measured #786 evidence and contract review.

## Key and item design

### Canonical encoding

Domain identifiers are encoded as their exact UTF-8 bytes without case folding or Unicode
normalization. A compound identity uses a sequence of `byte_length:value` components, so
embedded separators cannot create the same byte stream. When a physical key would include
caller-controlled or compound text, the table key uses the lower-case SHA-256 digest of
that canonical byte stream and stores every original component beside it.

Examples:

```text
PK=ENTITY#claim#clm_...
SK=META

PK=ENTITY#message#msg_...
SK=META

PK=IDEMPOTENCY#<sha256(length-prefixed actor_id, route, key)>
SK=META
```

A read of a hashed item compares the stored original components with the requested
components. A digest match with different components is a collision and fails closed.
Canonical insertion uses `attribute_not_exists(PK)` and `attribute_not_exists(SK)` where
the record is append-only. Reusing a stable ID with different scope or content is a
conflict for Messages, Audit events, Runtime evidence, and other immutable children.

`C(Type)` in the inventory expands to
`PK=ENTITY#{record_type}#{encoded-authoritative-identity}, SK=META`. A compound
identity uses its digest in the final component. Claim fragments and Evidence material
versions remain under their canonical entity PK with their documented non-`META` sort
keys; they are physical serialization details, not new domain records.

### Access projections

Access projections are ordinary items in the same table, not GSIs. This permits strongly
consistent `Query` and makes projection visibility part of the same `TransactWriteItems`
boundary as the canonical record. A projection contains only the canonical locator,
authorized filter fields, ordering fields, and non-sensitive summary data needed by the
repository method.

```text
PK=ACCESS#CUSTOMER_CLAIMS#<customer_id>
SK=UPDATED#<reverse-time>#<claim_id>

PK=ACCESS#CLAIM_SEARCH#<field>#<sha256(encoded-value)>
SK=UPDATED#<reverse-time>#<claim_id>

PK=ACCESS#SESSION_MESSAGES#<session_id>
SK=CREATED#<timestamp>#<message_id>

PK=ACCESS#AUDIT_SUBJECT#<subject-hash>
SK=TIME#<timestamp>#<event_id>
```

When an ordering value changes, the transaction deletes the old projection and writes the
new projection. No GSI is used to enforce identity or uniqueness. Secondary indexes are
therefore not required for the first adapter; adding one later requires a measured access
pattern and cannot weaken conditional uniqueness.

The access-reference labels in the inventory expand as follows:

| Reference label | Exact base-table key pattern |
| --- | --- |
| Claim-order | `PK=ACCESS#CLAIM#{claim_id}#{record_type}`, `SK={order_name}#{timestamp_or_state}#{entity_id}` |
| Session-order | `PK=ACCESS#SESSION#{session_id}#{record_type}`, `SK=CREATED#{created_at}#{entity_id}` |
| Turn-order | `PK=ACCESS#TURN#{turn_id}#{record_type}`, `SK=CREATED#{created_at}#{entity_id}` |
| Customer account active/all | `PK=ACCESS#CUSTOMER#{customer_id}#{record_type}#{active_or_all}`, `SK={configured_time}#{entity_id}` |
| Staff Agent session-order | `PK=ACCESS#STAFF_AGENT#{staff_id}#SESSIONS`, `SK=UPDATED#{reverse_time}#{session_id}` |
| Staff Agent message-order | `PK=ACCESS#STAFF_AGENT_SESSION#{session_id}#MESSAGES`, `SK=CREATED#{created_at}#{message_id}` |
| Deterministic client lookup | `PK=LOOKUP#{lookup_type}#{sha256(encoded-scope-and-client-id)}`, `SK=META` |
| Deterministic tuple uniqueness | `PK=UNIQUE#{constraint_name}#{sha256(encoded-components)}`, `SK=META` |
| Claim search | `PK=ACCESS#CLAIM_SEARCH#{field}#{sha256(encoded-value)}`, `SK=UPDATED#{reverse_time}#{claim_id}` |
| Audit time-order | `PK=ACCESS#AUDIT#{filter_name}#{sha256(encoded-filter-value)}`, `SK=TIME#{created_at}#{event_id}` |

Every reference stores the canonical PK/SK and its unhashed scope components. The adapter
verifies those components before dereferencing. The initial table has zero GSIs: all listed
request paths use base-table `GetItem`, `BatchGetItem`, or `Query` so they can request strong
consistency. This is the explicit GSI assumption for #991, not an omitted index decision.
Timestamps use UTC RFC 3339 with fixed microsecond precision for ascending keys. A descending
key uses a zero-padded 20-digit value equal to `99999999999999999999` minus Unix epoch
microseconds, followed by the stable entity ID as the tie-break.

### Claim ownership indirection

Every Claim has an ownership authority item:

```text
PK=ENTITY#claim#<claim_id>
SK=OWNER
owner_customer_id=<current customer_id>
```

Claim-scoped canonical children store immutable `owner_ref=claim:<claim_id>` as their
physical authorization link. Their serialized payload omits the duplicated mutable
`customer_id`; the adapter strongly reads the Claim owner and rehydrates the required
provider-neutral `customer_id` field. Account-owned Policy, Asset, identity, and payment
records remain directly customer-owned and do not use Claim owner indirection.

Anonymous-to-authenticated promotion is one transaction that:

1. conditions `OWNER.owner_customer_id` on the anonymous ID;
2. updates Claim `META` and `OWNER` to the authenticated customer;
3. deletes the old customer-Claim access projection;
4. writes the new customer-Claim access projection;
5. writes one destination lookup alias for every immutable idempotency record selected by
   the strongly consistent Claim/anonymous-actor projection;
6. writes one Claim-scoped anonymous-actor retirement item;
7. conditionally advances the global realtime counter; and
8. appends the globally ordered realtime event.

An idempotency alias occupies the deterministic requested key for the authenticated
`(actor_id, route, key)` and points to the unchanged canonical record under the original
anonymous triplet. It carries the Claim ID, original triplet, and original fingerprint for
verification, but does not copy or redefine the response. Alias insertion requires the
destination key to be absent; an existing canonical record or alias to another source is a
collision and aborts the whole promotion. Exact retry of an already completed promotion may
reuse only an alias to the same original canonical item and an identical retirement item.

No original idempotency item is deleted or re-keyed. An authenticated lookup first resolves
its deterministic item and follows an alias with strongly consistent reads, then verifies
the original actor, route, key, Claim, and fingerprint. An anonymous lookup that finds a
canonical record must also strongly read the retirement item for that record's Claim; after
promotion it fails closed instead of replaying through stale anonymous authority. The
retirement is Claim-scoped so promoting one Claim does not revoke unrelated Claims from the
same browser session.

Each Claim/actor idempotency write also conditionally advances one adapter-owned
Claim/actor generation item and requires that item not be retired. Promotion strongly reads
that generation before enumerating its `R` items, then changes the same item to retired with
a generation-equality condition in the promotion transaction. A concurrent or newly added
anonymous operation therefore conflicts with promotion instead of escaping alias creation.

The promotion preflight counts `m` selected idempotency records and verifies that every
record names the promoted Claim. The transaction has `m + 7` actions: the six existing
Claim/projection/realtime actions, `m` alias puts, and one retirement put. It performs no
idempotency deletes. If the action count exceeds 100, the serialized transaction exceeds
4 MB, a destination collides, or the source projection changes before commit, no promotion
write occurs. The current `promote_claim_owner` and `find_idempotency` protocol methods do
not expose alias/retirement semantics; the Backend owner must add and conformance-test that
repository contract before a DynamoDB profile is enabled. Until then this capability is
`unavailable`, rather than silently losing replay or weakening the exact triplet authority.

Child records are not rewritten. Every authorized child read resolves the owner first, so
there is no partial state in which old and new customers each authorize different children.
Migration rejects a source Claim when any Claim-scoped child carrying `customer_id` does
not match the current Claim owner. A staged ownership transition is not supported.

## Global realtime design

The implemented contract is one globally ordered stream. Claim- or customer-partitioned
events cannot implement its cursor, high watermark, or watch methods.

For each changed publication, the adapter strongly reads counter `n`, constructs sequence
`n + 1`, and submits one transaction containing the domain writes plus:

- a conditional counter update from `n` to `n + 1`; and
- an event put at `EVENT#{n+1:020d}#{event_id}` with stable-ID conflict checks.

A concurrent counter-condition failure retries from a fresh strongly consistent counter
read. `replay_realtime_events(after, limit)` queries event sort keys after the supplied
sequence. `realtime_high_watermark()` queries descending with limit one. One shared ECS
dispatcher repeatedly queries after its current cursor and fans out authorized events;
individual clients do not each scan or merge partitions. A dispatcher starts from a strongly
read high watermark and then queries after that cursor; reconnecting consumers use the
existing replay API from their own last cursor before joining the live feed.

The Sprint 4 target retains realtime events without TTL because the current repository has
no approved retention window. The single partition deliberately preserves the current total
order and is acceptable only for Validation Prototype volume. #786, owned by the Backend/AWS
owner, must record consumed capacity, throttling, retry, and alarm evidence before AWS is
reported verified. A measured throughput limit that is insufficient blocks the AWS profile
and requires a separately approved ordering/sharding contract; #991 does not silently shard
the stream.

## Item and transaction limits

DynamoDB permits at most 400 KB per item and 100 actions / 4 MB per transaction. The
adapter target budget is 300 KiB for every serialized item, including key and adapter
metadata, leaving headroom for expression and format changes.

| Aggregate | Physical layout | Overflow rule |
| --- | --- | --- |
| Working Claim | Core `META`; one `FORM#{field_code}` item per form field; one `CONTENTS#{item_id}` item per Contents item; one `CONSENT#{consent_ref}` item per external-service consent | Rehydrate one `WorkingClaim`. Any item over 300 KiB is `oversized`; no partial write. |
| Evidence | Core Evidence item plus one immutable `MATERIAL_VERSION#{version}` item for every archived material generation | Rehydrate ordered material history. Current material and each history generation must independently fit. |
| Message | One canonical item | Current content bounds normally fit; serialization is still measured. |
| Runtime turn | Every implemented Runtime record remains its own canonical item; lists of envelopes, tool results, and work items are not embedded into one turn item | Any individual oversized record or oversized atomic turn is blocked; records are never truncated. |
| Audit | One canonical append-only event plus bounded access references | Event and each projection must fit; no source refs or envelope fields are dropped. |
| Realtime | One bounded event and one singleton counter | Event must fit; no domain payload is copied into realtime. |

For an atomic write, let:

- `D` be changed canonical domain items, including changed Claim fragments;
- `P` be access-projection puts/deletes and uniqueness lookup items;
- `I` be the idempotency action bundle when the current method requires it: canonical
  record, Claim/actor projection, and Claim/actor generation update/retirement guard;
- `A` be append-only audit items and their projections;
- `R=2` for a changed realtime publication (counter update plus event), otherwise `0`.

The exact action count is `D + P + I + A + R`. The adapter must calculate count and
serialized bytes before calling DynamoDB. Important mutation families are:

| Mutation family | Records included in one current atomic boundary |
| --- | --- |
| Claim creation | Claim fragments, Claim owner, Session, customer/global/search/Claim-session projections, realtime counter/event |
| Session mutation/checkpoint | Changed Claim fragments, current/replaced Session, optional FollowUp and Branch Evaluation, idempotency, projections, realtime counter/event |
| Claim/child mutation | Changed Claim fragments, each supplied child, optional Session, idempotency, applicable audit events, all changed projections, realtime counter/event |
| Agent turn | Changed Claim fragments and Session, two Messages, Agent Decision, optional Handoff/Evidence/Branch Evaluation/Runtime Trace, every individual Runtime turn record, idempotency, projections, realtime counter/event |
| Staff/ownership mutation | Changed Claim fragments, Staff Action/Collaboration/Coworker/Customer Update/Signal Decision/Handoff as supplied, optional Staff Agent execution, idempotency, audit, projections, realtime counter/event |
| Retrieval bundle | Retrieval plus every Review Signal and Claim-order projections; no Claim revision change unless the current caller supplies a separate governed mutation |
| Anonymous promotion | Owner/Claim/customer-projection/realtime actions, one immutable alias per Claim/anonymous-actor idempotency record, and one Claim-scoped actor-retirement update; no child rewrite |

The current domain does not bound the total number of changed Claim fragments or Runtime
children tightly enough to prove that every valid input fits 100 actions and 4 MB. #991
does not invent a new public error, truncate records, split a currently atomic runtime
mutation, or weaken consistency. If preflight finds a valid runtime mutation above either
limit, the DynamoDB capability remains `unavailable` until the Backend owner adds an
approved bound or transaction contract. #992 must report this as `oversized`, not success.

## Migration and repeatability rules

Migration runs while the DynamoDB profile is not serving application traffic. It may write
canonical items and projections in deterministic batches, but the profile cannot be enabled
until a complete source snapshot is reconciled and a single dataset completion marker records
the source snapshot, inventory version, item count, and fingerprint. A failed run has no
completion marker and is never readable as a complete migration.

All source records for one run are read in one MongoDB session and transaction using
`snapshot` read concern. The run records its migration ID, MongoDB cluster/operation time,
database and collection identity, inventory version, and start time before transforming any
record. Parent, child, ownership, revision, idempotency, audit, and realtime reads must use
that same session and snapshot. A provider that cannot establish or retain this consistent
snapshot fails the run before target writes; the migration must never combine records from
different live moments. #992 may validate this snapshot metadata and repeatability against
local MongoDB, but that remains local preflight rather than AWS migration evidence.

For every source record, the migration derives the same canonical key and normalized content
fingerprint on every run. Results are classified as:

- `migrated`: target absent and deterministic items written;
- `unchanged`: every target item and fingerprint already match;
- `conflict`: authoritative key exists with different identity, scope, or content;
- `invalid`: source violates identity, ownership, relationship, or ordering rules;
- `oversized`: an item or required atomic bundle exceeds the target budget;
- `failed`: infrastructure or serialization prevented a conclusive result.

The migration preserves source identity, revision, timestamps, idempotency triplets,
request fingerprints, audit envelopes, global realtime sequence, and provenance. It does
not allocate new domain IDs. Resume skips only exact `unchanged` records. Conflicts,
invalid rows, oversized rows, unknown record types, and gaps in global realtime sequence
prevent the completion marker.

## #992 local rehearsal assertions

`#992` is local design validation against MongoDB; it does not write DynamoDB or claim AWS
connectivity. It must derive assertions from this mapping rather than from a manually
maintained subset.

| Assertion group | Required proof |
| --- | --- |
| Inventory completeness | Discover all 45 allowlisted record types; reject unknown types; prove excluded SQLite/MinIO/contract-only concepts are not read as MongoDB records. |
| Identity | Produce one deterministic canonical key per source identity; prove separator-safe compound encoding and idempotency hash collision checks. |
| Relationships | Resolve Claim/Session/Message, Claim children, Runtime turn, Staff Agent, Evidence, external task, Retrieval/review, and audit references; reject dangling or cross-owner links. |
| Ownership | Verify every Claim child customer matches the current Claim before converting it to `owner_ref`; simulate anonymous promotion without child rewrites. |
| Ordering | Prove customer Claim `updated_at`, Session, Message, child-list, audit, Staff Agent, and global realtime ordering including stable ID tie-breaks. |
| Uniqueness | Detect duplicate idempotency triplets, promotion-alias collisions, Evidence Claim target/Evidence tuples, External Task Claim/Evidence tuples, Message client IDs, Staff Agent client IDs, Contents item/Evidence tuples, external-task results, open FollowUps, and one Motor other-driver per Claim. |
| Size | Serialize every target item and report bytes; reject over 300 KiB; calculate action count and bytes for every reconstructed atomic mutation family. |
| Repeatability | Two transformations of the same snapshot produce identical keys, fingerprints, items, projections, and counts; an interrupted run resumes without duplicates. |
| Conflict safety | Changed content under an existing authoritative identity reports `conflict`; no last-write-wins replacement is accepted. |
| Realtime | Preserve unique contiguous source sequence and replay-after/high-watermark behavior; gaps or duplicate sequence values fail. |
| Reporting | Record source head, inventory version, local-only evidence level, counts by result class, and every unresolved reconciliation point. |

## Provisional decisions and reconciliation owners

| Decision or dependency | Current assumption | Affected target | Reconciliation owner and point | Risk if changed |
| --- | --- | --- | --- | --- |
| Message historical revision (#983/#989) | #989 is merged at this baseline; `message_turn_kind` and positive `message_turn_revision` are now preserved with idempotency while Message identity and ordering remain unchanged | Message canonical, session access items, and idempotency payload | Reconciled at `origin/main` `e4a3f498d054154462d43f390ec72ed8267b5c16`; #992 must retain the added fields | Omitting either field would break historical replay revision even though Message identity still matched. |
| Anonymous idempotency promotion | Governed destination aliases plus Claim-scoped anonymous retirement preserve the original triplet and disable stale anonymous replay | Idempotency canonical items, Claim/actor projections, aliases, retirement item, promotion action count | Backend owner before DynamoDB adapter/profile enablement | Current protocol cannot express alias resolution; omission loses authenticated replay, while unbounded aliasing can exceed transaction limits. |
| Evidence integrity (#986) | Stable Evidence ID and append-only material generations remain authoritative | Evidence core/version items and S3 references | Backend owner before migration tooling is frozen | Material layout or visibility could require remapping. |
| Claim creation evidence (#987) | Current atomic creation boundary remains authoritative | Claim creation action count and provenance | Backend owner before adapter implementation | Reservation/provenance records could increase transaction cardinality. |
| External task attempts (#984) | Current task/request/result identities and uniqueness remain authoritative | External-task canonical and lookup items | Backend owner before adapter implementation | A separately approved attempt record would add inventory and projections. |
| Workbench capability (#985) | Application permissions stay separate from IAM | Search and staff access projections | Backend owner at Workbench contract reconciliation | IAM must not become application authorization. |
| Global realtime capacity | One partition preserves the implemented total order | `SYSTEM#REALTIME` | Backend/AWS owner in #786 after real AWS load evidence | Insufficient capacity keeps AWS runtime unavailable. |
| Transaction cardinality | Current valid inputs may exceed DynamoDB hard limits | All multi-record runtime writes | Backend owner before enabling DynamoDB profile | Splitting would violate atomicity; silent truncation would corrupt evidence. |
| Identity and Control Plane placement | Existing SQLite stores remain separate | No #991 target | Separate approved architecture issue if deployment requires relocation | Pulling them into #991 would change authority and credential scope. |

If a dependency changes a field, state, revision rule, idempotency identity, Evidence
metadata, RAG citation, or readiness capability, the owner must update the relevant
authoritative contract first. This design and #992 assertions then reconcile to that
contract; migration code never overrides it.

## AWS limitation and acceptance evidence

This document does not implement a DynamoDB repository, create a table or index, transfer
records, change MongoDB, or validate S3, DynamoDB, Bedrock, Knowledge Bases, ECS, IAM,
Secrets Manager, or CloudWatch. The AWS profile remains fail-closed until #786 records
real account evidence.

`#991` is complete when review confirms that:

- all 45 implemented MongoDB record types and all excluded adjacent stores are explicit;
- each source identity, owner, read order, uniqueness rule, canonical item, access path,
  and atomic boundary is implementable without a request-path table scan;
- idempotency uses the exact actor/route/key authority with conditional creation;
- global realtime replay, high watermark, watch integration, retention, and capacity risk
  are explicit;
- anonymous Claim promotion is atomic without an unbounded child rewrite;
- 300 KiB item budgets and 100-action/4-MB transaction preflight determine readiness;
- #992 has executable local assertions and cannot misreport local transformation as AWS
  validation; and
- the design remains provider-neutral and does not change current API or business
  semantics.
