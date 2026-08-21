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
3. **Resume preserves the corrected role boundary.** Before and after resume,
   the claimant evidence list contains only the claimant-supplied police
   report and its claimant-safe aggregate reports one pending item. The staff
   projection contains all three authoritative records and reports three
   pending items.

## Acceptance

Issue #144 acceptance conditions:

- **"The same claim resumes after a new session."** Covered by PR #160 and
  re-confirmed here: the claim keeps its identity, gains the new active session,
  and advances its revision.
- **"Saved evidence state and visibility remain intact."** Evidence state,
  source, provenance, and the authoritative three-record set are unchanged
  across resume. The claimant-safe one-record projection and the staff-complete
  three-record projection also remain unchanged.

## Visibility boundary

Issue #219 and PR #220 resolved the earlier claimant evidence leak. The shared
visibility service now filters non-claimant records before the claimant list
and recomputes the claimant-facing aggregate from that filtered set. The
persisted Working Claim and Workbench retain the full aggregate. This validation
consumes that current contract and proves that starting a new session neither
narrows nor widens either role's projection.
