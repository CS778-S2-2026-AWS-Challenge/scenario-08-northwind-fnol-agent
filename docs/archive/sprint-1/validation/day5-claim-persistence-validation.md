# Day 5 claim persistence validation

Issue: #142

This validation covers the `jxu316-arch` ownership slice: independent repository and revision checks for claim creation and retry behaviour.

## Demonstration path

Run `tests/fixtures/presentation/test_claim_creation_persistence.py`.

The executable scenario proves:

1. The first claimant create request creates one working claim and one active session at revision 1.
2. An immediate replay with the same idempotency key and payload returns the same claim/session without creating another record.
3. A later claimant message advances the authoritative claim to revision 2.
4. Replaying the original create request after that newer write restores the same idempotent claim/session identity from persistence and projects the current revision-2 state; it does not create a duplicate or roll state back to revision 1.
5. Reusing the same idempotency key with a different create payload returns `IDEMPOTENCY_CONFLICT` and leaves the persisted claim unchanged.

## Persistence assertions

The validation checks repository state directly after each important step:

- `claim_count` remains one.
- The original `claim_id` remains authoritative.
- The original active `session_id` remains attached to that claim.
- The current persisted revision remains the newest revision when an earlier create request is retried.
- The idempotent create path reloads current claim/session state instead of replaying a stale frozen projection.

This distinguishes retry identity from stale-response replay: the idempotency record identifies the accepted claim/session pair, while the returned claimant projection reflects the current authoritative state.

## Team boundary

`jxu316-arch` independently validates repository and revision behaviour here.

The remaining Issue #142 ownership belongs to `liyang6620`: API routing, source traceability, AWS adapter behaviour, and fallback handling. This validation does not invent or substitute those external-adapter results.

After the #133/API-AWS dependency lands, rerun this persistence validation on the reconciled branch and combine the evidence with the adapter/fallback demonstration before Issue #142 is closed.
