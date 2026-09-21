## Purpose

This document defines the pre-account migration design for moving the local MongoDB
operational records to DynamoDB. It is a target design and migration reference, not
evidence that AWS is configured or that a DynamoDB adapter exists.

The design preserves the provider-neutral records and access boundaries in the
[Persistence Contract](../persistence-schema.md) and [Data Architecture](../data-architecture.md).
It does not introduce a second Claim State, field vocabulary, lifecycle, permission
model, or API representation.

## Current source and target boundary

The current source is the local MVP persistence model. Its core Claim persistence is
MongoDB, while claimant/staff identity and Control Plane data use separate SQLite stores
in the local composition. The planned target in this issue is a transactional DynamoDB
store for the MongoDB-backed operational records, with S3 and a separate governed
knowledge store handled by the related storage-migration work. MongoDB and MinIO remain
local rehearsal providers until AWS access is verified.

The following boundaries apply to this design:

| Area | Source of truth | Migration treatment |
| --- | --- | --- |
| Logical records and relationships | `docs/persistence-schema.md` and existing domain models | Preserve record identity, ownership, lifecycle, revision, timestamps, and source references. |
| API resources and visibility | `docs/api.md` and current projection rules | Do not expose DynamoDB item names, keys, indexes, or provider fields. |
| Claim revision and idempotency | Current Claim State transaction contract | Use conditional writes and transaction boundaries; do not create a second revision token. |
| Evidence bytes | Active object-store contract | Migrate metadata and protected references with the record; transfer bytes under the separate MinIO/S3 plan. |
| Knowledge documents and chunks | `docs/rag-ingestion.md` and knowledge-source contracts | Keep outside operational Claim partitions; migrate under the separate MinIO/RAG preparation issue. |
| Secrets and credentials | Runtime secret boundary | Never copy secrets, bearer tokens, password hashes, or raw provider payloads into migration data. |

The `local_mvp` composition is therefore not one MongoDB-only source. The MongoDB
rehearsal covers the core Claim persistence boundary. The SQLite identity and Control
Plane stores are included below as adjacent logical records so the target inventory does
not hide an ownership gap, but their migration is not silently included in #991 or #992.
Their final AWS placement requires a separate approved target decision.

## Access patterns

The design starts from the current required access patterns rather than from a
MongoDB collection or an API route. The first DynamoDB target must support these
operations without a table scan:

| Access pattern | Required scope | Target query shape |
| --- | --- | --- |
| Read one Claim | One Claim after ownership or staff authorization | Claim partition, Claim metadata item. |
| List a customer's Claims | One customer in stable order | Customer GSI with Claim entries ordered by creation time and ID. |
| Conditionally update Claim State | One Claim and expected revision | Claim partition transaction with a revision condition. |
| Read and resume a Session | One persisted Session bound to one Claim and customer | Session lookup plus Claim/session scope index. |
| Append and page Messages | One Session with visibility filtering | Session partition ordered by `(created_at, message_id)`. |
| Register and list Evidence | One Claim, or claimant-authorized customer history | Claim partition plus customer-scoped Evidence index. |
| Read Handoffs and WorkItems | One Claim or staff queue scope | Claim partition plus bounded queue index where required. |
| Read ExternalTask and request state | One Claim or operation identity | Claim partition plus operation/idempotency lookup. |
| Read and append Audit events | Authorized subject and time range | Subject/time index with append-only audit items. |
| Resolve idempotency | Actor, operation, client key, and fingerprint | Idempotency lookup index with conditional creation. |
| Read branch and retrieval evidence | One Claim and evaluated revision | Claim partition, with no independent public projection unless the current contract adds one. |

These access patterns are derived from the current Persistence Contract. They are not a
commitment to a production capacity model, throughput target, or final AWS table count.

## Provisional DynamoDB layout

The initial target is one operational table with an overloaded primary key and bounded
secondary indexes. A later capacity or isolation decision may split tables, but any split
must preserve the same logical records, access boundaries, conditional writes, and
provider-neutral repository ports.

The base key fields are:

| Field | Meaning |
| --- | --- |
| `pk` | Item's authoritative aggregate or identity partition. |
| `sk` | Item type and stable ordering within that partition. |
| `entity_type` | Existing logical record category, not a new domain enum. |
| `entity_id` | Existing stable record identity. |
| `customer_id` | Ownership scope where the current record has one. |
| `claim_id` | Claim scope where the current record has one. |
| `revision` | The record's current provider-neutral revision where defined. |
| `created_at` / `updated_at` | Existing timestamps used for deterministic ordering and migration audit. |
| `source_provider` / `source_record_id` | Migration provenance only; not an API field or authority override. |

The following item families are provisional key shapes. The exact serialized field set
must come from the current repository contract at implementation time. `Implemented`
means that the current backend has a corresponding domain record and persistence
boundary; a row in the persistence contract alone is not evidence that a source
record exists. Only rows marked `Implemented` and `Yes` are eligible inputs to #992.

| Logical record | Source store | Implementation status | In scope for #991 | Current contract relationship | Provisional target item shape | Scope and migration rule |
| --- | --- | --- | --- | --- | --- | --- |
| Customer account (`CustomerAccountRecord`) | SQLite claimant identity store | Implemented | No | Account authority and claimant authentication are owned by the identity adapter. | None assigned | Identity-store migration requires a separate approved target decision. Do not map claimant authentication or account authority to DynamoDB in #991. |
| Identity record | MongoDB core persistence | Implemented | Yes | Customer-owned protected identity record linked by `customer_id`; account authority remains outside this migration. | `pk=CUSTOMER#{customer_id}`, `sk=IDENTITY#{identity_id}` | Preserve protected ciphertext, mask, provenance, lifecycle, and revision; never migrate plaintext. |
| Payment destination | MongoDB core persistence | Implemented | Yes | Customer-owned protected payment destination linked by `customer_id`; account authority remains outside this migration. | `pk=CUSTOMER#{customer_id}`, `sk=PAYMENT#{payment_destination_id}` | Preserve protected value references and masks; never migrate account secrets as plaintext. |
| Policy summary | Synthetic policy/history source or separate governed store | Not implemented as a MongoDB source record | No | Policy/history remains synthetic or separately governed and is not an operational MongoDB record for this issue. | None assigned | Keep structured policy data outside this MongoDB-to-DynamoDB rehearsal; do not turn it into ordinary RAG text. |
| Customer memory | No implemented source record; contract-only concept | Not implemented | No | The persistence contract describes the concept, but the current backend has no corresponding source record, repository method, or adapter boundary. | None assigned | Do not assign a DynamoDB target or include Customer memory in #991/#992. A future migration requires a separate persistence contract and implementation first. |
| Asset | MongoDB core persistence | Implemented | Yes | Customer-owned typed asset linked by `customer_id`; Claim asset snapshots reference the selected asset and revision. | `pk=CUSTOMER#{customer_id}`, `sk=ASSET#{asset_id}` | Preserve owner, typed asset details, active state, revision, and timestamps. |
| Staff account | SQLite staff identity store | Implemented | No | Staff identity and role authority are owned by the staff identity adapter. | None assigned | Preserve the existing staff identity boundary; password hashes remain protected and are not part of #991 migration evidence. |
| Staff auth session | SQLite staff identity store | Implemented | No | Staff bearer-session authority is owned by the staff identity adapter. | None assigned | Do not migrate bearer values or token hashes; target placement requires a separate identity decision. |
| Claim | MongoDB core persistence | Implemented | Yes | Working Claim State is linked to one `customer_id` and owns its revision and workflow. | `pk=CLAIM#{claim_id}`, `sk=META` | Preserve customer ownership, Claim State, workflow, responsibility, retention, and current revision. |
| Claim asset snapshot | MongoDB core persistence | Implemented | Yes | Immutable selected asset details are linked to one Claim revision and source Asset revision. | `pk=CLAIM#{claim_id}`, `sk=ASSET_SNAPSHOT#{snapshot_id}` | Preserve immutable selected asset details, source asset revision, provenance, and capture time. |
| Session | MongoDB core persistence | Implemented | Yes | Every persisted Session has required `session_id`, `claim_id`, and `customer_id`; it is Claim-bound at the current contract. | `pk=SESSION#{session_id}`, `sk=META` | Preserve required Claim/customer ownership, summary revision, question accounting, and lifecycle. No non-Claim or optional-Claim Session is included in the current mapping. |
| Message | MongoDB core persistence | Implemented | Yes | Message is linked to a persisted Session and its Claim/customer scope, with visibility and ordering rules. | `pk=SESSION#{session_id}`, `sk=MESSAGE#{created_at}#{message_id}` | Preserve visibility, actor, Claim/session references, and stable ordering. Historical message-turn revision remains separate from current Claim revision pending #983. |
| Agent turn | MongoDB core persistence | Implemented | Yes | Runtime turn evidence is linked to a Session and optional Claim scope according to the current turn contract. | `pk=SESSION#{session_id}`, `sk=TURN#{created_at}#{turn_id}` | Preserve bounded proposal, execution, trace, tool-result, policy/version, usage, latency, and limitation references; exclude prompts, credentials, raw provider payloads, and hidden reasoning. |
| Staff Agent interaction and execution | MongoDB core persistence | Implemented | Yes | Staff session records remain staff-owned; each message or execution carries explicit Claim scope where the current contract requires it. | `pk=STAFF_SESSION#{session_id}`, `sk=MESSAGE#{created_at}#{message_id}` or `EXECUTION#{execution_id}` | Preserve explicit Claim scope, draft identity, confirmation source, action, expected/resulting revision, and idempotency; application capability remains separate from AWS IAM. |
| Evidence metadata | MongoDB core persistence | Implemented | Yes | Evidence metadata is Claim-owned and references protected object storage through the current Evidence contract. | `pk=CLAIM#{claim_id}`, `sk=EVIDENCE#{evidence_id}` | Preserve stable Evidence identity, material version/history, lifecycle, ownership, provenance, checksum, and protected object reference. |
| Motor other driver | MongoDB core persistence | Implemented | Yes | Bounded participant data is linked to one Claim and its customer ownership scope. | `pk=CLAIM#{claim_id}`, `sk=PARTICIPANT#{participant_id}` | Preserve the bounded participant record and ownership links; do not create a generic participant lifecycle. |
| Evidence association | MongoDB core persistence | Implemented | Yes | Immutable same-Claim link connects Evidence to its owning record under the current ownership checks. | `pk=CLAIM#{claim_id}`, `sk=EVIDENCE_LINK#{association_id}` | Preserve immutable same-Claim links and source/target ownership checks. |
| WorkItem | MongoDB core persistence | Implemented | Yes | WorkItem is Claim-scoped with owner, blocker, due time, and completion evidence. | `pk=CLAIM#{claim_id}`, `sk=WORK#{work_item_id}` | Preserve purpose, owner, blocker, due time, source references, and completion evidence. |
| Mitigation | No implemented source record; contract-only concept | Not implemented | No | The persistence contract describes mitigation vocabulary, but the current backend has no corresponding source record, repository method, or adapter boundary. | None assigned | Do not assign a DynamoDB target or include Mitigation in #991/#992. A future migration requires a separate persistence contract and implementation first. |
| Handoff | MongoDB core persistence | Implemented | Yes | Handoff is Claim-scoped and preserves ownership transfer and resume context. | `pk=CLAIM#{claim_id}`, `sk=HANDOFF#{handoff_id}` | Preserve transfer packet, queue, owner, status, lifecycle timestamps, and resume target. |
| Review and staff action | MongoDB core persistence | Implemented | Yes | Internal review signals and staff actions are Claim/work scoped and remain staff-only where required. | `pk=CLAIM#{claim_id}`, `sk=REVIEW#{review_id}` or `STAFF_ACTION#{action_id}` | Preserve internal signal, source references, professional decision, authority, and immutable action evidence. |
| External request/task | MongoDB core persistence | Implemented | Yes | External request/task records are Claim-scoped and linked by operation identity; attempts remain governed by #984. | `pk=CLAIM#{claim_id}`, `sk=EXTERNAL#{request_or_task_id}` | Preserve consent, authority, operation identity, provider-neutral result, and reconciliation state. Attempt records remain append-only pending #984. |
| Follow-up | MongoDB core persistence | Implemented | Yes | Follow-up is Claim-scoped and does not become a Claim lifecycle state. | `pk=CLAIM#{claim_id}`, `sk=FOLLOW_UP#{follow_up_id}` | Preserve due time, responsibility, attempt count, channel, outcome, and status without making follow-up a Claim lifecycle state. |
| Integration and operation configuration | SQLite Control Plane store | Implemented | No | Configuration and operation authority are owned by the Control Plane repository. | None assigned | Preserve the Control Plane ownership boundary; do not copy provider credentials or assign a DynamoDB target in #991. |
| Versioned configuration | SQLite Control Plane store | Implemented | No | Published configuration revisions and audit references are owned by the Control Plane repository. | None assigned | Preserve immutable published versions and audit references; target placement requires a separate decision. |
| Branch evaluation | MongoDB core persistence | Implemented | Yes | Branch evaluation is Claim-scoped and records the evaluated Claim revision. | `pk=CLAIM#{claim_id}`, `sk=BRANCH_EVAL#{evaluation_id}` | Preserve evaluated Claim revision, selected family, active branches, field states, and application status. |
| Retrieval record | MongoDB core persistence | Implemented | Yes | Retrieval evidence is Claim-scoped and preserves source/version/citation metadata without raw provider payloads. | `pk=CLAIM#{claim_id}`, `sk=RETRIEVAL#{retrieval_id}` | Preserve source, version, citations, limitations, visibility, and retrieval time. Raw provider payloads are excluded. |
| Audit event | MongoDB core persistence | Implemented | Yes | Audit events are append-only and scoped to the Claim or authorized subject under the current audit envelope. | `pk=CLAIM#{claim_id}` or `pk=AUDIT_SUBJECT#{subject_id}`, `sk=AUDIT#{occurred_at}#{event_id}` | Preserve immutable envelope, actor, authority, outcome, correlation/idempotency reference, and resulting Claim revision. |
| Realtime event | MongoDB core persistence | Implemented | Yes | Durable realtime events are Claim/customer scoped ordering records, not a second domain record. | `pk=CLAIM#{claim_id}` or customer scope, `sk=REALTIME#{sequence}` | Preserve durable sequence and bounded resource hints; do not treat it as a second domain record. |
| Idempotency result | MongoDB core persistence | Implemented | Yes | Idempotency result is bound to actor, operation, client key, fingerprint, and resulting revision. | `pk=IDEMPOTENCY#{scope}`, `sk=OPERATION#{operation_id}` | Preserve actor, operation, client key, request fingerprint, typed result, and resulting revision. |
| Retention record | No implemented source record; contract-only concept | Not implemented | No | The persistence contract describes retention vocabulary, but the current backend has no corresponding source record, repository method, or adapter boundary. | None assigned | Do not assign a DynamoDB target or include Retention in #991/#992. A future migration requires a separate persistence contract and implementation first. |

## Secondary indexes

The following index projections are the minimum provisional set. They are derived from
the access patterns above and must be confirmed against measured query shapes before
IaC is written.

| Index | Projection purpose | Example key shape |
| --- | --- | --- |
| `GSI1` | Customer-scoped Claim, Asset, Evidence, and in-scope operational record listing; not claimant identity listing | `gsi1pk=CUSTOMER#{customer_id}`, `gsi1sk={entity_type}#{created_at}#{entity_id}`. |
| `GSI2` | Claim-scoped Session, Evidence, WorkItem, Handoff, and ExternalTask lookup | `gsi2pk=CLAIM#{claim_id}`, `gsi2sk={entity_type}#{created_at}#{entity_id}`. |
| `GSI3` | Session-scoped Message ordering when messages use a separate aggregate partition | `gsi3pk=SESSION#{session_id}`, `gsi3sk=MESSAGE#{created_at}#{message_id}`. |
| `GSI4` | Operation and idempotency resolution | `gsi4pk={operation_or_idempotency_scope}`, `gsi4sk={identity}#{fingerprint}`. |
| `GSI5` | Bounded staff queue and audit reads where the current contract requires them | `gsi5pk={authorized_queue_or_subject}`, `gsi5sk={time}#{entity_id}`. |

These indexes are not application permissions. Every query still applies the current
ownership, actor, visibility, and Claim authorization rules before returning a projection.
The `GSI` names and projections remain provisional until the migration implementation
records real query and capacity assumptions.

## Consistency and migration rules

The migration must preserve the current write boundaries:

1. A Claim mutation uses the stored current Claim revision as its compare-and-set value.
   A stale expected revision fails without a partial migration or write.
2. A successful material Claim mutation advances the Claim revision exactly once.
3. Idempotency records bind actor, operation, client key, and request fingerprint. An
   identical retry returns the stored typed result; a different request under the same
   key is a conflict.
4. Claim mutation, idempotency result, applicable Branch Evaluation, audit facts, and
   durable realtime persistence remain one approved transaction boundary where the
   current contract requires that boundary.
5. Messages preserve the deterministic `(created_at, message_id)` order. The historical
   message-turn revision must not be rewritten by later Claim, Evidence, or retrieval
   writes; #983 owns the final replay contract.
6. Evidence metadata and bytes remain separate. The migration carries metadata,
   checksum, provenance, and protected references; it does not expose adapter-owned
   object keys in claimant projections.
7. Evidence replacements preserve the stable Evidence identity and append material
   history. A replacement must not become a second requirement record.
8. ExternalTask attempts are append-only and distinguish retryable, terminal, and unknown
   outcomes. The final attempt and reconciliation shape remains subject to #984.
9. Raw provider payloads, credentials, bearer tokens, password hashes, and unrestricted
   model context are excluded from the target records.

## Migration provenance and idempotency

The future migration tool must treat the source record identity and content fingerprint
as an input to a deterministic migration identity. A record is eligible for a second run
only when the source identity, source version, and normalized content fingerprint match the
already migrated target. A mismatch must stop that record as a conflict rather than silently
replace the target.

Each migration result should be classified as `migrated`, `unchanged`, `conflict`,
`invalid`, or `failed`. The result should retain source identity, target identity,
checksum or content fingerprint, migration run identity, and a bounded failure reason.
This record is migration evidence and is not an application audit event unless the current
audit contract explicitly adds such an event.

The local rehearsal in #992 must read only rows whose `Implementation status` is
`Implemented`, `In scope for #991` is `Yes`, and `Source store` is MongoDB core
persistence. It must explicitly exclude contract-only/not-implemented rows, the SQLite
claimant identity store, SQLite staff identity store, SQLite Control Plane store,
synthetic policy/history source, and knowledge object store. It must prove this behavior
against MongoDB without writing to DynamoDB, and prove that a partial run can resume
without duplicating logical records or changing an authoritative revision.

## Contract reconciliation points

The mapping is deliberately provisional in the following areas:

| Backend issue | Reconciliation required before formal migration tooling |
| --- | --- |
| #983 | Confirm separate historical message-turn revision and current Claim revision fields and replay readback. |
| #987 | Confirm Claim-creation Evidence set, operation reservation, provenance, and interrupted/unknown outcome records. |
| #986 | Confirm Evidence material/version metadata, Message references, actor/visibility checks, and total ordering. |
| #984 | Confirm ExternalTask attempt identity, append-only history, retry/terminal/unknown outcome, and reconciliation records. |
| #985 | No data-key change is expected; application Workbench capabilities remain separate from AWS IAM roles. |

If one of these contracts changes, the affected mapping and local rehearsal must be
updated before the migration tool is frozen. No migration design decision may silently
override the owning Backend issue.

## Out of scope and AWS limitation

This document does not claim that the AWS profile is configured, reachable, permitted, or
deployed. The current AWS runtime profile remains fail-closed until the capabilities and
permissions in #786 are verified.

This issue does not implement a DynamoDB repository, create tables or indexes, migrate
real records, change the local MongoDB model, change Claim or Evidence business semantics,
or validate Bedrock, Knowledge Bases, ECS, IAM, or S3. Those activities require separate
bounded work after the design and AWS prerequisites are complete.

## Acceptance evidence for #991

- The logical-record inventory and target mapping are recorded in this document.
- Every inventory row names its source store, implementation status, current contract relationship, and whether it is in scope for #991.
- Only implemented MongoDB records marked in scope are eligible inputs to #992; contract-only concepts are explicitly excluded.
- Session mapping follows the current required `claim_id` and `customer_id` relationship and excludes non-Claim sessions.
- Access patterns precede the provisional key and index layout.
- Revision, idempotency, audit, provenance, ownership, and visibility boundaries are explicit.
- Customer identity, staff identity, and Control Plane records are explicitly excluded from #991/#992.
- Local-only and AWS-dependent work are separated.
- Reconciliation points for the active Backend issues are explicit.
- The document is indexed from `docs/README.md` and does not change the current API or persistence contract.
