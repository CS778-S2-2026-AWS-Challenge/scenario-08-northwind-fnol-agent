# Policy and History Mapping Boundary

## Purpose

Issue #108 establishes the provider-to-domain mapping contract for policy and
claim-history retrieval. It does not confirm an AWS service, provider schema,
permission, table, index, or production integration.

The mapping boundary is intentionally split into two layers:

1. `ProviderLookupEnvelope` is an internal adapter input. Its `payload` may
   contain provider-specific transport fields and must not cross into shared
   Claim State or a public API response.
2. `PolicyRetrievalRecord` and `ClaimHistoryRetrievalRecord` are
   provider-neutral domain records containing only allow-listed facts,
   provenance, retrieval time, and explicit uncertainty.

## Domain provenance

Every mapped retrieval record contains:

- an opaque `retrieval_id` owned by Northwind;
- the parent `claim_id`;
- the retrieval kind (`policy` or `claim_history`);
- `source.system`, naming the adapter/provider boundary;
- `source.reference`, an opaque source record reference;
- `source.retrieved_at`, recording when the lookup result was obtained;
- typed provider-neutral facts;
- zero or more uncertainty entries containing a code and bounded detail.

A retrieval source is evidence, not decision authority. Policy interpretation,
history matching, coverage decisions, and professional-review signals remain
subject to the authority rules in the SPEC.

## Allow-listed mapping

`backend/adapters/policy_history.py` copies only the fields required by the
provider-neutral domain models. Unknown provider data is discarded rather than
stored inside an untyped metadata object.

The current synthetic policy example maps:

- policy reference;
- product and status;
- effective dates;
- excess amount and currency;
- coverage-section identifiers.

The current synthetic history example maps:

- history reference;
- incident type;
- occurrence time;
- status;
- outcome.

Provider-only notes, risk scores, fraud labels, AWS/storage identifiers, and
other raw payload fields are deliberately not mapped.

## Public API boundary

Issue #108 does not add retrieval records to `ClaimantClaim` or another
claimant response model. Raw provider payloads therefore remain behind the
adapter boundary. A later public projection may expose customer-relevant,
contract-approved facts or uncertainty, but must never return the adapter
`payload` or provider-only scoring/internal metadata.

## Relationship to later work

- Issue #107 owns verification of actual AWS access, schemas, permissions, API
  boundaries, and fallbacks. The synthetic envelope in #108 must not be read as
  a statement of available AWS capability.
- Issue #126 owns persistence of retrieval records, evidence provenance, and
  supported professional-review signal mappings. It should reuse these domain
  records rather than introduce a second provider-specific state model.
