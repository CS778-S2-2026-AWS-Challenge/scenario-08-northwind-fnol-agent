# Day 5 staff revision and projection validation

Issue: #149

This validation covers the `jxu316-arch` ownership slice: an independent check that staff review write-back uses the current `WorkingClaim.revision` and that internal review material does not leak into the claimant projection.

## Demonstration path

Run `tests/fixtures/presentation/test_staff_revision_projection.py`.

The executable scenario proves:

1. A claimant creates one working claim at revision 1.
2. A sourced policy retrieval with explicit uncertainty creates a staff-only professional-review signal without changing the claim revision.
3. The staff Workbench can see the signal, reason code, source references, and source evidence.
4. A staff decision using `If-Match: 1` succeeds and advances the authoritative claim to revision 2.
5. The persisted decision records the staff actor, staff reason, result summary, and source-backed evidence references.
6. The underlying retrieval and review-signal records remain unchanged after write-back.
7. The claimant projection advances to revision 2 but still excludes internal signals, retrieval records, signal decisions, fraud state, staff reason codes, and staff-only summary text.
8. A later staff decision using stale `If-Match: 1` is rejected with `REVISION_CONFLICT` and does not create a second stored decision.

## Revision rule

Staff review write-back shares the same `WorkingClaim.revision` used by claimant and persistence flows. There is no separate signal or staff-action concurrency counter.

The validation therefore checks both sides of the boundary:

- current revision write succeeds and advances the claim once;
- stale revision write fails without a partial persistence mutation.

## Projection boundary

The staff Workbench receives review-only source evidence needed for professional handling. The claimant `GET /api/v1/claims/{claim_id}` projection must not expose that internal review material merely because a staff action advanced the parent claim revision.

## Team boundary

`jxu316-arch` performs the independent revision/persistence check here.

Issue #138 and the remaining Issue #149 work are owned by `LLL263`: staff assignment, full review/resolution demonstration, and claimant-safe update integration. This validation does not implement or replace #138. After #138 lands, rerun this test against the reconciled branch before Issue #149 is closed.
