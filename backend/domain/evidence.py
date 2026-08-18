from collections.abc import Sequence

from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceState,
    EvidenceStatus,
    EvidenceSummary,
)


def evidence_summary_for(records: Sequence[EvidenceRecord]) -> EvidenceSummary:
    received = 0
    pending = 0
    needs_attention = 0
    for record in records:
        if record.status is EvidenceStatus.PENDING_GENERATION or record.file_status in {
            EvidenceFileStatus.AWAITING_UPLOAD,
            EvidenceFileStatus.UPLOADING,
            EvidenceFileStatus.UPLOADED,
            EvidenceFileStatus.PROCESSING,
        }:
            pending += 1
        elif (
            record.status is EvidenceStatus.RECEIVED
            and record.file_status is EvidenceFileStatus.READY
        ):
            received += 1
        else:
            needs_attention += 1
    return EvidenceSummary(
        received=received,
        pending=pending,
        needs_attention=needs_attention,
    )


def evidence_state_for(records: Sequence[EvidenceRecord]) -> EvidenceState:
    statuses = {record.status for record in records}
    if EvidenceStatus.INCONSISTENT in statuses:
        return EvidenceState.INCONSISTENT
    if EvidenceStatus.INCOMPLETE in statuses:
        return EvidenceState.INCOMPLETE
    if EvidenceStatus.UNOFFICIAL in statuses:
        return EvidenceState.UNOFFICIAL
    if EvidenceStatus.PENDING_GENERATION in statuses:
        return EvidenceState.PENDING_GENERATION
    if records and statuses == {EvidenceStatus.RECEIVED}:
        return EvidenceState.RECEIVED
    return EvidenceState.NOT_STARTED
