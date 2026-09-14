"""Runtime-owned implementations for the small, read-only tool surface."""

from collections.abc import Mapping

from backend.core.auth import Principal
from backend.domain.agent_tool_registry import tool_contract
from backend.domain.models import EvidenceFileStatus, EvidenceSource, EvidenceStatus, WorkingClaim
from backend.repositories.protocols import PersistenceRepository
from backend.services.evidence import list_evidence_history


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
    unknown = set(arguments) - {'limit', 'cursor'}
    if unknown:
        raise ValueError(f'evidence.history does not accept: {", ".join(sorted(unknown))}.')
    raw_limit = arguments.get('limit', 25)
    if not isinstance(raw_limit, int) or isinstance(raw_limit, bool) or not 1 <= raw_limit <= 50:
        raise ValueError('evidence.history limit must be an integer between 1 and 50.')
    raw_cursor = arguments.get('cursor')
    if raw_cursor is not None and (not isinstance(raw_cursor, str) or not raw_cursor.strip()):
        raise ValueError('evidence.history cursor must be a non-empty string.')

    history = list_evidence_history(
        repository,
        Principal(
            subject=claim.customer_id,
            actor_type='claimant',
            auth_source='runtime:claimant_session',
        ),
        limit=raw_limit,
        cursor=raw_cursor,
    )
    next_cursor = history.page.next_cursor
    limitations = [
        'History is claimant-scoped and does not grant permission to attach or remove Evidence.'
    ]
    if next_cursor is not None:
        limitations.append(
            'More Evidence history is available; this page cannot support an exhaustive '
            'not-found conclusion.'
        )
    return {
        'tool': contract.name,
        'status': 'succeeded',
        'items': [item.model_dump(mode='json') for item in history.items],
        'source_refs': [item.evidence_id for item in history.items],
        'page': {'next_cursor': next_cursor},
        'limitations': limitations,
    }


def validate_evidence_proposal(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    *,
    action_code: str,
    evidence_id: str,
    source_claim_id: str | None = None,
    removal_scope: str | None = None,
) -> dict[str, object]:
    """Validate an Evidence reuse/removal proposal without performing a side effect.

    This is the backend boundary for the two new proposal actions. It deliberately
    returns ``unavailable`` for persisted removal because no governed remove handler
    exists yet; callers must not convert that result into a completed operation.
    """

    if action_code not in {'claim.propose_evidence_reuse', 'claim.propose_evidence_remove'}:
        raise ValueError(f'Unsupported Evidence proposal: {action_code}.')
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        return {'status': 'rejected', 'reason': 'EVIDENCE_ID_REQUIRED'}
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

    if action_code == 'claim.propose_evidence_reuse':
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
            'reason': 'CLAIMANT_CONFIRMATION_REQUIRED_BEFORE_EVIDENCE_API_ATTACH',
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
