"""Runtime-owned implementations for the small, read-only tool surface."""

from collections.abc import Mapping

from backend.domain.agent_tool_registry import tool_contract
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    WorkingClaim,
)
from backend.repositories.protocols import PersistenceRepository

_HISTORY_FILE_STATES = frozenset(
    {
        EvidenceFileStatus.UPLOADED,
        EvidenceFileStatus.PROCESSING,
        EvidenceFileStatus.READY,
        EvidenceFileStatus.FAILED,
    }
)


def _history_entry(record: EvidenceRecord) -> dict[str, object]:
    """Build the claimant-safe subset used by the Agent tool."""

    return {
        'evidence_id': record.evidence_id,
        'source_claim_id': record.claim_id,
        'kind': record.kind,
        'status': record.status.value,
        'file_status': record.file_status.value,
        'original_filename': record.original_filename,
        'media_type': record.media_type,
        'size_bytes': record.size_bytes,
        'source': record.source.value,
        'provenance_summary': ['claimant_upload']
        if record.source is EvidenceSource.CLAIMANT
        else [],
        'can_reuse': (
            record.source is EvidenceSource.CLAIMANT
            and record.file_status is EvidenceFileStatus.READY
            and record.status
            not in {EvidenceStatus.INVALID, EvidenceStatus.EXPIRED, EvidenceStatus.SUPERSEDED}
        ),
        # The current Evidence API deliberately does not expose a governed remove path.
        'can_remove': False,
        'created_at': record.created_at.isoformat(),
        'updated_at': record.updated_at.isoformat(),
    }


def read_evidence_history_for_runtime(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Read one bounded, claimant-scoped Evidence history projection.

    The authenticated message boundary supplies the current Claim. The Agent cannot
    select a customer, Claim, storage key, or provider path. Repository access is
    filtered by the Claim's customer identity and the same uploaded-file rules used
    by ``GET /api/v1/evidence``.
    """

    contract = tool_contract('evidence.history')
    # Runtime repositories use structural typing; keep the error useful for unit callers.
    if not hasattr(repository, 'list_evidence_for_customer'):
        raise TypeError('repository must provide claimant-scoped Evidence history access.')
    if not isinstance(arguments, Mapping):
        raise TypeError('evidence.history arguments must be a mapping.')
    unknown = set(arguments) - {'limit'}
    if unknown:
        raise ValueError(f'evidence.history does not accept: {", ".join(sorted(unknown))}.')
    raw_limit = arguments.get('limit', 25)
    if not isinstance(raw_limit, int) or isinstance(raw_limit, bool) or not 1 <= raw_limit <= 50:
        raise ValueError('evidence.history limit must be an integer between 1 and 50.')

    records = [
        record
        for record in repository.list_evidence_for_customer(claim.customer_id)
        if record.source is EvidenceSource.CLAIMANT and record.file_status in _HISTORY_FILE_STATES
    ]
    records = records[:raw_limit]
    return {
        'tool': contract.name,
        'status': 'succeeded',
        'items': [_history_entry(record) for record in records],
        'source_refs': [record.evidence_id for record in records],
        'limitations': [
            'History is claimant-scoped and does not grant permission to attach or remove Evidence.'
        ],
    }


def validate_evidence_proposal(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    *,
    action_code: str,
    evidence_id: str,
    source_claim_id: str | None = None,
    confirmation_ref: str | None = None,
    removal_scope: str | None = None,
) -> dict[str, object]:
    """Validate an Evidence reuse/removal proposal without performing a side effect.

    This is the backend boundary for the two new proposal actions. It deliberately
    returns ``unavailable`` for persisted removal because no governed remove handler
    exists yet; callers must not convert that result into a completed operation.
    """

    if action_code not in {'evidence.propose_reuse', 'evidence.propose_remove'}:
        raise ValueError(f'Unsupported Evidence proposal: {action_code}.')
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        return {'status': 'rejected', 'reason': 'EVIDENCE_ID_REQUIRED'}
    if not isinstance(confirmation_ref, str) or not confirmation_ref.strip():
        return {'status': 'rejected', 'reason': 'CLAIMANT_CONFIRMATION_REQUIRED'}

    record = next(
        (
            candidate
            for candidate in repository.list_evidence_for_customer(claim.customer_id)
            if candidate.evidence_id == evidence_id
        ),
        None,
    )
    if record is None or record.source is not EvidenceSource.CLAIMANT:
        return {'status': 'rejected', 'reason': 'EVIDENCE_SCOPE_DENIED'}

    if action_code == 'evidence.propose_reuse':
        if source_claim_id != record.claim_id:
            return {'status': 'rejected', 'reason': 'SOURCE_CLAIM_MISMATCH'}
        if not (
            record.file_status is EvidenceFileStatus.READY
            and record.status
            not in {EvidenceStatus.INVALID, EvidenceStatus.EXPIRED, EvidenceStatus.SUPERSEDED}
        ):
            return {'status': 'rejected', 'reason': 'EVIDENCE_NOT_REUSABLE'}
        return {
            'status': 'proposed',
            'reason': 'CONFIRMATION_REQUIRED_FOR_EVIDENCE_API_ATTACH',
            'source_claim_id': record.claim_id,
            'target_claim_id': claim.claim_id,
            'evidence_id': record.evidence_id,
        }

    if removal_scope not in {'draft', 'persisted'}:
        return {'status': 'rejected', 'reason': 'REMOVAL_SCOPE_REQUIRED'}
    if removal_scope == 'draft':
        return {
            'status': 'unavailable',
            'reason': 'DRAFT_REMOVAL_IS_FRONTEND_OWNED',
            'evidence_id': record.evidence_id,
        }
    return {
        'status': 'unavailable',
        'reason': 'PERSISTED_REMOVE_HANDLER_UNAVAILABLE',
        'evidence_id': record.evidence_id,
        'can_remove': False,
        'limitations': ['Retention and audit policy do not currently expose a remove API.'],
    }


def read_claim_for_runtime(
    claim: WorkingClaim,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Return the current Claim projection for the authenticated turn.

    The caller supplies the already-authorised current Claim loaded by the message
    transaction. No provider response or fixture is manufactured here, and the tool
    accepts no caller-selected claim identifier, preventing cross-claim reads.
    """

    contract = tool_contract('claim.read')
    if arguments:
        raise ValueError('claim.read does not accept input arguments.')
    form = {
        field_code: {
            'value': field.value,
            'status': field.status.value,
            'source': field.source.value,
            'needed_for': field.needed_for.value,
        }
        for field_code, field in sorted(claim.form.items())
        if field.needed_for.value == 'current_action'
    }
    return {
        'tool': contract.name,
        'claim_id': claim.claim_id,
        'revision': claim.revision,
        'incident_type': claim.incident_type,
        'workflow_state': claim.claim_state.workflow_state.value,
        'next_action': claim.claim_state.next_action.value,
        'customer_next_step': claim.customer_next_step.model_dump(mode='json'),
        'form': form,
        'evidence_summary': claim.evidence_summary.model_dump(mode='json'),
    }
