# Claim Creation and Provider Adapter Boundary

## Purpose

This document defines the provider-neutral boundary for creating and routing a claim. It
separates authorised Northwind domain behaviour from fixture and configured external
services. It does not confirm a Northwind provider schema, cloud service, credential,
permission, or production connection.

## Current Capability Classes

| Capability | Meaning |
| --- | --- |
| Provider-neutral contract | Domain command and result are defined independently of a provider payload |
| Controlled creation path | Current Claim State, revision, idempotency, and authority are checked before invocation |
| Fixture adapter | Returns repeatable synthetic results labelled `fixture` |
| Configured provider adapter | May report `configured_service` only after its connection, authority, schema, and result mapping are verified |
| Unavailable capability | Preserves the working claim and returns the documented dependency limitation |

## Stable Create Contract

The creation service derives a provider-neutral command from the authorised Working
Claim. A claimant or route handler cannot submit provider keys, table names, external
schemas, or an unverified customer-supplied claim identifier as authority.

Every result contains:

- creation status such as `created`, `pending`, or `failed`;
- configured processing route, not a coverage or liability decision;
- claimant-visible next step;
- source class such as `fixture` or `configured_service`;
- provider reference and expected timing when available; and
- limitations required to interpret the result honestly.

When the accepted result is `created`, the same authoritative Claim compare-and-set also writes
`terminal_disposition.value=completed` with registered reason `CLAIM_CREATED`, the authorising
decision reference, the created external Claim reference, typed system actor, timestamp, and
resulting Claim revision. Workbench reads this record directly; it must not later infer completion
from `workflow_state=created` or adapter text. A `created` result without a stable external Claim
reference is a malformed dependency result and is not committed.

The public API remains unchanged when the active adapter changes.

Creation is one registered Claim action within a larger turn. A model may propose
`claim.prepare_creation` or `claim.create`, but Runtime must place an approved
`claim.create` ActionEnvelope in the `ExecutionPlan` before the adapter is called. The
adapter result becomes part of `TurnResult`; the response draft is corrected from that
real result before creation is described to the claimant.

## Authority, Revision, and Idempotency

- Required material facts and confirmations must satisfy the current controlled rule.
- Motor, home, and contents use one deterministic requirement resolver over their mutually
  exclusive registered family branch plus shared fields. Creation rejects any missing or
  unconfirmed `required_now` item and routes accepted commands as `standard_motor_intake`,
  `standard_home_intake`, or `standard_contents_intake`.
- Typed contents items satisfy the contents collection requirement only when at least one current
  item is confirmed. They are not flattened into the generic form or inferred from an empty
  `contents.items` string.
- Claim creation requires the current Working Claim revision and an authorised
  `claim.create` ActionEnvelope. During migration, the existing `CREATE_CLAIM` Agent
  Decision may satisfy this boundary only through an explicit, tested mapping to the new
  action contract.
- The provider-neutral operation identity and fingerprint enforce idempotency.
- An identical retry returns the accepted claim identity and current authorised
  projection; changed input under the same key is a conflict.
- Once a terminal disposition exists, a new Claim-creation attempt is an invalid transition;
  replay of the already accepted creation fingerprint still returns the original external result.
- Pending evidence remains recorded and is not silently discarded.
- Model output, severity, retrieval, or an adapter response cannot independently
  authorise creation or assessor routing.
- Assessor routing requires both a current Northwind rule/staff decision and a matching
  active claimant-consent record from the shared Working Claim. These are separate
  authorities and neither substitutes for the other.

## Failure Behaviour

Timeout, unavailable, malformed, access-denied, partial, and conflicting provider
responses preserve the working claim and return a bounded error or pending result. The
service must not report success, fabricate a reference, or fall through to a second data
runtime profile.

A timeout after submission may be `unknown_outcome`, not an ordinary failure. Runtime
must reconcile through the existing operation identity, idempotency key, or provider
reference before retrying. The claimant is told only the real known state and recovery
path; the system must not create a duplicate formal Claim because acknowledgement was
lost.

The provider-neutral external-task recovery matrix is:

| Failure | Delivery | Operation status | Recovery | Retryable |
| --- | --- | --- | --- | --- |
| `timeout` | `not_submitted` | `retryable_failure` | `retry_same_operation` | Yes |
| `timeout` | `submitted` | `unknown_outcome` | `reconcile_before_retry` | No |
| `unavailable` | Any | `retryable_failure` | `retry_same_operation` | Yes |
| `partial` | Any | `unknown_outcome` | `reconcile_before_retry` | No |
| `access_denied` | Any | `terminal_failure` | `review_required` | No |
| `malformed` | Any | `terminal_failure` | `review_required` | No |
| `conflicting` | Any | `terminal_failure` | `review_required` | No |

`unavailable` retains the controlled assessor contract: an unchanged attempt may retry with
the same operation identity even when the failed invocation reached the provider. This is not
permission to create a new operation or to retry automatically. `partial` records an observed
side effect whose completion is uncertain, so Runtime reconciles it before another attempt.
The `recovery` value determines both operation status and retryability; implementations must
reject combinations that disagree with this matrix.

The current assessor runtime remains a compatibility model. It records `prepared`,
`retryable_failure`, `terminal_failure`, and `accepted`, but it does not record delivery or
represent `unknown_outcome`, `partial`, or `conflicting`. The provider-neutral model is therefore
not a drop-in enum replacement. A later integration must supply trustworthy delivery evidence
before classifying a timeout as `submitted`; until that migration updates the assessor runtime,
API contract, persistence, and tests together, its documented timeout and unavailable behaviour
remains unchanged.

An explicitly configured fixture adapter may be used for controlled development. It is
not a silent production fallback and its result remains labelled `fixture`.

The vehicle-damage assessor simulation is a separate, explicitly non-live adapter for the
provider-neutral lifecycle. It consumes the bounded assessor request confirmed by Issue #416 and
returns delivery, operation status, failure code, recovery, retryability, and routing output as one
typed result. Its assigned and queued outcomes include a simulation acknowledgement and limitation;
its unavailable, pre-submission timeout, rejected, malformed, and partial-result scenarios remain
distinct. A partial simulated response is `unknown_outcome` and requires reconciliation before any
retry. The adapter never reports `configured_service` and is not wired into the claimant runtime by
this boundary; Issue #441 owns that end-to-end consumption.

## Routing and External Participants

Routing, assessor tasks, repair tasks, or another participant action require their own
provider-neutral command, result, authority, idempotency, visibility, and failure
contract. Claim creation does not automatically grant an external participant access to
the complete claim.

The current controlled assessor fixture requires `claimant_consent_ref` and validates the
record's service identity, requested action, granted status, and minimum permitted fields
before the adapter is called. The record must have been granted by the claimant linked to the
Working Claim; authorised-representative consent remains unsupported until that identity and
authority are modelled explicitly. The adapter supports deterministic assigned and queued
successes plus timeout, unavailable, access-denied, and malformed failures. A failure preserves
the current claim and never becomes an assignment. Timeout and unavailable are retryable with
the same operation identity; access-denied and malformed responses require review before another
attempt. Automatic retry counts remain unapproved.

The service reserves an immutable operation identity and full request fingerprint before
invocation. It records retryable failure, terminal failure, or provider acceptance separately
from Claim State. A changed retry is rejected even before any success, and a provider-accepted
result can be reconciled after a concurrent Claim revision advance without invoking a second
external task.

An accepted and assigned `P3-ASSESSOR` task can receive one later report through the installed
assessor adapter. The controlled adapter returns deterministic JSON marked `simulation_only`;
Runtime validates the task identity, provider acknowledgement, source class, source timestamp,
current Claim revision, and receipt idempotency before storing the bytes through the active
Evidence storage profile. The resulting `ExternalTaskResult` remains separate from the routing
acknowledgement, links to the task's immutable `assessment_report` Evidence, and records the Claim
revision used by the verification operation. Its initial checked state is `review_required`.
Receipt updates only the Claim's Evidence lifecycle projection; it cannot change material facts,
workflow, coverage, repair authority, or claimant-visible routing state. This path does not contact
or claim the existence of a production assessor provider.

The claimant experience uses two versioned public mutations. The first records a fixed,
task-specific consent scope; the second derives the current decision, consent, external claim,
requested action, and confirmed region from the shared Working Claim before invoking this
adapter. The action is projected only for a created controlled motor claim when no open handoff
or professional review has priority. The claimant client shows the participant, controlled
fixture provider label, purpose, shared-data summary, submission progress, assigned or queued
result, and bounded failure. It does not construct an internal adapter command or expose the raw
consent and authority references.

The target external-request lifecycle expands this boundary further. External coordination
separates capability discovery, request requirements,
preparation, request-type classification, consent and authority, submission, tracking,
response verification, Claim reconciliation, safe retry, cancellation, and failure
escalation. Each step uses the minimum disclosure and records its own result; a generic
external-service call cannot collapse these states.

## Runtime-profile Relationship

Cloudflare, MongoDB, AWS, and fixture data profiles are selected as complete, mutually
exclusive runtime configurations according to `docs/data-architecture.md`. The claims
system itself may remain a separately approved external integration, but its adapter
cannot expose provider details to the domain or use another data profile as a silent
fallback.

## Open Confirmations

Before a configured provider can be described as production-capable, verify endpoint and
identity, authorised matching keys, schema and null semantics, retry and timeout
behaviour, idempotency, service limits, ownership, visibility, retention, audit,
reconciliation, rollback, and operational support.
