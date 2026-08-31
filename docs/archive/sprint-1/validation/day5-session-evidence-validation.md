# Day 5 session and evidence validation

Issue: #144

This validation covers the `jxu316-arch` ownership slice: session recovery and revision behaviour while a persisted evidence record remains attached to the same claim.

## Demonstration path

Run `tests/fixtures/presentation/test_session_evidence_restore.py`.

The executable scenario proves:

1. A claimant creates one working claim at revision 1.
2. The claimant requests an image-evidence upload, advancing the claim to revision 2.
3. Upload completion is accepted at revision 3 and the file enters `processing`.
4. Completed processing records the extracted facts at revision 4, moves the file to `ready`, and leaves the facts `proposed`.
5. The active interaction session is paused and the same claim advances to revision 5.
6. A new claimant session resumes the same claim at revision 6.
7. The evidence record keeps the same `evidence_id`, state, source, metadata, and internal provenance across the session boundary.
8. The proposed facts survive the session boundary as proposals, with the same value, status, and source references.
9. The claimant evidence projection still omits internal provenance.
10. The staff Workbench still sees the persisted provenance needed for operational traceability.
11. The claim has exactly one active claimant session after resume and no duplicate working claim is created.

## Evidence visibility boundary

Claimant-visible evidence retains safe operational fields such as status, file status, source, filename, media type, and size. Internal storage provenance remains excluded from the claimant projection.

The staff Workbench reads the same underlying evidence record and may see internal provenance, including the mock storage key, upload checksum, and processing state.

Resume must not copy, replace, or re-create the evidence record merely because a new interaction session is created, and it must not decide a proposed fact on the claimant's behalf.

## Revision evidence

The presentation fixture uses one authoritative `WorkingClaim.revision` lineage:

`1 create -> 2 request upload -> 3 accept upload -> 4 complete processing -> 5 pause -> 6 resume`

The evidence record and the proposed facts remain unchanged between revisions 4 and 6; only the claim/session lifecycle advances.

## Team boundary

`jxu316-arch` validates session restore and revision behaviour here.

The evidence lifecycle itself is owned by `bdfa123`: PR #166 made accepted upload completion return `202` with `processing`, and PR #167 / Issue #120 owns the processing-completion transition that produces proposed facts and moves the file to `ready`. This PR is based on that lifecycle rather than restating it, and does not implement or replace Issue #139.

When Issue #139 reconciles the evidence lifecycle, mock storage, and path fixtures, rerun this validation against that result.
