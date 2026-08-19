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

## Retrieval persistence and professional-review signals

Issue #126 persists the provider-neutral retrieval records from #108 together
with any review-only signal derived from their explicit uncertainty.

A retrieval bundle contains one `PolicyRetrievalRecord` or
`ClaimHistoryRetrievalRecord` and zero or more `ReviewSignalRecord` values. The
fixture repository writes the bundle as one persistence operation and future
adapters must preserve the same all-or-nothing relationship.

A persisted review signal contains:

- a stable `signal_id`;
- the parent `claim_id`;
- `review_type=professional_review`;
- a supported signal code;
- one or more `source_refs`, including the retrieval record that produced it;
- one or more reason codes copied from explicit retrieval uncertainty;
- a bounded staff-facing summary;
- the retrieval timestamp used as the signal creation time.

The current supported mappings are deliberately narrow:

- policy retrieval uncertainty -> `POLICY_RETRIEVAL_UNCERTAINTY`;
- claim-history retrieval uncertainty ->
  `CLAIM_HISTORY_RETRIEVAL_UNCERTAINTY`.

No uncertainty means no review signal. Provider-only risk scores, fraud labels,
notes, or other discarded raw payload fields cannot create a signal because
they never cross the #108 mapping boundary.

Retrieval persistence is evidence/audit persistence, not a material Claim State
write. Saving a retrieval bundle does not increment `WorkingClaim.revision`,
change workflow state, set `fraud_signal`, approve or reject a claim, or block a
claim. Any later staff decision about a persisted signal remains an authorised
professional action and belongs to the Day 4 integration path.

Retrieval and review records are claim/customer scoped. Repeating an identical
retrieval bundle is idempotent; attempting to reuse a retrieval or signal ID
for different content is a persistence conflict. Every persisted review signal
must identify its parent retrieval record in `source_refs`.

## Staff review integration and source-preserving write-back

Issue #136 connects the persisted #126 review records to the existing staff
workbench and revision-aware staff write-back boundary without redefining the
general staff-action contract.

- A persisted `ReviewSignalRecord` is projected only to the staff workbench.
  Its `source_refs` remain intact and the workbench adds the provider-neutral
  retrieval record referenced by the retrieval ID as `source_evidence`.
- Retrieval and review-signal source records are immutable evidence. Staff
  decisions are persisted separately as `SignalDecisionRecord` values and do
  not rewrite the retrieval facts, uncertainty, signal reason codes, or source
  provenance.
- When staff decide a persisted review signal, the signal's original
  `source_refs` are automatically unioned into the decision's `evidence_refs`
  before persistence. Staff may add evidence references, but cannot
  accidentally omit the source evidence that caused the review signal.
- The persisted decision retains the authenticated staff actor, the staff's
  decision, staff reason codes, and staff summary. These fields remain distinct
  from the original retrieval uncertainty and original review-signal reasons.
- A staff review decision is a revision-aware shared write: it uses the current
  `WorkingClaim.revision` through `If-Match`, advances that parent revision once,
  and persists through the existing `save_staff_mutation(...)` boundary.
- The review decision itself does not set `fraud_signal`, change workflow state,
  approve or reject the claim, or block progression. Any such high-impact state
  transition requires its own authorised contract and reasoned staff action.
- Signals that are not persisted #126 retrieval-review signals continue through
  the pre-existing legacy signal-decision service. Issue #136 therefore adds
  the retrieval integration path without replacing Agent/message review
  behaviour.
- Issue #109 owns the general staff-action and state-write-back contract/fixtures.
  Issue #136 consumes that revisioned persistence boundary rather than
  redefining it.

## Public API boundary

Issue #108 and #126 do not add retrieval records to `ClaimantClaim` or another
claimant response model. Raw provider payloads therefore remain behind the
adapter boundary. A later public projection may expose customer-relevant,
contract-approved facts or uncertainty, but must never return the adapter
`payload` or provider-only scoring/internal metadata.

## Relationship to later work

- Issue #107 owns verification of actual AWS access, schemas, permissions, API
  boundaries, and fallbacks. The synthetic envelope in #108 must not be read as
  a statement of available AWS capability.
- Issue #108 owns provider-neutral retrieval mapping and intentionally excludes
  persistence and professional-review signal generation.
- Issue #126 owns persistence of retrieval records, evidence provenance,
  uncertainty, and supported review-only signal mappings.
- Issue #136 owns connecting these persisted retrieval/review records into the
  staff workbench, staff review decisions, and revision-aware integration flow.
