# Data Architecture

## Purpose

This document defines how Northwind classifies, stores, retrieves, and exposes
data. It also defines the provider-neutral boundary that allows one complete
data runtime profile to be selected without changing the domain, Agent,
claimant, or staff contracts.

The physical services, production schemas, retention periods, Northwind data
access, and AWS permissions remain open until they are verified. Candidate
service mappings below are implementation options, not claims of availability.

## Core Decisions

- One running application uses exactly one data runtime profile.
- `cloudflare`, `mongodb`, and `aws` profiles are mutually exclusive. A process
  must not silently read from or write to another profile as a fallback.
- Domain records and service interfaces are provider-neutral. Provider keys,
  SDK types, transport payloads, and infrastructure names stay inside adapters.
- Formal Claim State, customer preferences, conversation context, evidence,
  knowledge documents, retrieval results, internal review material, and audit
  records remain separate even when a provider stores them in one physical
  database.
- Claim-specific records and customer-level records remain separate. A stable
  `customer_id` links them, but the Customer record does not contain complete
  claim history, message transcripts, unfinished claim details, or staff-only
  review signals.
- A short-lived, purpose-limited Customer Memory may retain a confirmed preference
  or an expiring continuity hint after a claim is purged. An interruption is not a
  permanent negative customer trait and must not become a fraud, reliability, or
  service-priority decision by itself.
- Raw evidence bytes do not belong in Claim State. Evidence metadata retains a
  protected object reference owned by the active adapter.
- RAG supports knowledge retrieval. It does not replace structured claim,
  policy, customer, or claim-history queries and does not authorise high-impact
  decisions.
- The Agent accesses data through application tools and services. It does not
  query a provider SDK, database collection, bucket, or vector index directly.
- The internal FNOL form is dynamic by selection, not by schema invention.
  Approved rules activate only predefined fields, tags, and content branches from the
  [FNOL Information Model](fnol-field-model.md).
- Claim content branches and Claim lifecycle are separate. Content branches determine
  applicable incident information; lifecycle and WorkItems determine current ownership,
  waiting, review, creation, and recovery.
- The model does not own Claim State. Model requests, proposals, validated execution
  plans, tool outcomes, and final turn results remain separate records.
- Northwind's Administration and Control Plane owns system and knowledge
  management. Runtime services consume approved configuration and published
  knowledge rather than depending on a third-party note application.

## Data Classes

| Data class | Examples | Canonical use | Agent access | Visibility |
| --- | --- | --- | --- | --- |
| Customer profile | identity reference, permitted contact details, communication preferences | Identify the authorised customer and adapt communication | Minimum fields required for the current task | Customer-scoped and authorised staff |
| Customer preferences and memory | explicit communication preference, short-lived continuity hint, source, visibility, expiry | Resume a useful interaction without retaining full claim content | Only purpose-relevant, source-linked, non-sensitive memory | Customer and authorised staff according to each record's visibility |
| FNOL field and branch definitions | field category, value contract, claim family, branch, applicability, current-action requirement, confirmation policy | Constrain the dynamic form to predefined information and versioned rules | Active field and branch metadata only | Published definitions are controlled; claimant sees only relevant labels and questions |
| Working Claim State | incident facts, form fields, active content branches, independent claim attributes, lifecycle status, next action, responsibility, and retention timestamps | Authoritative current FNOL record | Bounded current snapshot | Claimant-safe projection, shared fields, and staff-only fields are separated |
| WorkItems | question, evidence, confirmation, professional judgement, external request, or system task; owner, status, blocked action, due time, source, completion evidence | Represent unresolved work independently of Claim lifecycle | Current purpose-relevant items only | Claimant-safe responsibility and staff operational detail are separated |
| Sessions and messages | intent, complete messages, bounded session summary, unresolved questions, prior commitments | Resume interaction without replacing Claim State; keep non-claim chat out of claim facts | Recent necessary messages and compact context only | Customer and staff according to message visibility |
| Agent turn records | TurnPlan, AgentProposal, ExecutionPlan, ActionEnvelopes, ToolRequests, ToolResults, TurnResult, policy and Registry versions | Separate proposed, authorised, attempted, and completed behaviour | Only the bounded current-turn objects | Role projection excludes hidden instructions, unnecessary model output, and internal diagnostics |
| Evidence metadata | evidence ID, type, state, provenance, checksum, protected object reference | Track evidence lifecycle and source | Safe metadata and extracted proposals | Claimant-safe metadata; protected provenance for staff |
| Evidence objects | images, PDFs, police documents, audio if approved | Original submitted material | Only through authorised evidence tools | Protected object access |
| Extracted evidence facts | proposed vehicle damage, dates, document fields | Candidate facts derived from evidence | Proposals with source references | Never confirmed solely because a model extracted them |
| Customer policy records | policy reference, product, status, effective dates, schedule, endorsements | Determine which contract may apply to the customer | Structured, authorised lookup | Customer-safe facts and staff review according to authority |
| Claim history | previous claim references, dates, types, status, outcomes | Support continuity and bounded review signals | Structured, customer-scoped lookup | Staff by default; claimant projection requires an explicit contract |
| Knowledge documents | policy wording, legislation, industry guidance, approved procedures | Answer process and wording questions with citations | RAG retrieval with scope filters | Controlled by document authority and access metadata |
| Retrieval records | returned facts, citations, source, version, retrieval time, limitations | Preserve what evidence supported an answer or review | Current relevant result only | Customer-safe citation or staff evidence according to source |
| Handoffs and staff work | transfer packet, queue, owner, staff action, review decision | Preserve responsibility and professional decisions | Status and authorised result only | Internal details remain staff-only |
| External coordination | capability and requirement version, request draft, disclosure manifest, authority, submission identity, provider state, verified response, reconciliation result | Track third-party work without treating one HTTP response as the complete lifecycle | Minimum current state through registered tools | Claimant sees safe status; request and provider detail remain restricted |
| Follow-up tasks | due time, responsible party, attempt count, channel, outcome | Track Agent or staff follow-up for paused or incomplete claims | Current task and safe claim context only | Staff; claimant sees only an authorised contact or status |
| Retention and purge records | expiry, hold, purge eligibility, deletion or anonymisation result | Apply retention policy without making deletion an Agent side effect | No routine Agent access | Restricted operations and audit access |
| Internal signals | ambiguity, conflicting evidence, review-required indicators | Route work for professional attention | Bounded reason and required action | Staff-only |
| Audit events | actor, action, authority check, revision, outcome, timestamp | Trace material changes | Not general model context | Restricted operational access |
| Model profiles | adapter and endpoint references, provider model identity, verified capabilities, data terms, allowed purposes, fallback group, evaluation bundle, lifecycle | Select a model by purpose without scattering provider configuration | Profile identity and allowed capability only | Restricted configuration; secrets remain external references |
| Evaluation data | synthetic conversations, expected trajectories, RAG relevance labels, corrected outputs, model-profile results | Compare models and verify Agent behaviour | Test and evaluation environments only | Synthetic or explicitly approved data |
| Operational telemetry | request IDs, latency, error class, token usage, retrieval metrics | Reliability and cost measurement | Aggregated metrics only | Restricted operational access |

## Dynamic FNOL Form, Content Branches, and Lifecycle

The detailed field groups, current coverage, selection states, and branch rules are
defined in the
[FNOL Information Model and Field Taxonomy](fnol-field-model.md). The architecture
separates three concerns:

```text
industry and process evidence
-> logical FNOL information model
-> approved field, tag, and content-branch definitions
-> claim-specific active form selected by controlled rules
-> stored field values, sources, states, and decisions
```

All possible form fields and processing tags are predefined. Dynamic form generation
means that the system selects an applicable subset for one claim; it does not allow a
model or client to create an arbitrary field name or schema.

A controlled content-branch graph may:

- interrupt ordinary collection for urgent safety or human-support needs;
- activate a primary motor, home, contents, or unknown claim-family branch;
- add conditional branches for another party, Police involvement, witness, theft,
  evidence state, material conflict, or another approved condition;
- classify active fields as required now, candidate now, pending later, inactive, or
  system-owned according to the current next action; and
- recalculate the active subset after new facts, correction, evidence, resume, or staff
  action without deleting source history.

One claim may hold several branch dimensions at the same time. For example, a motor
claim can also involve injury, another party, damaged property, pending Police evidence,
and professional review. A single route label must not overwrite those independent
facts, responsibilities, or decisions.

Content branches do not contain workflow states. The application-controlled lifecycle
tracks `no_claim`, active draft, waiting, staff support, professional review,
ready-to-create, creation, created, withdrawal, expiry, and purge or anonymisation. A
Claim may hold several independent WorkItems while holding one lifecycle state. Changing
lifecycle may change the current purpose and permitted tools, but it cannot rewrite
incident facts or content branches.

The current implementation contains 18 allowed field codes and a bounded four-field
intake path. It does not yet implement a data-driven branch engine, dynamic required-now
selection, or a published field and tag catalogue. Those remain implementation work and
must not be inferred from this architecture document.

## Logical Storage Responsibilities

The logical responsibilities stay stable even if one provider combines them
physically:

1. **Transactional store** holds customer references, Claim State, sessions,
   messages, customer preferences and memory, evidence metadata, policy/history
   retrieval records, Agent turn records, WorkItems, external coordination, handoffs,
   staff actions, follow-up tasks, active content-branch and rule references, revisions,
   idempotency records, retention work, and audit events.
2. **Object store** holds original evidence and other large binary objects.
   For the local MVP, the object-store port may use the S3-compatible MinIO
   adapter defined in [MinIO Object-Storage Boundary](minio-object-storage.md).
   MinIO is an object-store choice, not a separate data runtime profile; it
   does not change the provider-neutral domain or API contract.
3. **Knowledge document store** holds approved source documents, parsed text,
   versions, authority metadata, and chunk records.
4. **Retrieval index** supports metadata-filtered keyword and vector search over
   knowledge chunks.
5. **Evaluation store** holds synthetic scenarios, expected results, model
   comparison results, and RAG evaluation evidence outside production records.
6. **Configuration store** holds immutable published Agent Policy, Field, Content Branch,
   Lifecycle, Action, Tool, Staff Capability, Model Profile, Error, tag, and
   controlled-rule versions when those capabilities are implemented.

Physical co-location does not remove the logical visibility, retention,
ownership, or authority boundaries.

## Customer and Claim Relationship

The logical relationship is linked but not merged:

```text
Customer
  ├── CustomerPreferences
  ├── CustomerMemory
  ├── Claims
  │     ├── Sessions and Messages
  │     ├── Claim Fields and Evidence
  │     ├── Handoffs and Staff Work
  │     └── Follow-up Tasks
  ├── Interaction Metrics
  └── Authorised Audit References
```

`Customer` stores stable identity references and permitted contact details. Claim-specific
facts, messages, evidence, staff decisions, and unfinished-work details remain owned by
their claim or interaction records. `CustomerMemory` is a separate, source-linked record
for a small set of durable or short-lived facts that have an explicit product purpose.

An interaction with no credible claim intent may remain a session with
`interaction_intent = non_claim_intent` and no `claim_id`. If a user has already supplied
material incident facts, a draft claim may be retained while later unrelated messages
remain session-only.

After a temporary claim is purged, the system may retain an expiring category-level
continuity hint such as `waiting_external`, but not the full accident account
or transcript. An interruption must not by itself become a fraud, reliability, or
service-priority signal.

## Provider-neutral Ports

Application services depend on capability ports rather than one large provider
adapter:

```text
CustomerRepository
CustomerMemoryRepository
ClaimRepository
WorkItemRepository
SessionRepository
EvidenceMetadataRepository
EvidenceObjectStore
PolicyDataSource
ClaimHistoryDataSource
KnowledgeDocumentStore
KnowledgeRetriever
HandoffRepository
FollowUpRepository
RetentionRepository
AuditEventStore
RegistrySnapshotStore
AgentTurnStore
ExternalRequestRepository
ModelGateway
ToolExecutor
```

The existing `PersistenceRepository` may be decomposed gradually. A migration
must preserve current ownership, revision, idempotency, projection, and audit
behaviour while the smaller ports are introduced.

`ModelGateway` is not a data-runtime profile and does not select Cloudflare, MongoDB, or
AWS persistence. It is a provider-neutral inference port used by Agent Runtime. Model
providers may change independently of the one selected data profile, subject to privacy,
capability, policy, and evaluation constraints.

## Model Gateway Data Boundary

The implemented Gateway accepts a provider-neutral `ModelRequest` containing normalised
messages, an optional response schema, and optional tool declarations. It returns a
`ModelResponse` containing text or structured output, tool-call representations, finish
reason, token usage when supplied, and bounded provider model and request identifiers.
The implemented `GatewayAgent` builds a task-minimal Claim projection, requests a
structured legacy `AgentProposal`, rejects model-proposed internal signals and tool
execution, converts form suggestions to inference-sourced proposals, and relies on the
existing deterministic validator and server-rendered claimant response.

The `openai_compatible` adapter covers official, relay, and local endpoints that implement
the compatible chat-completions protocol. A non-compatible service implements the same
`ModelGateway` port and registers under a separate adapter name. Provider credentials,
raw payloads, prompts, and provider-specific SDK types stay inside the adapter boundary.
The implemented contract and limitations are defined in
[Model Gateway](model-gateway.md).

The target Gateway extends this base with an Instruction Compiler and purpose-aware
request metadata: request and model-profile identity, actor role, Claim scope, policy and
Registry versions, filtered retrieval context, allowed actions and tools, required
capabilities, token and timeout budgets, privacy class, and trace context. It normalises
refusal, incomplete output, limitations, latency, actual fallback profile, and safe
diagnostics into a higher-level result used by Agent Runtime.

The Instruction Compiler will render active Northwind Policy and Registry contracts into
provider-understood instructions, tool schemas, and response schemas. The compiled prompt
is an artifact, not authority. Runtime validates every proposal after the Gateway.

Future fallback may use only another active profile that satisfies the same purpose, required
capabilities, privacy and data terms, policy version, and evaluation threshold. A text
response cannot substitute for strict structured output, and fallback cannot widen Claim
scope or silently change a data-runtime profile.

The current Gateway does not implement provider retries, fallback selection, circuit
breaking, usage persistence, evaluation thresholds, remote capability negotiation,
streaming, the complete Instruction Compiler, Model Profile Registry, or target turn
records. Those remain implementation work and must not be reported as active until code,
configuration, API, persistence, fixtures, and tests support them together.

## Mutually Exclusive Runtime Profiles

The composition root selects one complete adapter bundle at startup:

```text
DATA_RUNTIME_PROFILE=fixture | cloudflare | mongodb | aws
```

```text
Application services
        |
provider-neutral ports
        |
one selected adapter bundle
        |
one data provider profile only
```

The selected profile must provide every required capability or fail startup
with an explicit configuration error. It must not obtain a missing capability
from a second profile without a separately approved architecture change.

| Profile | Candidate transactional store | Candidate object store | Candidate knowledge/index services | Status |
| --- | --- | --- | --- | --- |
| `fixture` | In-memory fixture repository | Synthetic object adapter, or explicitly configured local MinIO | Deterministic fixture retriever | Available for controlled tests and local demonstrations |
| `cloudflare` | D1 | R2 | R2 plus Vectorize and/or approved search service | Candidate; access and limits must be verified |
| `mongodb` | MongoDB Atlas collections | GridFS or an approved MongoDB-managed object pattern | Atlas Search and Atlas Vector Search | Repository adapter in progress; transactions, object storage, topology, and access are not yet verified |
| `aws` | DynamoDB or another approved AWS transactional service | S3 | OpenSearch, Bedrock Knowledge Bases, or another approved AWS retrieval service | Candidate; service access and permissions must be verified |

These mappings are alternatives. For example, selecting `mongodb` does not
store evidence in Cloudflare R2 or query an AWS vector index.

## Runtime Configuration and Assembly

Configuration identifies the profile and non-secret connection settings.
Credentials are supplied through approved secret or environment mechanisms and
must not be committed or logged.

The application composition root must:

1. validate that exactly one profile is selected;
2. validate all capabilities required by that profile;
3. instantiate one coherent adapter bundle;
4. expose health information without exposing secrets or physical keys;
5. refuse partial or mixed-provider assembly; and
6. run the same contract tests against every implemented profile.

The current implementation selects `fixture` by default and assembles its persistence,
evidence, structured policy/history, knowledge-document, and knowledge-retrieval
capabilities as one bundle. Selecting `cloudflare`, `mongodb`, or `aws` currently fails
startup with an explicit unsupported-profile error. Those profiles must remain
unavailable until one complete provider-specific bundle and its conformance tests exist;
the application does not fill missing capabilities from `fixture`.

The runtime capability table used by the composition root is:

| Capability | `fixture` | `cloudflare` | `mongodb` | `aws` |
| --- | --- | --- | --- | --- |
| `persistence` | `using_fixture` | `pending_confirmation` | `unavailable` | `pending_confirmation` |
| `evidence_storage` | `using_fixture` | `pending_confirmation` | `unavailable` | `pending_confirmation` |
| `policy` | `using_fixture` | `pending_confirmation` | `unavailable` | `pending_confirmation` |
| `claim_history` | `using_fixture` | `pending_confirmation` | `unavailable` | `pending_confirmation` |
| `knowledge_documents` | `using_fixture` | `pending_confirmation` | `unavailable` | `pending_confirmation` |
| `knowledge_retrieval` | `using_fixture` | `pending_confirmation` | `unavailable` | `pending_confirmation` |

The capability-status vocabulary separates readiness from implementation source.
`using_fixture` means that the controlled fixture capability is ready, while `verified`
means that a non-fixture provider capability has passed its required verification. Both
statuses are start-capable. `pending_confirmation` and `unavailable` are not
start-capable and appear in the named missing-capability error.

The table currently provides diagnostic input to `build_data_runtime_bundle`; it is not
the sole composition gate. `validate_data_runtime_bundle` independently rejects every
externally supplied non-fixture bundle until a complete provider-specific composition
path and its conformance tests are implemented. Changing a table entry to `verified`
alone therefore cannot enable a provider or assemble a mixed bundle. The current table
is intentionally conservative: MongoDB repository code exists, but complete provider
conformance, protected object storage, and runtime bundle verification are still
outstanding. MongoDB persistence is recorded as `pending_confirmation` after a bounded
Atlas connection and transaction probe. This does not make the profile start-capable.
Runtime bundles close provider repositories at application shutdown when the selected
repository exposes a close operation.

The `fixture` capability row is the default baseline. When the local fixture profile
explicitly selects the S3-compatible object adapter, the assembled bundle and readiness
check report that configured service instead. External bundle injection must match both
`DATA_RUNTIME_PROFILE` and `NORTHWIND_OBJECT_STORAGE_ADAPTER`; it cannot relabel fixture
storage as the configured service.

`DATA_RUNTIME_PROFILE` remains the only variable that selects a complete data-runtime
profile. Provider connection and secret-reference variables are introduced by their
corresponding adapter contracts rather than treated as profile selectors. The MinIO/S3
compatible evidence adapter is explicitly selected by
`NORTHWIND_OBJECT_STORAGE_ADAPTER=s3_compatible` and defines
`NORTHWIND_OBJECT_STORAGE_ENDPOINT`,
`NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID`, `NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY`,
`NORTHWIND_OBJECT_STORAGE_BUCKET`, `NORTHWIND_OBJECT_STORAGE_REGION`, and
`NORTHWIND_OBJECT_STORAGE_PRESIGN_EXPIRY_SECONDS`. Connection or credential variables
alone do not switch adapters, and this local object-store selection does not enable a
MongoDB, Cloudflare, or AWS data profile.

## Knowledge Base and RAG

### Knowledge scope

The knowledge base may contain approved policy wording, legislation, industry
guidance, claims procedures, service directories, and other non-customer
reference material. Customer policy schedules, Claim State, claim history,
messages, and staff-only decisions remain structured or protected operational
data rather than ordinary RAG documents.

### Source and chunk contract

Every indexed source and chunk must retain enough metadata to determine whether
it is applicable and citable:

```text
document_id
chunk_id
title
document_type
version
section_path
printed_pages
pdf_page_indices
source_uri
jurisdiction
insurer
product
effective_from
effective_to
authority
visibility
checksum
ingested_at
text
```

### Ingestion and retrieval

```text
Northwind Control Plane source
-> import and malware/type validation
-> OCR or text extraction
-> section-aware chunking
-> metadata and access classification
-> checksum and version record
-> keyword and vector indexing
-> metadata-filtered hybrid retrieval
-> optional reranking
-> cited result with limitations
-> Agent explanation or professional review
```

The Northwind Control Plane manages source upload or import, required metadata,
validation, version history, access control, ingestion status, retrieval testing,
publication, withdrawal, and audit. Published content and indexes are stored through
the active data runtime profile rather than read from a third-party note application at
request time.

### RAG authority boundary

- Retrieval results are evidence, not coverage, fraud, liability, approval, or
  rejection decisions.
- Retrieval must filter insurer, jurisdiction, product, effective period,
  document authority, visibility, and exact source version before similarity
  ranking.
- The current fixture retriever fails closed when insurer, product, authority,
  version, or effective time is omitted. It does not treat an omitted selector
  as permission to broaden a search. Global documents with no insurer or product
  are not executable retrieval candidates until an explicit governed scope and
  applicability contract is introduced.
- Answers must retain citations to the exact source version and section.
- Missing, conflicting, expired, or inapplicable evidence must be stated as a
  limitation and may require professional review.
- Prompt injection or instructions inside retrieved documents are untrusted
  content and must not alter system authority or tool permissions.

## Administration and Control Plane Data Flow

```text
Admin Console
-> authenticated Admin API
-> versioned configuration and knowledge services
-> validation, ingestion, evaluation, and connection jobs
-> approved publication record
-> active runtime-profile stores and indexes
-> claimant, Agent, staff, and operations runtime
```

The browser never connects directly to a provider database, object store, vector
index, model endpoint, or secret manager. Administrative records retain author,
reason, validation, approval when required, publication state, effective time,
previous version, and rollback target. Secret values remain in an approved secret
manager; the Control Plane stores and displays only references and safe connection
status.

## How the Agent Uses Data

The Agent receives a bounded context assembled by application services:

- the current Claim State snapshot;
- active claim-family and conditional branches, current-action field requirements,
  and allowed registered fields;
- lifecycle and purpose-relevant WorkItems;
- a compact session summary and only necessary recent messages;
- authorised structured policy or history results;
- relevant knowledge chunks with citations and limitations;
- permitted tool results;
- allowed action, tool, staff-capability, policy, and model-profile metadata needed to
  constrain the turn.

The Agent must not receive complete customer histories, raw provider payloads,
unnecessary evidence objects, secrets, internal infrastructure identifiers, or
unbounded conversation history. The model returns an `AgentProposal`; Runtime separately
builds an `ExecutionPlan`, executes authorised tools, and records `TurnResult`. These
objects cannot share mutable state that obscures proposed, approved, and completed work.

The provider-neutral model API implementation is tracked separately by issue #204, while
the Week 4 Agent and Gateway delivery slices are tracked by issues #233 and #234.

## Evaluation Requirements

Each implemented profile must pass the same behavioural contracts for:

- ownership and customer isolation;
- optimistic revision checks and idempotency;
- claimant, shared, and staff-only projections;
- evidence provenance and protected object references;
- session resume without stale Claim State replacement;
- retrieval source, version, access, and citation preservation;
- unavailable, timeout, malformed, and partial provider responses; and
- prevention of mixed-provider reads and writes.

Model profiles and Agent Runtime must additionally be evaluated for strict-schema and
tool capability, refusal and incomplete output, qualified fallback, privacy scope,
proposal overreach, unknown external outcomes, staff read-versus-execute authority, and
the full trajectory from proposal through actual state effect.

The dynamic FNOL information model must additionally be evaluated for claim-family and
conditional branch activation, irrelevant-question avoidance, required-now versus
candidate selection, correction of a proposed branch, preservation of field provenance,
and rejection of unregistered fields and tags.

RAG evaluation must additionally measure retrieval relevance, citation support,
correct policy version and jurisdiction, safe refusal when evidence is
insufficient, and comparison with a non-RAG model baseline.

## Open Decisions

- Which profile will be the first deployed MVP profile.
- Which Cloudflare, MongoDB, and AWS services are available and approved.
- Northwind data schemas, matching keys, permissions, retention, residency,
  encryption, backup, and deletion requirements.
- Which customer policy and claim-history fields may be shown to claimants.
- Which Control Plane roles, approval levels, and publication workflow Northwind will
  authorise.
- Which field, tag, and branch definitions belong in the MVP and which changes require
  a code-level schema migration rather than configuration publication.
- Whether evidence extraction and embeddings run inside the selected provider
  profile or through a separately approved external processing boundary.
- Which model evaluation dataset is sufficient before fine-tuning is considered.
- Which model profiles, privacy classes, capability thresholds, fallback groups, and
  evaluation validity periods Northwind will approve for each Agent purpose.
