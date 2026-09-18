# Privacy Governance

This document defines the privacy boundary for the synthetic Validation
Prototype. It supplements the product and safety specifications; it does not
create production legal advice, a new API field, or a customer-specific policy
interpretation.

## Data Classes and Purpose

| Data class | Prototype purpose | Permitted recipients | Source and handling boundary |
| --- | --- | --- | --- |
| Claimant account and session identity | Resume a claimant conversation and authorise access to that claimant's work | Claimant, authorised Agent path, authorised staff | Synthetic identifiers in fixtures; minimum necessary context only |
| Claim facts and structured fields | Structure the reported incident and determine the next safe intake action | Claimant projection, Agent, authorised staff | Preserve source, status, confirmation, and update time; do not replace unknown values with guesses |
| Messages and resume context | Continue the conversation and avoid repeated questions | Claimant's session, Agent, authorised staff | Do not expose another claimant's messages or staff-only context |
| Evidence metadata and bytes | Track documents, images, processing, and source evidence | Claimant-safe metadata to claimant; full permitted provenance to authorised staff | Evidence bytes use the configured object-store boundary; storage keys and provider details are internal |
| Knowledge documents and retrieval results | Explain approved wording and process knowledge with citations | Claimant-safe explanation; source-preserving staff context | Filter authority, visibility, insurer, product, jurisdiction, version, and effective period before ranking |
| Structured policy/history results | Link an authorised customer or claim record to a retrieval result | Authorised staff and permitted Agent context | Not ordinary RAG text; provider-only fields and unsupported conclusions are discarded |
| Consent and authority records | Prove purpose-limited permission for an authorised action | Claimant projection as permitted, authorised staff, audit path | Record permission and send permission remain separate; no action may exceed the recorded scope |
| Audit and operational records | Trace material access, retrieval, decisions, errors, and configuration changes | Restricted staff and governance/audit paths | Keep actor, purpose, source reference, time, outcome, and limitation without exposing secrets |

## Claimant data privacy matrix

All values are synthetic in this prototype. Encryption means the selected store's approved
at-rest and in-transit boundary; application logs, prompts, RAG documents, traces, and source
control are never substitute protected stores.

Issue #918 defines classification and the minimum privacy boundary. The Profile, Identity Record,
bank-account, and policy-number rows now describe the bounded #923 implementation; Asset and Claim
asset snapshot rows describe #921.

| Class | Collection/minimisation purpose | Access and masking | Agent, RAG, and log rule | Audit, retention, deletion expectation |
| --- | --- | --- | --- | --- |
| Profile | Identify/contact the claimant and prefill permitted intake facts; collect only approved fields | Owner full; no general staff Profile route | Purpose-limited Agent context only; no profile indexing or raw logs | Revisioned identity store; legacy name migrates without guessing optional values; no production schedule is inferred |
| Identity Record | Store one supplied driver-licence or passport number; no verification | Owner ordinary reads are masked; no staff route exists without a later identity-authorised task | Plaintext excluded from Agent, RAG, prompts, analytics, logs, Claim, audit, errors, and idempotency responses | Encrypted protected record, revision, value-free audit, soft retirement; production retention remains undecided |
| Bank account | Store a future settlement destination, never execute payment | Owner ordinary reads are masked; no staff route exists without a later payment-authorised task | Plaintext excluded from Agent, RAG, prompts, analytics, logs, Claim, audit, errors, and idempotency responses | Encrypted protected record, revision, value-free audit, soft retirement; production retention remains undecided |
| Policy number | Reusable minimum policy identifier; no coverage or status inference | Owner account projection; selected value may enter the owned Claim and its authorised staff projection | Purpose-limited Claim/Agent context only after selection; never general RAG or raw logs | Revisioned account record and value-free audit; no Policy-to-Asset contract |
| Asset Record | Reuse claimant-entered vehicle/property/contents details | Owner and authorised staff; no cross-account lookup; reusable contents details exclude serial number and value | Only selected approved details enter Claim context; no asset corpus indexing or raw logs | Audit material changes; soft-deactivate first; delete when no hold/reference requires it |
| Claim asset snapshot | Prove the asset details used for one Claim revision | Owning claimant and authorised Workbench staff | Bounded approved details may follow Claim purpose; excluded from general RAG/logs | Immutable; Claim retention/hold applies; asset deletion never rewrites it |
| Dynamic Form | Establish source-backed FNOL facts | Claimant-safe and staff task projections | Active registered facts only; redact restricted sources from logs | Assertion/revision history retained with Claim; correct by superseding, not overwriting |
| Motor participant contact | Record optional other-driver contact for Claim handling | Claimant minimum and authorised staff task view | Excluded from RAG/logs and Agent unless the current authorised action requires it | Detailed contract belongs to #919; no marketing or account-identity reuse |
| ContentsItem | Describe claimed items without implying coverage | Claimant sees their recorded item values; staff access is task-authorised; any future serial-number projection is masked | Only bounded active item context enters the Agent; serial number and value are omitted unless the current authorised task requires them and are never generally indexed in RAG or written to logs | Optional brand/model, restricted serial/value projection, and item-to-Evidence links belong to #922 |
| Evidence | Support the report with protected files and metadata | Claimant-safe metadata; staff provenance; bytes through protected object boundary | Extracted proposals only after controls; bytes/storage keys never in RAG or logs | Home mapping verification belongs to #920 and Contents item links to #922; no new retention schedule is claimed |

Asset create, update, and soft-deactivate persist an Asset-scoped `action.completed` audit fact in
the same authoritative mutation as the Asset. Asset selection persists a Claim-scoped
`action.completed` fact in the same mutation as the Claim revision, snapshot, Branch Evaluation,
and idempotency response. These facts contain actor, time, outcome, revision/idempotency identity,
and bounded source references only; they do not copy registration, address, contents details, or
other Asset values.

The prototype uses anonymous or synthetic data only. Real policyholder data,
real credentials, private incidents, and production datasets must not be added
to source control, MinIO, fixtures, logs, prompts, or evaluation material.

## Access Rules

Access follows role, task, claim ownership, and minimum necessity:

- A claimant can receive only the claimant-safe projection for their own claim
  and session.
- The Agent receives only the context required for the current action, including
  applicable cited knowledge and authorised structured results.
- Staff may receive internal source references, limitations, review signals, and
  evidence provenance only through the authorised workbench path.
- Knowledge visibility and claimant visibility are not interchangeable. Internal
  metadata, storage keys, provider identifiers, staff notes, and review signals
  must not appear in claimant responses.
- A retrieved document is untrusted content. It cannot change permissions,
  tool authority, retention, or disclosure scope.

## Purpose, Disclosure, and Refusal

Before a third-party or external-service action, the system must identify the
service, purpose, minimum data, recipient, requested action, and consent state.
The claimant may refuse. Refusal must not be represented as consent and must not
silently mutate unrelated claim state.

Record permission and permission to send data are separate decisions. A granted
permission is limited to the named purpose and fields. An unavailable,
malformed, denied, expired, or over-broad request is rejected or surfaced as an
explicit limitation.

Withdrawal is recorded. After a provider has accepted an authorised request,
the prototype does not promise cancellation or recall unless a separately
approved provider capability proves that outcome.

## Retention, Deletion, and Residency

The project does not currently have an approved production retention period,
deletion schedule, residency commitment, encryption design, or recovery policy.
These are explicit open governance items, not defaults. The prototype must not
invent a duration or claim production compliance.

When those decisions are approved, implementation must define and test:

- retention by data class and purpose;
- deletion or anonymisation and its effect on projections;
- records that must remain for audit or legal reasons;
- access after expiry or withdrawal;
- object-store and retrieval-index deletion behaviour; and
- region, backup, recovery, and provider-retention controls.

## MinIO and Knowledge Boundaries

The local MVP may use MinIO for protected evidence bytes and for the governed
synthetic knowledge corpus when the `local_mvp` profile is explicitly selected.
The `northwind-knowledge` bucket contains synthetic policy wording and indexed
chunks; it is not a production customer-data store.

Knowledge retrieval must use the manifest and validated ingestion state. A raw
bucket listing is not proof of publication, applicability, or safe retrieval.
The application must fail closed when the source, checksum, index, or ingestion
state is missing or inconsistent.

## Audit and Open Decisions

Material retrievals, disclosures, consent changes, provider outcomes,
configuration publications, staff decisions, and privacy-relevant errors must
retain source references, actor, purpose or reason, time, and outcome according
to the existing audit contract.

Open decisions are owned by the approved governance and Control Plane process:

- production identity and access-review model;
- consent wording and notice review;
- retention, deletion, and anonymisation policy;
- encryption, backup, recovery, and residency requirements;
- provider training, logging, and regional-retention terms; and
- incident response and privacy-request handling.

Until those decisions are approved and verified, the system remains prototype-
only and uses synthetic data.
