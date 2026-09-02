# Policy and Claim-History Retrieval Contract

## Purpose

This document defines the boundary between provider responses and Northwind's structured
policy and claim-history domain records. It is separate from knowledge-document RAG:

- structured retrieval answers which authorised policy or history record belongs to a
  customer or claim; and
- RAG retrieves approved wording, legislation, guidance, or procedures with citations.

Neither path independently authorises coverage, fraud, liability, approval, or rejection.

## Tool Registry Mapping

The target Tool Registry uses these provider-neutral names rather than provider SDK
methods or private adapter names:

| Tool | Purpose | Result boundary |
| --- | --- | --- |
| `knowledge.search` | Retrieve approved wording, legislation, guidance, or procedures after authority and applicability filtering | Returns exact source version, section citations, limitations, and relevance evidence; it does not identify the claimant's policy |
| `policy.lookup` | Query the authorised structured policy record associated with the current claimant or Claim | Returns only allow-listed policy facts and matching limitations; it does not make a coverage decision |
| `claim_history.lookup` | Query authorised historical Claim facts for the current customer and permitted purpose | Returns only allow-listed history facts and limitations; it does not determine fraud or lower service priority |

Each request retains tool version, purpose, actor and Claim scope, source references,
required permission, bounded arguments, and result identity. The Model may request a
tool, but Runtime validates and executes it. A successful call proves only the mapped
result returned at that time.

The current API routes and adapters retain their existing compatibility names until the
Tool Registry, Runtime requests, persistence, fixtures, and contract tests migrate
together. This mapping does not introduce a new HTTP route or claim current runtime
support for the target tool identifiers.

The current deterministic message path may execute a bounded legacy `policy_history`
proposal for policy or claim-history lookup. Runtime validates the claim scope and
allow-listed purpose before calling the adapter, persists only the mapped retrieval
record, and reuses an existing record for the same claim-scoped reference. The model
gateway path still rejects tool requests until model-tool capability is explicitly
enabled and verified.

## Provider Boundary

`ProviderLookupEnvelope` is an internal adapter input. It may contain provider-specific
transport fields but must not enter shared Claim State, model context, audit summaries,
or public responses as an untyped payload.

Adapters map allow-listed facts into:

- `PolicyRetrievalRecord`; or
- `ClaimHistoryRetrievalRecord`.

Unknown fields are discarded rather than copied into a generic metadata object.

## Provenance

Every mapped record retains:

- a Northwind-owned retrieval ID;
- the parent claim ID;
- retrieval kind;
- source system and opaque source reference;
- retrieval time;
- typed provider-neutral facts;
- explicit limitations or uncertainty; and
- the visibility and authority required to use the result.

A source is evidence, not decision authority. A successful provider response proves only
what the mapped source returned at that time.

## Allow-listed Policy Facts

The contract may map verified fields such as:

- policy reference;
- customer-policy match result;
- product and status;
- effective dates;
- schedule and endorsement references;
- excess amount and currency; and
- coverage-section identifiers.

Policy wording excerpts belong to the knowledge and citation contract, not inside a
structured policy record. Missing customer matching or applicability remains an explicit
limitation.

## Allow-listed Claim-History Facts

The contract may map verified fields such as:

- history reference;
- incident type;
- occurrence time;
- status; and
- recorded outcome.

Provider-only risk scores, fraud labels, demographic attributes, internal notes,
accounting fields, infrastructure identifiers, and unsupported conclusions are not
mapped.

## Persistence and Review Signals

A retrieval bundle contains one mapped record and zero or more supported review signals
derived only from explicit mapped uncertainty. The bundle is persisted atomically.

A review signal retains:

- stable signal and parent claim identities;
- professional-review type and supported reason code;
- source references including the retrieval record;
- a bounded staff-facing summary; and
- lifecycle and audit timestamps.

No uncertainty means no retrieval-derived signal. Discarded provider fields cannot create
a signal because they never cross the adapter boundary.

Saving retrieval evidence does not advance Working Claim revision, change workflow,
approve or reject a claim, set a fraud conclusion, or block unrelated progress. A later
staff decision is a separate, revision-aware record.

## Staff Review and Write-back

- Retrieval and signal records are immutable evidence.
- Staff see the provider-neutral record and source references required for review.
- A staff decision retains actor, decision, reason, summary, and source-backed evidence
  separately from the original retrieval uncertainty.
- Source references that caused the review cannot be silently omitted from the decision.
- Material write-back uses current Working Claim revision and produces an appropriate
  claimant-safe update.
- High-impact state changes require their own authorised contract and cannot be implied by
  resolving a signal.

## API and Visibility

Raw provider payloads, provider scores, infrastructure identifiers, internal signals,
and other customers' history never appear in claimant responses. A claimant-facing
projection may expose approved customer-relevant facts, citations, or plain-language
limitations only when the API and authority contract permit it.

Provider unavailable, timeout, no-match, malformed, and access-denied outcomes are
limitations, not evidence records containing invented facts. They preserve claim progress
and produce bounded errors or professional follow-up as required.

## Conformance

Every provider adapter must pass the same mapping, discarded-field, provenance,
idempotency, visibility, unavailable-provider, atomic persistence, and staff write-back
contract tests. A fixture result is labelled as a fixture and cannot be reported as a
confirmed Northwind, Cloudflare, MongoDB, or AWS result.
