# Day 5 evidence handoff packet check

Issue: #146

This is the `bdfa123` half of Issue #146: an independent check of the evidence
handoff packet. `liyang6620` owns the handoff API, priority, retry, and
fallback demonstration.

## Demonstration

Run `tests/fixtures/presentation/test_evidence_handoff_packet_check.py`.

1. **The packet carries the evidence context staff need.** A claim with an
   outstanding police report transfers with that record in `evidence_refs`, in
   `pending_items` as a named gap, and as a `HandoffEvidenceItem` carrying kind,
   status, file status, source, related fields, and the claimant's note.
2. **The packet classifies visibility by source.** A claimant-supplied record is
   `shared`; a record the claimant did not supply is `internal_only`. Storage
   provenance is not copied into the staff packet at all.
3. **A dispatch outage does not lose the packet or its context.** With the staff
   queue notification service refusing connections, the claimant still receives
   `201`, delivery reports `queued_locally`, the packet keeps every reference
   and gap, and staff still reach the handoff through the Workbench, because
   that queue reads persisted claim state rather than the notification.
4. **An urgent transfer is not blocked by outstanding intake.** A claim with
   evidence still pending transfers at urgent priority, and the outstanding item
   travels with the packet instead of holding the transfer.

## Acceptance

- **"Urgent handling is not blocked by ordinary intake."** Demonstrated in 4.
  The claim is in exactly the state that could have blocked it — evidence
  outstanding — and the transfer proceeds at urgent priority, visible in the
  staff queue at that priority.
- **"External failure does not lose the request or structured context."**
  Demonstrated in 3, against the real adapter boundary from Issue #123 rather
  than a stub.

## Finding: the visibility rule already exists

`backend/services/evidence_handoff.py` contains `default_handoff_visibility()`:

```python
if evidence.source is EvidenceSource.CLAIMANT:
    return MessageVisibility.SHARED
return MessageVisibility.INTERNAL_ONLY
```

That is a record-level visibility rule, applied by both the claimant support
handoff path and the professional-review path, and the packet has carried a
`visibility` field per evidence item since Issue #129.

`INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT` in
`docs/day4-evidence-visibility-defects.md` describes the claimant evidence list
returning records the claimant never supplied, and records it as needing a
domain decision about where visibility should live.

**That decision is narrower than the record suggests.** The repository already
has one rule, in one place, agreed by two callers. The gap is that
`GET /api/v1/claims/{claim_id}/evidence` does not apply it — not that the rule
needs inventing.

This is recorded rather than fixed, for the same reason as before: the claimant
evidence projection belongs to the evidence API stack, and Issue #146 is a
check. But whoever picks the defect up should start from
`default_handoff_visibility` rather than from a blank design.

Two things worth deciding at the same time:

- Whether `shared` and `internal_only` are the right classes for the claimant
  list, or whether it needs the third class the fixtures use
  (`claimant_visible`).
- Whether the `EvidenceWaitType` enum now on `main` (`claimant`,
  `external_agency`, `internal`) is meant to become that boundary, in which case
  it and `default_handoff_visibility` should not diverge.
