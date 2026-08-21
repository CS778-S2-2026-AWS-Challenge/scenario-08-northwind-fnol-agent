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
   that queue reads persisted claim state rather than the notification. A retry
   and a repeated request reuse the same handoff and do not advance the claim a
   second time.
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

## Shared visibility boundary

`backend/services/evidence_handoff.py` contains `default_handoff_visibility()`:

```python
if evidence.source is EvidenceSource.CLAIMANT:
    return MessageVisibility.SHARED
return MessageVisibility.INTERNAL_ONLY
```

That record-level rule is now shared by the handoff service and the claimant
evidence projection through `backend/services/evidence_visibility.py`. Issue
#219 and PR #220 fixed the earlier claimant-list and aggregate leak. The
validation therefore seeds both claimant- and staff-sourced evidence, proves
the packet carries each with the appropriate visibility, and proves the
claimant list returns only the claimant-supplied record. Storage provenance is
still absent from every handoff-packet item.
