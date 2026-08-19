# Day 5 Policy / History Review Validation

## Purpose

This runbook is the `jxu316-arch` validation slice for Issue #147. It
demonstrates the provider-neutral mapping, persistence, professional-review
record, and staff write-back chain built by Issues #108, #126, and #136.

It does not replace the API / AWS adapter-boundary check owned by
`liyang6620`, and it does not claim the external timeout/unavailable fallback
owned by Issue #134 is complete before that dependency lands.

## Automated demonstration

Run the presentation validation test:

```text
python -m pytest tests/fixtures/presentation/test_policy_review_traceability.py -q
```

The full repository CI remains the merge gate. The focused command is only a
convenient Day 5 demonstration path.

## Demonstration path

The first presentation test walks one policy lookup through the full domain
chain:

1. Create a synthetic working claim at revision 1.
2. Receive a synthetic provider payload containing allow-listed policy facts
   plus deliberately unsafe provider-only values:
   - `fraud_label`
   - `fraud_finding`
   - `risk_score`
   - `policy_conclusion`
   - `provider_internal_note`
3. Map only the provider-neutral policy facts, source provenance, retrieval
   timestamp, and explicit uncertainty.
4. Persist the retrieval record and the sourced professional-review signal.
5. Read the staff Workbench projection and show:
   - the review signal has reason codes;
   - the review signal has source references;
   - the matching provider-neutral retrieval record appears as source evidence;
   - none of the provider-only risk/fraud/conclusion keys appear anywhere in
     the Workbench response.
6. Submit a staff review decision with `If-Match: 1`.
7. Show that the stored decision preserves:
   - authenticated staff actor;
   - staff reason code;
   - staff summary;
   - the original review signal source references, even though the staff
     request did not repeat them.
8. Show that the claim advances to revision 2 while:
   - `fraud_signal` remains `none`;
   - workflow remains `collecting`;
   - the original retrieval and review-signal records are unchanged.

This demonstrates that retrieval evidence can request professional review but
cannot silently become a fraud finding, policy decision, or high-impact state
transition.

## Fail-closed adapter check

The second presentation test supplies policy/history payloads that contain
provider-only status/risk/conclusion fields but omit the required domain
reference (`policy_reference` or `history_reference`).

The adapter must reject both mappings through domain validation. It must not
manufacture a policy/history record or preserve the provider-only conclusion.
This is the local contract proof for the Issue #147 acceptance statement that
no policy or fraud conclusion appears without a source.

## What Issue #147 can claim from this slice

After this validation passes, the `jxu316-arch` portion can demonstrate:

- the adapter follows the allow-listed domain contract;
- every persisted professional-review signal has a source and a reason;
- source evidence remains traceable through staff write-back;
- provider-only fraud/risk/policy conclusions do not cross the adapter
  boundary;
- review persistence alone does not set fraud state or block/transition a
  claim;
- missing required source facts fail closed rather than creating an
  unsupported conclusion.

## Dependency still owned by Issue #134

Issue #147 also lists unavailable-data fallback in its overall deliverable.
The HTTP/service behaviour for successful retrieval, timeout, unavailable, and
retry states belongs to Issue #134 (`Connect handoff, retrieval, and fallback
APIs`) owned by `liyang6620`.

Until #134 lands, this validation slice intentionally does not fake an
unavailable provider response or invent an AWS/provider API. When #134 is
available, its fallback result should be added to the final Issue #147 Day 5
run by the API/AWS-boundary owner and checked against the same rule: failure
must not create an unsourced policy or fraud conclusion.
