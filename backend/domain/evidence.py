from collections.abc import Sequence
from enum import Enum

from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceState,
    EvidenceStatus,
    EvidenceSummary,
)

PENDING_FILE_STATES = frozenset(
    {
        EvidenceFileStatus.AWAITING_UPLOAD,
        EvidenceFileStatus.UPLOADING,
        EvidenceFileStatus.UPLOADED,
        EvidenceFileStatus.PROCESSING,
    }
)


class EvidenceLifecycleStage(str, Enum):
    """The entry states every business path shares.

    `pending` means an upload is already in flight. `not_yet_generated` means
    the external document does not exist yet. They stay separate so an
    unavailable document is never mistaken for a failed upload.
    """

    PENDING = 'pending'
    UNOFFICIAL = 'unofficial'
    INCOMPLETE = 'incomplete'
    NOT_YET_GENERATED = 'not_yet_generated'
    RECEIVED = 'received'


class UnregisteredEvidenceShape(ValueError):
    """An evidence record does not match any shared lifecycle stage."""


def lifecycle_stage_for(record: EvidenceRecord) -> EvidenceLifecycleStage:
    """Resolve one record to the shared lifecycle stage it occupies.

    This is the single source of the state rules. Fixtures, path entries, and
    scenarios all resolve through it, so no path can define a private mapping
    from status and file status to a lifecycle stage.
    """

    if record.status is EvidenceStatus.UNOFFICIAL:
        return EvidenceLifecycleStage.UNOFFICIAL
    if (
        record.status is EvidenceStatus.PENDING_GENERATION
        and record.file_status is EvidenceFileStatus.NOT_AVAILABLE
    ):
        return EvidenceLifecycleStage.NOT_YET_GENERATED
    if record.status is EvidenceStatus.RECEIVED and record.file_status is EvidenceFileStatus.READY:
        return EvidenceLifecycleStage.RECEIVED
    if record.status is EvidenceStatus.INCOMPLETE:
        if record.file_status in PENDING_FILE_STATES:
            return EvidenceLifecycleStage.PENDING
        return EvidenceLifecycleStage.INCOMPLETE
    raise UnregisteredEvidenceShape(
        f'{record.evidence_id}: status {record.status.value} with file status '
        f'{record.file_status.value} is not a registered evidence lifecycle stage.'
    )


def is_registered_evidence_shape(record: EvidenceRecord) -> bool:
    """Whether a record uses a status and file status the shared model allows.

    Wider than `lifecycle_stage_for`, which answers only for the five *entry*
    stages a claim can start an item in. `inconsistent` is not an entry state:
    it is reached after two records disagree on a material fact, so it is
    registered here but deliberately has no entry stage.

    A conflict requires comparable settled evidence, so it is only registered
    with a `ready` file. `failed` and `not_available` are excluded as well as
    the pending states: a file that never arrived, or never will, cannot be
    the thing another record disagrees with.
    """

    if record.status is EvidenceStatus.INCONSISTENT:
        return record.file_status is EvidenceFileStatus.READY
    try:
        lifecycle_stage_for(record)
    except UnregisteredEvidenceShape:
        return False
    return True


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
