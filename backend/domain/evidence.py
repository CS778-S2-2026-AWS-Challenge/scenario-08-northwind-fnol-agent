from collections.abc import Sequence
from enum import Enum

from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceReference,
    EvidenceRelation,
    EvidenceRelationState,
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

# Conditions that describe material nobody can open, and for which a file status other
# than `not_available` would be a contradiction rather than extra detail.
NO_ARTEFACT_STATUSES = frozenset({EvidenceStatus.MISSING, EvidenceStatus.UNAVAILABLE})

# Conditions that describe material that arrived. Something arrived, so a file status
# describing an upload still in flight, or one that never started, contradicts them.
SETTLED_FILE_STATES = frozenset({EvidenceFileStatus.READY, EvidenceFileStatus.FAILED})


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


def unresolved_conflicts(references: Sequence[EvidenceReference]) -> tuple[str, ...]:
    """Report what a record is recorded as being in unresolved conflict with.

    A conflict is not a status, so it is not read from one. It is read from the record's
    own references, which is also the only place that can say what the other side is.
    This takes the references rather than the record so that the staff handoff
    projection answers the question from the same rule as the authoritative record,
    rather than keeping a second copy of it.

    Args:
        references: The record's references.

    Returns:
        The evidence identifiers and field codes it contests, empty when none stand open.
    """

    contested: list[str] = []
    for reference in references:
        if reference.relation is not EvidenceRelation.CONFLICTS_WITH:
            continue
        if reference.state is not EvidenceRelationState.UNRESOLVED:
            continue
        contested.append(reference.evidence_id or f'field:{reference.field_code}')
    return tuple(contested)


def is_in_conflict(references: Sequence[EvidenceReference]) -> bool:
    """Whether a record stands in a conflict nobody has resolved.

    Args:
        references: The record's references.

    Returns:
        Whether an unresolved conflict reference names another record or claim field.
    """

    return bool(unresolved_conflicts(references))


def lifecycle_stage_for(record: EvidenceRecord) -> EvidenceLifecycleStage:
    """Resolve one record to the shared lifecycle stage it occupies.

    This is the single source of the state rules. Fixtures, path entries, and
    scenarios all resolve through it, so no path can define a private mapping
    from status and file status to a lifecycle stage.

    The two vocabularies now answer different questions, so the stage is read from both
    rather than from either alone: `pending` business condition with nothing to upload is
    a document that does not exist yet, while the same condition with an upload in flight
    is a file on its way in.

    Args:
        record: The record to resolve.

    Returns:
        The shared stage the record occupies.

    Raises:
        UnregisteredEvidenceShape: The status and file status do not describe a stage.
    """

    if record.status is EvidenceStatus.UNOFFICIAL:
        return EvidenceLifecycleStage.UNOFFICIAL
    if record.status is EvidenceStatus.PENDING:
        if record.file_status is EvidenceFileStatus.NOT_AVAILABLE:
            return EvidenceLifecycleStage.NOT_YET_GENERATED
        if record.file_status in PENDING_FILE_STATES:
            return EvidenceLifecycleStage.PENDING
    if record.status is EvidenceStatus.RECEIVED:
        if record.file_status is EvidenceFileStatus.READY:
            return EvidenceLifecycleStage.RECEIVED
        if record.file_status is EvidenceFileStatus.PROCESSING:
            return EvidenceLifecycleStage.PENDING
        if record.file_status is EvidenceFileStatus.FAILED:
            return EvidenceLifecycleStage.INCOMPLETE
    if record.status is EvidenceStatus.INVALID:
        return EvidenceLifecycleStage.INCOMPLETE
    raise UnregisteredEvidenceShape(
        f'{record.evidence_id}: status {record.status.value} with file status '
        f'{record.file_status.value} is not a registered evidence lifecycle stage.'
    )


def is_registered_evidence_shape(record: EvidenceRecord) -> bool:
    """Whether a record uses a status and file status the shared model allows.

    Wider than `lifecycle_stage_for`, which answers only for the five *entry*
    stages a claim can start an item in. The conditions registered here and not there
    are the ones a claim reaches later rather than starts in: material that was sought
    and established as unobtainable, material replaced by a later issue, material whose
    validity window closed, and material nothing was ever offered for.

    Each of those is registered only with a file status that does not contradict it. A
    missing or unavailable material has nothing to open, so a `ready` file would say a
    document exists for a condition whose whole meaning is that none does. A superseded
    or expired one is the opposite: it arrived and is still in the record, so an upload
    still in flight would say it never did.

    A record standing in an unresolved conflict is held to a narrower shape still. A
    conflict is established by comparing settled evidence, so a material still arriving,
    or one that never arrived and never will, cannot be the thing another record
    disagrees with. That rule predates the reference model — it was carried by the
    retired `inconsistent` status, which was registered only with a `ready` file — and it
    survives the migration unchanged, because what made it true was never the status.

    Args:
        record: The record to check.

    Returns:
        Whether the record's status and file status can hold together.
    """

    if is_in_conflict(record.references) and not (
        record.status is EvidenceStatus.RECEIVED and record.file_status is EvidenceFileStatus.READY
    ):
        return False
    if record.status in NO_ARTEFACT_STATUSES:
        return record.file_status is EvidenceFileStatus.NOT_AVAILABLE
    if record.status in {
        EvidenceStatus.SUPERSEDED,
        EvidenceStatus.EXPIRED,
        EvidenceStatus.INVALID,
    }:
        return record.file_status in SETTLED_FILE_STATES
    try:
        lifecycle_stage_for(record)
    except UnregisteredEvidenceShape:
        return False
    return True


def evidence_summary_for(records: Sequence[EvidenceRecord]) -> EvidenceSummary:
    """Count what a claim has, is waiting for, and must act on.

    Args:
        records: The claim's evidence records.

    Returns:
        The three counts, which always sum to the number of records.
    """

    received = 0
    pending = 0
    needs_attention = 0
    for record in records:
        if record.status is EvidenceStatus.PENDING or record.file_status in PENDING_FILE_STATES:
            pending += 1
        elif (
            record.status is EvidenceStatus.RECEIVED
            and record.file_status is EvidenceFileStatus.READY
            and not is_in_conflict(record.references)
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
    """Roll a claim's evidence records up to the one position it is in.

    Ordered by what a reader has to act on first. An unresolved conflict outranks
    everything because it is the only one where the claim holds two accounts and cannot
    proceed on either. Material that arrived and is unusable outranks material that has
    not arrived, because there is something to act on rather than something to wait for.

    Args:
        records: The claim's evidence records.

    Returns:
        The claim's evidence state.
    """

    if any(is_in_conflict(record.references) for record in records):
        return EvidenceState.IN_CONFLICT
    statuses = {record.status for record in records}
    if EvidenceStatus.INVALID in statuses:
        return EvidenceState.INVALID
    if any(record.file_status is EvidenceFileStatus.FAILED for record in records):
        return EvidenceState.INVALID
    if EvidenceStatus.UNOFFICIAL in statuses:
        return EvidenceState.UNOFFICIAL
    if EvidenceStatus.UNAVAILABLE in statuses:
        return EvidenceState.UNAVAILABLE
    if EvidenceStatus.PENDING in statuses or EvidenceStatus.MISSING in statuses:
        return EvidenceState.PENDING
    if any(record.file_status in PENDING_FILE_STATES for record in records):
        return EvidenceState.PENDING
    if records and statuses <= {
        EvidenceStatus.RECEIVED,
        EvidenceStatus.SUPERSEDED,
        EvidenceStatus.EXPIRED,
    }:
        return EvidenceState.RECEIVED
    return EvidenceState.NOT_STARTED
