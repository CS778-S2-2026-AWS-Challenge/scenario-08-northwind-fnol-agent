"""Ownership-safe account Policy Summary behavior."""

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.ids import new_id
from backend.domain.models import ActorType, PageInfo
from backend.domain.policies import (
    CreatePolicySummaryRequest,
    PolicySummaryListResponse,
    PolicySummaryProjection,
    PolicySummaryRecord,
    UpdatePolicySummaryRequest,
    project_policy_summary,
)
from backend.repositories.policies import PolicySummaryRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.support import (
    decode_cursor,
    encode_cursor,
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

CREATE_ROUTE = '/api/v1/account/policies'


def _not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The policy summary was not found.',
    )


def _revision_conflict(current_revision: int) -> ApiError:
    return ApiError(
        status_code=409,
        code='REVISION_CONFLICT',
        message='The resource changed after this page was loaded.',
        retryable=True,
        current_revision=current_revision,
    )


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The Idempotency-Key was already used with a different request.',
    )


def _policy_audit_event(
    policy: PolicySummaryRecord,
    principal: Principal,
    *,
    action: str,
    idempotency_key: str | None = None,
) -> AuditEventEnvelope:
    return AuditEventEnvelope(
        event_id=new_id('aud'),
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.POLICY,
            subject_id=policy.policy_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason=f'Claimant {action} the account Policy Summary.',
        source_refs=[f'policy:{policy.policy_id}:revision:{policy.revision}'],
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=idempotency_key,
        created_at=policy.updated_at,
    )


def create_policy_summary(
    repository: PolicySummaryRepository,
    idempotency_repository: PersistenceRepository,
    principal: Principal,
    payload: CreatePolicySummaryRequest,
    idempotency_key: str | None,
) -> PolicySummaryProjection:
    key = require_idempotency_key(idempotency_key)
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = idempotency_repository.find_idempotency(principal.subject, CREATE_ROUTE, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.response_payload is None:
            raise _idempotency_conflict()
        return PolicySummaryProjection.model_validate(existing.response_payload)

    timestamp = now_utc()
    policy = PolicySummaryRecord(
        policy_id=new_id('pol'),
        customer_id=principal.subject,
        created_at=timestamp,
        updated_at=timestamp,
        **payload.model_dump(),
    )
    projection = project_policy_summary(policy)
    record = IdempotencyRecord(
        actor_id=principal.subject,
        route=CREATE_ROUTE,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=policy.policy_id,
        session_id='',
        response_payload=projection.model_dump(mode='json'),
    )
    try:
        repository.create_policy_summary(
            policy,
            record,
            _policy_audit_event(policy, principal, action='created', idempotency_key=key),
        )
    except IdempotencyConflict as error:
        replay = idempotency_repository.find_idempotency(principal.subject, CREATE_ROUTE, key)
        if (
            replay is None
            or replay.request_fingerprint != fingerprint
            or replay.response_payload is None
        ):
            raise _idempotency_conflict() from error
        return PolicySummaryProjection.model_validate(replay.response_payload)
    return projection


def get_policy_summary(
    repository: PolicySummaryRepository,
    principal: Principal,
    policy_id: str,
) -> PolicySummaryProjection:
    policy = repository.get_policy_summary(policy_id, principal.subject)
    if policy is None:
        raise _not_found()
    return project_policy_summary(policy)


def list_policy_summaries(
    repository: PolicySummaryRepository,
    principal: Principal,
    *,
    include_inactive: bool,
    limit: int,
    cursor: str | None,
) -> PolicySummaryListResponse:
    offset = decode_cursor(cursor)
    records, has_more = repository.list_policy_summaries(
        principal.subject,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
    )
    page = PageInfo(next_cursor=encode_cursor(offset + len(records)) if has_more else None)
    return PolicySummaryListResponse(
        items=[project_policy_summary(item) for item in records],
        page=page,
    )


def update_policy_summary(
    repository: PolicySummaryRepository,
    principal: Principal,
    policy_id: str,
    payload: UpdatePolicySummaryRequest,
    if_match: str | None,
) -> PolicySummaryProjection:
    expected_revision = parse_if_match(if_match)
    current = repository.get_policy_summary(policy_id, principal.subject)
    if current is None:
        raise _not_found()
    if current.revision != expected_revision:
        raise _revision_conflict(current.revision)
    updated = current.model_copy(
        update={
            **payload.model_dump(exclude_unset=True),
            'revision': current.revision + 1,
            'updated_at': now_utc(),
        }
    )
    try:
        repository.update_policy_summary(
            updated,
            expected_revision,
            _policy_audit_event(updated, principal, action='updated'),
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    return project_policy_summary(updated)


def deactivate_policy_summary(
    repository: PolicySummaryRepository,
    principal: Principal,
    policy_id: str,
    if_match: str | None,
) -> None:
    expected_revision = parse_if_match(if_match)
    current = repository.get_policy_summary(policy_id, principal.subject)
    if current is None:
        raise _not_found()
    if current.revision != expected_revision:
        raise _revision_conflict(current.revision)
    if not current.active:
        return
    updated = current.model_copy(
        update={'active': False, 'revision': current.revision + 1, 'updated_at': now_utc()}
    )
    try:
        repository.update_policy_summary(
            updated,
            expected_revision,
            _policy_audit_event(updated, principal, action='deactivated'),
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
