# Day 5 Policy / History Review Validation

## Purpose

This runbook is the `jxu316-arch` validation slice for Issue #147. It
demonstrates the provider-neutral mapping, persistence, professional-review
record, unavailable-data boundary, and staff write-back chain.

The original version of this runbook predated completion of Issue #134 and
therefore described timeout/unavailable behaviour as pending. That statement is
no longer current. Issue #134 is completed, the retrieval API failure contract
is merged on `main`, and PR #231 supplies the remaining connected
retrieval-to-handoff outage/recovery regression. PR #231 is currently Draft
under the repository's newer PR policy until its exact-head local full gate is
recorded and the assigned API/adapter owner review is complete.

Nothing in this runbook claims a live AWS policy/history integration. Current
AWS capability remains `pending_confirmation`.

## Focused demonstrations

Provider-neutral source/authority traceability:

```text
python -m pytest tests/fixtures/presentation/test_policy_review_traceability.py -q
```

Retrieval API success, ambiguity, no-evidence, and unavailable behaviour:

```text
python -m pytest tests/test_retrieval_api.py -q
```

Connected retrieval + handoff degraded path after PR #231 is on the checked-out
branch:

```text
python -m pytest tests/test_connected_retrieval_handoff_fallback.py -q
```

The complete repository gate remains the merge requirement. Focused commands
are demonstration aids, not substitutes for `./scripts/check.ps1`.

## Source and authority path

The presentation validation walks a policy lookup through the domain boundary:

1. Create a synthetic working claim at a known revision.
2. Receive a synthetic provider payload containing allow-listed policy facts
   plus deliberately unsafe provider-only values such as `fraud_label`,
   `risk_score`, `policy_conclusion`, and provider notes.
3. Map only provider-neutral facts, source provenance, retrieval time, and
   explicit uncertainty.
4. Persist the retrieval record and a sourced professional-review signal when
   human judgment is required.
5. Read the Workbench projection and prove the review signal carries reason
   codes and source references while provider-only conclusion/risk fields do
   not cross the boundary.
6. Submit staff review with optimistic revision control.
7. Prove staff actor, reason, summary, and source references persist through
   write-back.
8. Prove the write-back does not silently create a fraud finding or provider
   policy decision.

This demonstrates the intended authority boundary: retrieval evidence can ask
for professional review but cannot become a high-impact policy/fraud decision
without a sourced, authorised staff action.

## Fail-closed mapping check

Provider payloads that omit required domain references are rejected rather
than turned into records. Provider-only status/risk/conclusion values are not a
substitute for a source.

The acceptance statement "no policy or fraud conclusion appears without a
source" is therefore enforced both at mapping time and at the review/write-back
boundary.

## Retrieval API unavailable-data contract

`tests/test_retrieval_api.py` now provides the merged Issue #134 behaviour that
this runbook previously marked as pending:

- sourced success returns provider-neutral facts plus source;
- ambiguity produces a sourced professional-review signal rather than an
  automatic coverage decision;
- no-evidence remains no-evidence;
- timeout/unavailable returns `facts=None`, `source=None`, and limitations;
- unavailable retrieval does not persist a retrieval record or review signal;
- claim-history retrieval is purpose-limited and cannot be expanded into fraud
  screening by caller-supplied provider fields.

An unavailable provider therefore cannot create an unsupported policy or fraud
conclusion.

## Connected degraded path — PR #231

PR #231 composes the existing retrieval and handoff boundaries on one real
application/repository/claim:

1. Persist confirmed claimant incident context.
2. Force policy retrieval timeout and prove it fails closed without facts,
   source, retrieval persistence, or review signal.
3. Force handoff dispatch outage on the same claim.
4. Prove the human-support request and structured transfer context are durable
   before notification and the API reports `queued_locally`.
5. Prove the Workbench sees one queued handoff and claimant projection does not
   leak provider timeout/internal details.
6. Replay with the same idempotency key and prove no duplicate handoff or
   revision advance.
7. Restore dispatch and prove delivery recovers on the same durable handoff.

The regression has green GitHub CI and an independent `bdfa123` approval on its
current code head. It is deliberately **not** represented as merged/current-main
evidence until the newer PR policy requirement is satisfied: exact-head
`./scripts/check.ps1` local PASS, current template metadata, assigned API/adapter
owner review, and merge.

## What Issue #147 can claim now

The technical evidence supports these statements:

- the adapter follows an allow-listed provider-neutral domain contract;
- persisted professional-review signals have sources and reasons;
- source evidence remains traceable through staff write-back;
- provider-only fraud/risk/policy conclusions do not cross the adapter/API
  boundary;
- missing source facts and unavailable providers fail closed;
- the claim remains available for safe human fallback instead of receiving a
  fabricated answer;
- durable handoff fallback/recovery is implemented in #231 but remains a
  pre-merge validation until its new local-gate/review requirements are met.

## Remaining closure boundary

Issue #147 should remain open until:

- PR #231 records an exact-head `./scripts/check.ps1` PASS under the current PR
  policy;
- the assigned API/AWS boundary owner (`liyang6620`) completes the independent
  check;
- PR #231 merges; and
- no live AWS/provider capability is claimed unless it is separately verified.
