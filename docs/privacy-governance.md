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

The matrix below is the authoritative implementation contract for the #917 children. Policy
Summary, Asset, and Claim asset snapshot behavior is executable. Profile, Identity Record,
Payment Destination, Participant, ContentsItem, and Evidence changes are implemented by their
own children, but their visibility and failure boundaries are no longer open design inputs.

| Class | Collection/minimisation purpose | Access and masking | Agent, RAG, and log rule | Audit, retention, deletion expectation |
| --- | --- | --- | --- | --- |
| Profile | Identify/contact the claimant and prefill permitted intake facts; collect only approved fields | Owner full; staff minimum task view | Purpose-limited Agent context only; no profile indexing or raw logs | Revision/audit on change; deactivate with account; erase or anonymise only through the governed account request after holds are resolved |
| Identity Record | Identity proof and verification only | Owner masked; identity-authorised role by task; protected value encrypted separately | Excluded by default from Agent, RAG, prompts, analytics, and logs | Revoke before purge; a hold keeps the protected reference inaccessible to ordinary reads; protected-store failure is fail-closed and does not create/update metadata |
| Payment Destination | Future approved settlement destination, never payment execution | Owner masked; payment-authorised staff masked; token/reference encrypted separately | Always excluded from Agent, RAG, prompts, analytics, and logs | Revoke before purge; referenced settlement/audit facts survive as opaque IDs; protected-store failure is fail-closed and produces no ordinary record |
| Policy Summary | Display and associate the minimum approved policy facts | Owner and claims staff bounded projection; provider internals hidden | Only approved policy facts may enter Agent context; never general RAG or raw logs | Soft-deactivate first; existing Claim snapshots remain immutable; inactive summaries cannot form new Asset or Claim associations |
| Asset Record | Reuse claimant-entered vehicle/property/contents details | Owner and authorised staff; no cross-account lookup | Only selected approved details enter Claim context; no asset corpus indexing or raw logs | Audit material changes; soft-deactivate first; delete when no hold/reference requires it |
| Claim asset snapshot | Prove the asset details used for one Claim revision | Owning claimant and authorised Workbench staff | Bounded approved details may follow Claim purpose; excluded from general RAG/logs | Immutable; Claim retention/hold applies; asset deletion never rewrites it |
| Dynamic Form | Establish source-backed FNOL facts | Claimant-safe and staff task projections | Active registered facts only; redact restricted sources from logs | Assertion/revision history retained with Claim; correct by superseding, not overwriting |
| Participant | Represent repeatable incident roles and contacts | Claimant minimum; staff task view; contact values masked unless the task and contact consent require them | Sensitive contacts excluded from RAG/logs and Agent unless current task requires them | Claim retention/hold applies; correction supersedes rather than overwrites provenance; relationship-aware deletion removes ordinary projections but preserves bounded audit identity |
| ContentsItem | Describe claimed items without implying coverage | Claimant and staff Claim projections; serial number masked outside the owning claimant or authorised staff task | Bounded active item context only; serial/value omitted unless current task requires it | Claim retention/hold applies; item and association history is immutable/superseding, not destructive update |
| Evidence | Support the report with protected files and metadata | Claimant-safe metadata; staff provenance; bytes through protected object boundary | Extracted proposals only after controls; bytes/storage keys never in RAG or logs | Claim retention/hold applies; metadata tombstone and object/index deletion must converge before purge is reported complete |

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

## Retention, deletion, and residency

Northwind has not supplied a production retention duration, residency commitment, or legal-hold
schedule. The prototype therefore performs no time-based automatic purge and makes no production
compliance claim. This missing duration does not leave a child implementation decision open: every
child uses the following lifecycle contract until an authorised configuration replaces it.

- `active` records may be read only through their role and purpose projection.
- Deactivation or revocation blocks new use immediately but preserves immutable Claim snapshots,
  audit facts, and already-authorised external-operation provenance.
- A deletion request marks the subject `deletion_pending`. A record with a documented hold remains
  inaccessible to ordinary reads and moves to `held`, never falsely to `deleted`.
- Without a hold, deletion removes ordinary and protected values plus derived object/index copies,
  then records a bounded tombstone containing subject ID, actor, reason, time, and outcome. A child
  must not report completion while any configured store returns an unknown or failed result.
- Claim-owned Participant, ContentsItem, Evidence, mitigation, association, and snapshot records
  follow the Claim hold and deletion decision. Deleting an account Asset or Policy Summary never
  rewrites a retained Claim snapshot.
- Adapter conformance requires Fixture and normal persistence to return the same lifecycle,
  revision, idempotency, masking, and failure semantics. Protected-store unavailable or unknown
  outcomes fail closed with no metadata-only partial record.

Production duration, backup expiry, region, recovery point, and provider-retention values remain
deployment-governance inputs. They do not permit a child to invent a different lifecycle or expose
data while those values are unknown.

## MinIO and Knowledge Boundaries

The local MVP may use MinIO for protected evidence bytes and for the governed
synthetic knowledge corpus when the `local_mvp` profile is explicitly selected.
The `northwind-knowledge` bucket contains synthetic policy wording and indexed
chunks; it is not a production customer-data store.

Knowledge retrieval must use the manifest and validated ingestion state. A raw
bucket listing is not proof of publication, applicability, or safe retrieval.
The application must fail closed when the source, checksum, index, or ingestion
state is missing or inconsistent.

## Audit and deployment decisions

Material retrievals, disclosures, consent changes, provider outcomes,
configuration publications, staff decisions, and privacy-relevant errors must
retain source references, actor, purpose or reason, time, and outcome according
to the existing audit contract.

The following production deployment values are owned by the governance and Control Plane process.
They do not alter the child-record lifecycle, masking, or fail-closed rules above:

- production identity and access-review model;
- consent wording and notice review;
- retention, deletion, and anonymisation policy;
- encryption, backup, recovery, and residency requirements;
- provider training, logging, and regional-retention terms; and
- incident response and privacy-request handling.

Until those decisions are approved and verified, the system remains prototype-
only and uses synthetic data.
