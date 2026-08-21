from collections.abc import Iterable

from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceStatus,
    HandoffEvidenceItem,
    HandoffPacket,
    MessageVisibility,
)
from backend.services.evidence_visibility import default_evidence_visibility

PENDING_EVIDENCE_STATUSES = {
    EvidenceStatus.UNOFFICIAL,
    EvidenceStatus.INCOMPLETE,
    EvidenceStatus.PENDING_GENERATION,
}
PENDING_FILE_STATUSES = set(EvidenceFileStatus) - {
    EvidenceFileStatus.NOT_AVAILABLE,
    EvidenceFileStatus.READY,
}


def default_handoff_visibility(evidence: EvidenceRecord) -> MessageVisibility:
    """Apply the shared safe runtime default to a handoff evidence record."""

    return default_evidence_visibility(evidence.source)


def assemble_evidence_handoff_packet(
    packet: HandoffPacket,
    claim_id: str,
    evidence_records: Iterable[tuple[EvidenceRecord, MessageVisibility]],
) -> HandoffPacket:
    """Attach authoritative evidence state to a staff-only handoff packet."""

    records = list(evidence_records)
    if any(record.claim_id != claim_id for record, _ in records):
        raise ValueError('Every handoff evidence item must belong to the handoff claim.')
    evidence = [
        HandoffEvidenceItem(
            evidence_id=record.evidence_id,
            kind=record.kind,
            status=record.status,
            file_status=record.file_status,
            source=record.source,
            visibility=visibility,
            original_filename=record.original_filename,
            media_type=record.media_type,
            size_bytes=record.size_bytes,
            related_fields=record.related_fields,
            needed_for=record.needed_for,
            claimant_note=record.claimant_note,
        )
        for record, visibility in records
    ]
    evidence_refs = list(
        dict.fromkeys([*packet.evidence_refs, *(item.evidence_id for item in evidence)])
    )
    pending_items = list(
        dict.fromkeys(
            [
                *packet.pending_items,
                *(
                    item.evidence_id
                    for item in evidence
                    if item.status in PENDING_EVIDENCE_STATUSES
                    or item.file_status in PENDING_FILE_STATUSES
                ),
            ]
        )
    )
    conflicts = list(
        dict.fromkeys(
            [
                *packet.conflicts,
                *(
                    item.evidence_id
                    for item in evidence
                    if item.status is EvidenceStatus.INCONSISTENT
                ),
            ]
        )
    )
    return packet.model_copy(
        update={
            'evidence_refs': evidence_refs,
            'evidence': evidence,
            'pending_items': pending_items,
            'conflicts': conflicts,
        }
    )
