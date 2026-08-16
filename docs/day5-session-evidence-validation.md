# Day 5 session and evidence validation

Issue: #144

This validation covers the `jxu316-arch` ownership slice: session recovery and revision behaviour while a persisted evidence record remains attached to the same claim.

## Demonstration path

Run `tests/fixtures/presentation/test_session_evidence_restore.py`.

The executable scenario proves:

1. A claimant creates one working claim at revision 1.
2. The claimant requests an image-evidence upload, advancing the claim to revision 2.
3. Upload completion stores the evidence as `received` / `ready` at revision 3.
4. The active interaction session is paused and the same claim advances to revision 4.
5. A new claimant session resumes the same claim at revision 5.
6. The evidence record keeps the same `evidence_id`, state, source, metadata, and internal provenance across the session boundary.
7. The claimant evidence projection still omits internal provenance.
8. The staff Workbench still sees the persisted provenance needed for operational traceability.
9. The claim has exactly one active claimant session after resume and no duplicate working claim is created.

## Evidence visibility boundary

Claimant-visible evidence retains safe operational fields such as status, file status, source, filename, media type, and size. Internal storage provenance remains excluded from the claimant projection.

The staff Workbench reads the same underlying evidence record and may see internal provenance, including the mock storage key, upload checksum, and proposed extraction state.

Resume must not copy, replace, or re-create the evidence record merely because a new interaction session is created.

## Revision evidence

The presentation fixture uses one authoritative `WorkingClaim.revision` lineage:

`1 create -> 2 request upload -> 3 complete upload -> 4 pause -> 5 resume`

The evidence record remains unchanged between revisions 3 and 5; only the claim/session lifecycle advances.

## Team boundary

`jxu316-arch` validates session restore and revision behaviour here.

Issue #139 and the independent evidence-state/source/visibility check remain owned by `bdfa123`. When #139 lands, this validation should be rerun against the reconciled evidence fixture service. This PR does not implement or replace #139.
