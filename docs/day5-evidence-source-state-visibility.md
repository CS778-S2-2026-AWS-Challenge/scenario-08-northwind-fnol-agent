# Day 5 evidence source, state, and visibility check

Issue: #144

This is the `bdfa123` half of Issue #144: an independent check of evidence
source, state, and visibility across a session change. `jxu316-arch` owns the
session recovery and revision half, delivered in PR #160.

## Why this uses a different scenario

PR #160 demonstrates recovery against a single claimant-uploaded image, which
is the right shape for revision behaviour. It cannot show whether resume
preserves *which source* a record came from, or whether the claimant and staff
boundary survives, because every record in it has the same source.

This check uses `AT-06-pending-evidence`, which holds three records from three
different sources:

| Evidence | Kind | Source |
| --- | --- | --- |
| `evd_fixture_at06_police` | `police_report` | `claimant` |
| `evd_fixture_at06_agency` | `agency_incident_record` | `external_system` |
| `evd_fixture_at06_internal` | `internal_policy_history` | `staff` |

## Demonstration

Run `tests/fixtures/presentation/test_evidence_source_state_visibility_on_resume.py`.

1. **The mixed-source set survives resume unchanged.** All three records are
   byte-identical either side of the session change, the three sources are still
   distinct, and the derived evidence state and summary recompute to the same
   values. Resume neither rewrote nor recreated a record.
2. **Internal provenance never reaches the claimant.** Each record carries an
   `internal_note`; none of the three appears in a claimant response before or
   after resume, while staff continue to receive all three.
3. **Resume does not widen the record-level visibility gap.** The set of records
   the claimant can see is identical before and after.

## Acceptance

Issue #144 acceptance conditions:

- **"The same claim resumes after a new session."** Covered by PR #160 and
  re-confirmed here: the claim keeps its identity, gains the new active session,
  and advances its revision.
- **"Saved evidence state and visibility remain intact."** Evidence state,
  summary, source, and internal provenance are all intact across resume, and the
  claimant-visible set is unchanged.

## Known limitation, recorded not hidden

`INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT` in
`docs/day4-evidence-visibility-defects.md` is open. `EvidenceRecord` has no
visibility field, so `GET /api/v1/claims/{claim_id}/evidence` returns every
persisted record, including the `staff` and `external_system` ones above.

That gap is **not** caused by resume and is not this issue's to fix — it belongs
to the evidence API and domain model. The distinction matters for reading this
evidence honestly: "visibility remains intact" here means the boundary is the
same before and after the session change, **not** that the boundary is correct.

The third test pins the leak deliberately. If the owning stack fixes it, that
test fails and points at the defect record, so the fix and this document are
updated together rather than one drifting from the other.

`main` now carries an `EvidenceWaitType` enum (`claimant`, `external_agency`,
`internal`) that is close to what the record-level boundary needs, but it is not
yet wired into the claimant projection.
