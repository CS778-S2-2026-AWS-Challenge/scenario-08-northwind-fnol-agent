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
- Raw evidence bytes do not belong in Claim State. Evidence metadata retains a
  protected object reference owned by the active adapter.
- RAG supports knowledge retrieval. It does not replace structured claim,
  policy, customer, or claim-history queries and does not authorise high-impact
  decisions.
- The Agent accesses data through application tools and services. It does not
  query a provider SDK, database collection, bucket, or vector index directly.

## Data Classes

| Data class | Examples | Canonical use | Agent access | Visibility |
| --- | --- | --- | --- | --- |
| Customer profile | identity reference, permitted contact details, communication preferences | Identify the authorised customer and adapt communication | Minimum fields required for the current task | Customer-scoped and authorised staff |
| Working Claim State | incident facts, form fields, independent claim attributes, workflow state, next action | Authoritative current FNOL record | Bounded current snapshot | Claimant-safe projection, shared fields, and staff-only fields are separated |
| Sessions and messages | complete messages, bounded session summary, unresolved questions, prior commitments | Resume interaction without replacing Claim State | Recent necessary messages and compact context only | Customer and staff according to message visibility |
| Evidence metadata | evidence ID, type, state, provenance, checksum, protected object reference | Track evidence lifecycle and source | Safe metadata and extracted proposals | Claimant-safe metadata; protected provenance for staff |
| Evidence objects | images, PDFs, police documents, audio if approved | Original submitted material | Only through authorised evidence tools | Protected object access |
| Extracted evidence facts | proposed vehicle damage, dates, document fields | Candidate facts derived from evidence | Proposals with source references | Never confirmed solely because a model extracted them |
| Customer policy records | policy reference, product, status, effective dates, schedule, endorsements | Determine which contract may apply to the customer | Structured, authorised lookup | Customer-safe facts and staff review according to authority |
| Claim history | previous claim references, dates, types, status, outcomes | Support continuity and bounded review signals | Structured, customer-scoped lookup | Staff by default; claimant projection requires an explicit contract |
| Knowledge documents | policy wording, legislation, industry guidance, approved procedures | Answer process and wording questions with citations | RAG retrieval with scope filters | Controlled by document authority and access metadata |
| Retrieval records | returned facts, citations, source, version, retrieval time, limitations | Preserve what evidence supported an answer or review | Current relevant result only | Customer-safe citation or staff evidence according to source |
| Handoffs and staff work | transfer packet, queue, owner, staff action, review decision | Preserve responsibility and professional decisions | Status and authorised result only | Internal details remain staff-only |
| Internal signals | ambiguity, conflicting evidence, review-required indicators | Route work for professional attention | Bounded reason and required action | Staff-only |
| Audit events | actor, action, authority check, revision, outcome, timestamp | Trace material changes | Not general model context | Restricted operational access |
| Evaluation data | synthetic conversations, expected actions, RAG relevance labels, corrected outputs | Compare models and verify Agent behaviour | Test and evaluation environments only | Synthetic or explicitly approved data |
| Operational telemetry | request IDs, latency, error class, token usage, retrieval metrics | Reliability and cost measurement | Aggregated metrics only | Restricted operational access |

## Logical Storage Responsibilities

The logical responsibilities stay stable even if one provider combines them
physically:

1. **Transactional store** holds customer references, Claim State, sessions,
   messages, evidence metadata, policy/history retrieval records, handoffs,
   staff actions, revisions, idempotency records, and audit events.
2. **Object store** holds original evidence and other large binary objects.
3. **Knowledge document store** holds approved source documents, parsed text,
   versions, authority metadata, and chunk records.
4. **Retrieval index** supports metadata-filtered keyword and vector search over
   knowledge chunks.
5. **Evaluation store** holds synthetic scenarios, expected results, model
   comparison results, and RAG evaluation evidence outside production records.

Physical co-location does not remove the logical visibility, retention,
ownership, or authority boundaries.

## Provider-neutral Ports

Application services depend on capability ports rather than one large provider
adapter:

```text
CustomerRepository
ClaimRepository
SessionRepository
EvidenceMetadataRepository
EvidenceObjectStore
PolicyDataSource
ClaimHistoryDataSource
KnowledgeDocumentStore
KnowledgeRetriever
HandoffRepository
AuditEventStore
```

The existing `PersistenceRepository` may be decomposed gradually. A migration
must preserve current ownership, revision, idempotency, projection, and audit
behaviour while the smaller ports are introduced.

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
one provider profile only
```

The selected profile must provide every required capability or fail startup
with an explicit configuration error. It must not obtain a missing capability
from a second profile without a separately approved architecture change.

| Profile | Candidate transactional store | Candidate object store | Candidate knowledge/index services | Status |
| --- | --- | --- | --- | --- |
| `fixture` | In-memory fixture repository | Synthetic object adapter | Deterministic fixture retriever | Available for controlled tests and demonstrations |
| `cloudflare` | D1 | R2 | R2 plus Vectorize and/or approved search service | Candidate; access and limits must be verified |
| `mongodb` | MongoDB Atlas collections | GridFS or an approved MongoDB-managed object pattern | Atlas Search and Atlas Vector Search | Candidate; topology and access must be verified |
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

Implementation is tracked by repository issue #203.

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
page
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
approved cloud-managed source
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

The source-management product is not fixed by this contract. Whatever product
is selected must support version history, access control, export or API access,
and a reliable ingestion trigger into the active data profile.

### RAG authority boundary

- Retrieval results are evidence, not coverage, fraud, liability, approval, or
  rejection decisions.
- Retrieval must filter insurer, jurisdiction, product, effective period,
  document authority, and visibility before similarity ranking.
- Answers must retain citations to the exact source version and section.
- Missing, conflicting, expired, or inapplicable evidence must be stated as a
  limitation and may require professional review.
- Prompt injection or instructions inside retrieved documents are untrusted
  content and must not alter system authority or tool permissions.

## How the Agent Uses Data

The Agent receives a bounded context assembled by application services:

- the current Claim State snapshot;
- unresolved questions and pending actions;
- a compact session summary and only necessary recent messages;
- authorised structured policy or history results;
- relevant knowledge chunks with citations and limitations; and
- permitted tool results.

The Agent must not receive complete customer histories, raw provider payloads,
unnecessary evidence objects, secrets, internal infrastructure identifiers, or
unbounded conversation history. Model output remains a proposal until existing
deterministic and staff authority checks permit the requested action.

The provider-neutral model API boundary is tracked separately by issue #204.

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

RAG evaluation must additionally measure retrieval relevance, citation support,
correct policy version and jurisdiction, safe refusal when evidence is
insufficient, and comparison with a non-RAG model baseline.

## Open Decisions

- Which profile will be the first deployed MVP profile.
- Which Cloudflare, MongoDB, and AWS services are available and approved.
- Northwind data schemas, matching keys, permissions, retention, residency,
  encryption, backup, and deletion requirements.
- Which customer policy and claim-history fields may be shown to claimants.
- Which cloud-managed product will own knowledge authoring and approval.
- Whether evidence extraction and embeddings run inside the selected provider
  profile or through a separately approved external processing boundary.
- Which model evaluation dataset is sufficient before fine-tuning is considered.
