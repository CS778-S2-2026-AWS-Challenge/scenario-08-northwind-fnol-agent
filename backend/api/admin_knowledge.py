from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from backend.core.auth import Principal, require_administrator
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
from backend.domain.knowledge import KnowledgeSearchRequest
from backend.domain.knowledge_admin import (
    AdminKnowledgeSourceProjection,
    KnowledgeSourceCreate,
    KnowledgeSourcePage,
    KnowledgeSourceRecord,
    KnowledgeValidationRequest,
    KnowledgeVersionState,
)
from backend.domain.operations import OperationKind, OperationRecord, OperationState
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.operations import OperationIdempotencyRecord, OperationRepository
from backend.services import knowledge_admin
from backend.services.admin_action_projection import knowledge_projection
from backend.services.knowledge_ingestion import KnowledgeIngestionService
from backend.services.knowledge_search import search_knowledge
from backend.services.support import paginate, request_fingerprint, require_idempotency_key

router = APIRouter(prefix='/internal/v1/admin/knowledge', tags=['administration'])


def repository_for(request: Request) -> KnowledgeAdminRepository:
    return cast(KnowledgeAdminRepository, request.app.state.knowledge_admin_repository)


def operations_for(request: Request) -> OperationRepository:
    return cast(OperationRepository, request.app.state.operation_repository)


def _audit(
    request: Request,
    principal: Principal,
    knowledge_id: str,
    action: str,
    reason: str,
    outcome: AuditOutcome,
) -> None:
    event_type = (
        AuditEventType.ACTION_FAILED
        if outcome is not AuditOutcome.SUCCEEDED
        else AuditEventType.ACTION_COMPLETED
    )
    cast(Any, request.app.state.data_runtime_bundle.repository).append_audit_event(
        AuditEventEnvelope(
            event_id=new_id('aud'),
            event_type=event_type,
            outcome=outcome,
            subject=AuditSubject(
                subject_type=AuditSubjectType.CONFIGURATION,
                subject_id=f'knowledge:{knowledge_id}',
            ),
            actor=AuditActor(
                actor_id=f'{principal.actor_type}:{principal.subject}',
                actor_type='system',
                auth_source=principal.auth_source,
            ),
            reason=f'{action}: {reason}',
            source_refs=[f'knowledge:{knowledge_id}'],
            visibility=AuditVisibility.ADMINISTRATION_ONLY,
            correlation_id=getattr(request.state, 'request_id', None),
            created_at=datetime.now(UTC),
        )
    )


def _idempotent(
    request: Request,
    principal: Principal,
    key: str | None,
    route: str,
    payload: object,
) -> tuple[str, str, JSONResponse | None]:
    idempotency_key = require_idempotency_key(key)
    fingerprint = request_fingerprint(payload)
    repository = operations_for(request)
    existing = repository.find_idempotency(principal.subject, route, idempotency_key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Idempotency-Key was reused with a different request.',
            )
        return (
            idempotency_key,
            fingerprint,
            JSONResponse(
                status_code=existing.status_code,
                content=existing.response,
            ),
        )
    return idempotency_key, fingerprint, None


def _remember(
    request: Request,
    principal: Principal,
    route: str,
    key: str,
    fingerprint: str,
    response: dict[str, object],
    status_code: int,
) -> None:
    operations_for(request).save_idempotency(
        OperationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            response=response,
            status_code=status_code,
        )
    )


def _new_operation(request: Request, kind: OperationKind, subject: str) -> OperationRecord:
    repository = operations_for(request)
    now = datetime.now(UTC)
    operation_id = repository.new_operation_id()
    operation = repository.create(
        OperationRecord(
            operation_id=operation_id,
            kind=kind,
            subject_type='knowledge',
            subject_id=subject,
            state=OperationState.QUEUED,
            revision=1,
            status_url=f'/internal/v1/admin/operations/{operation_id}',
            progress_percent=0,
            created_at=now,
            updated_at=now,
        )
    )
    # Advance the operation to running after the durable queued record exists.
    running = operation.model_copy(
        update={
            'state': OperationState.RUNNING,
            'revision': 2,
            'progress_percent': 20,
            'status_url': f'/internal/v1/admin/operations/{operation.operation_id}',
            'updated_at': datetime.now(UTC),
        }
    )
    repository.save(running, operation.revision)
    return running


def _finish_operation(
    request: Request,
    operation: OperationRecord,
    *,
    state: OperationState,
    result: dict[str, object] | None = None,
    error_code: str | None = None,
) -> OperationRecord:
    finished = operation.model_copy(
        update={
            'state': state,
            'revision': operation.revision + 1,
            'progress_percent': 100,
            'result': result,
            'error_code': error_code,
            'updated_at': datetime.now(UTC),
        }
    )
    return operations_for(request).save(finished, operation.revision)


@router.post('', response_model=KnowledgeSourceRecord, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: KnowledgeSourceCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> KnowledgeSourceRecord | JSONResponse:
    route = 'POST /internal/v1/admin/knowledge'
    key, fingerprint, replay = _idempotent(
        request, principal, idempotency_key, route, payload.model_dump(mode='json')
    )
    if replay is not None:
        return replay
    source = knowledge_admin.to_source(payload)
    store: Any = getattr(request.app.state, 'knowledge_object_store', None)
    if payload.content is not None:
        if not hasattr(store, 'write'):
            raise ApiError(
                status_code=503,
                code='KNOWLEDGE_STORE_UNAVAILABLE',
                message='The configured knowledge store cannot accept source content.',
                retryable=True,
            )
        try:
            store.write(
                source.source_key,
                payload.content.encode('utf-8'),
                content_type='text/markdown',
                metadata={'document-id': source.document_id, 'version': source.version},
            )
        except Exception as error:
            raise ApiError(
                status_code=503,
                code='KNOWLEDGE_STORE_UNAVAILABLE',
                message='The configured knowledge store is unavailable.',
                retryable=True,
            ) from error
    record = knowledge_admin.record_from_source(
        repository_for(request), source, principal.subject, content=payload.content
    )
    try:
        saved = repository_for(request).create(record)
    except ValueError as error:
        code = (
            'KNOWLEDGE_VERSION_EXISTS'
            if str(error) == 'knowledge_version_exists'
            else 'KNOWLEDGE_EXISTS'
        )
        raise ApiError(
            status_code=409, code=code, message='The knowledge version already exists.'
        ) from error
    _remember(
        request,
        principal,
        route,
        key,
        fingerprint,
        saved.model_dump(mode='json'),
        status.HTTP_201_CREATED,
    )
    _audit(
        request,
        principal,
        saved.knowledge_id,
        'create',
        'Knowledge draft created.',
        AuditOutcome.SUCCEEDED,
    )
    return saved


@router.get('', response_model=KnowledgeSourcePage)
def list_sources(
    request: Request,
    state: KnowledgeVersionState | None = Query(default=None),
    document_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> KnowledgeSourcePage:
    records = repository_for(request).list(state=state, document_id=document_id, limit=100)
    selected, page = paginate(records, limit, cursor)
    items = [knowledge_projection(item, _principal.subject) for item in selected]
    return KnowledgeSourcePage(items=items, page=page)


@router.get('/{knowledge_id}', response_model=AdminKnowledgeSourceProjection)
def get_source(
    knowledge_id: str,
    request: Request,
    principal: Principal = Depends(require_administrator),
) -> AdminKnowledgeSourceProjection:
    record = repository_for(request).get(knowledge_id)
    if record is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    return knowledge_projection(record, principal.subject)


@router.post('/{knowledge_id}/validate', response_model=KnowledgeSourceRecord)
def validate_source(
    knowledge_id: str,
    payload: KnowledgeValidationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> KnowledgeSourceRecord | JSONResponse:
    route = f'POST /internal/v1/admin/knowledge/{knowledge_id}/validate'
    key, fingerprint, replay = _idempotent(
        request, principal, idempotency_key, route, payload.model_dump(mode='json')
    )
    if replay is not None:
        return replay
    current = repository_for(request).get(knowledge_id)
    if current is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    if current.state not in {
        KnowledgeVersionState.DRAFT,
        KnowledgeVersionState.FAILED,
        KnowledgeVersionState.INDEXED,
    }:
        raise ApiError(
            status_code=400,
            code='INVALID_KNOWLEDGE_TRANSITION',
            message='Only a draft, indexed, or failed version can be validated.',
        )
    failed = [item for item in payload.scenario_results if item.get('outcome') != 'passed']
    evidence = {'scenarios': payload.scenario_results, 'result': 'failed' if failed else 'passed'}
    updated = current.model_copy(
        update={
            'revision': current.revision + 1,
            'state': KnowledgeVersionState.FAILED
            if failed
            else KnowledgeVersionState.AWAITING_APPROVAL,
            'validation_evidence': evidence,
            'error_code': 'VALIDATION_FAILED' if failed else None,
            'updated_at': datetime.now(UTC),
        }
    )
    saved = repository_for(request).save(updated, current.revision)
    _audit(
        request,
        principal,
        saved.knowledge_id,
        'validate',
        'Knowledge validation recorded.',
        AuditOutcome.SUCCEEDED if not failed else AuditOutcome.FAILED,
    )
    _remember(
        request,
        principal,
        route,
        key,
        fingerprint,
        saved.model_dump(mode='json'),
        status.HTTP_200_OK,
    )
    return saved


@router.post('/{knowledge_id}/ingest', response_model=KnowledgeSourceRecord)
def ingest_source(
    knowledge_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> KnowledgeSourceRecord | JSONResponse:
    route = f'POST /internal/v1/admin/knowledge/{knowledge_id}/ingest'
    key, fingerprint, replay = _idempotent(
        request, principal, idempotency_key, route, {'knowledge_id': knowledge_id}
    )
    if replay is not None:
        return replay
    current = repository_for(request).get(knowledge_id)
    if current is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    if current.state not in {KnowledgeVersionState.DRAFT, KnowledgeVersionState.FAILED}:
        raise ApiError(
            status_code=400,
            code='INVALID_KNOWLEDGE_TRANSITION',
            message='Only a draft or failed version can be indexed.',
        )
    store: Any = getattr(request.app.state, 'knowledge_object_store', None)
    if not hasattr(store, 'read') or not hasattr(store, 'write'):
        raise ApiError(
            status_code=503,
            code='KNOWLEDGE_STORE_UNAVAILABLE',
            message='The configured knowledge store cannot run ingestion.',
            retryable=True,
        )
    source = KnowledgeSourceCreate(
        document_id=current.document_id,
        version=current.version,
        source_key=current.source_key,
        title=current.title,
        document_type=current.document_type,
        source_uri=current.source_uri,
        jurisdiction=current.jurisdiction,
        insurer=current.insurer,
        product=current.product,
        effective_from=current.effective_from,
        effective_to=current.effective_to,
        authority=current.authority,
        visibility=current.visibility,
        expected_checksum=current.expected_checksum,
    )
    governed = knowledge_admin.to_source(source)
    operation = _new_operation(request, OperationKind.KNOWLEDGE_INGESTION, knowledge_id)
    try:
        result = KnowledgeIngestionService(
            store, {(governed.document_id, governed.version): governed}
        ).ingest(governed)
    except Exception as error:
        code = getattr(error, 'code', 'KNOWLEDGE_INGESTION_FAILED')
        _finish_operation(request, operation, state=OperationState.FAILED, error_code=code)
        failed = current.model_copy(
            update={
                'revision': current.revision + 1,
                'state': KnowledgeVersionState.FAILED,
                'error_code': code,
                'ingestion_operation_id': operation.operation_id,
                'updated_at': datetime.now(UTC),
            }
        )
        saved = repository_for(request).save(failed, current.revision)
        _audit(
            request,
            principal,
            saved.knowledge_id,
            'ingest',
            code,
            AuditOutcome.FAILED,
        )
        _remember(
            request,
            principal,
            route,
            key,
            fingerprint,
            saved.model_dump(mode='json'),
            status.HTTP_200_OK,
        )
        return saved
    _finish_operation(
        request,
        operation,
        state=OperationState.SUCCEEDED,
        result={'chunk_count': result.chunk_count, 'checksum': result.source_checksum},
    )
    saved = repository_for(request).save(
        current.model_copy(
            update={
                'revision': current.revision + 1,
                'state': KnowledgeVersionState.INDEXED,
                'chunk_count': result.chunk_count,
                'ingestion_operation_id': operation.operation_id,
                'error_code': None,
                'updated_at': datetime.now(UTC),
            }
        ),
        current.revision,
    )
    _audit(
        request,
        principal,
        saved.knowledge_id,
        'ingest',
        'Knowledge ingestion completed.',
        AuditOutcome.SUCCEEDED,
    )
    _remember(
        request,
        principal,
        route,
        key,
        fingerprint,
        saved.model_dump(mode='json'),
        status.HTTP_200_OK,
    )
    return saved


@router.post('/{knowledge_id}/retrieval-check', response_model=dict)
def retrieval_check(
    knowledge_id: str,
    payload: KnowledgeSearchRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> dict[str, object] | JSONResponse:
    route = f'POST /internal/v1/admin/knowledge/{knowledge_id}/retrieval-check'
    key, fingerprint, replay = _idempotent(
        request, principal, idempotency_key, route, payload.model_dump(mode='json')
    )
    if replay is not None:
        return replay
    current = repository_for(request).get(knowledge_id)
    if current is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    operation = _new_operation(request, OperationKind.RETRIEVAL_CHECK, knowledge_id)
    result = search_knowledge(cast(Any, request.app.state.knowledge_retriever), payload)
    _finish_operation(
        request,
        operation,
        state=OperationState.SUCCEEDED,
        result={'status': result.status, 'result_count': len(result.results)},
    )
    _audit(
        request,
        principal,
        knowledge_id,
        'retrieval_check',
        'Knowledge retrieval check completed.',
        AuditOutcome.SUCCEEDED,
    )
    response: dict[str, object] = {
        'operation_id': operation.operation_id,
        'knowledge_id': knowledge_id,
        'result': result.model_dump(mode='json'),
    }
    _remember(request, principal, route, key, fingerprint, response, status.HTTP_200_OK)
    return response


@router.post('/{knowledge_id}/publish', response_model=KnowledgeSourceRecord)
def publish_source(
    knowledge_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> KnowledgeSourceRecord | JSONResponse:
    route = f'POST /internal/v1/admin/knowledge/{knowledge_id}/publish'
    key, fingerprint, replay = _idempotent(
        request, principal, idempotency_key, route, {'knowledge_id': knowledge_id}
    )
    if replay is not None:
        return replay
    repository = repository_for(request)
    current = repository.get(knowledge_id)
    if current is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    if (
        current.state
        not in {KnowledgeVersionState.INDEXED, KnowledgeVersionState.AWAITING_APPROVAL}
        or current.validation_evidence is None
    ):
        raise ApiError(
            status_code=400,
            code='INVALID_KNOWLEDGE_TRANSITION',
            message='Only an indexed, validated version can be published.',
        )
    if current.author == principal.subject:
        _audit(
            request,
            principal,
            knowledge_id,
            'publish',
            'The source author cannot publish the version.',
            AuditOutcome.REJECTED,
        )
        raise ApiError(
            status_code=403,
            code='KNOWLEDGE_APPROVER_CONFLICT',
            message='The source author cannot publish a high-impact knowledge version.',
        )
    previous = repository.active(current.document_id)
    if previous is not None and previous.knowledge_id != current.knowledge_id:
        repository.save(
            previous.model_copy(
                update={
                    'revision': previous.revision + 1,
                    'state': KnowledgeVersionState.SUPERSEDED,
                    'updated_at': datetime.now(UTC),
                }
            ),
            previous.revision,
        )
    saved = repository.save(
        current.model_copy(
            update={
                'revision': current.revision + 1,
                'state': KnowledgeVersionState.PUBLISHED,
                'previous_version': previous.knowledge_id if previous else None,
                'updated_at': datetime.now(UTC),
            }
        ),
        current.revision,
    )
    _audit(
        request,
        principal,
        saved.knowledge_id,
        'publish',
        'Knowledge version published.',
        AuditOutcome.SUCCEEDED,
    )
    _remember(
        request,
        principal,
        route,
        key,
        fingerprint,
        saved.model_dump(mode='json'),
        status.HTTP_200_OK,
    )
    return saved


@router.post('/{knowledge_id}/withdraw', response_model=KnowledgeSourceRecord)
def withdraw_source(
    knowledge_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> KnowledgeSourceRecord | JSONResponse:
    route = f'POST /internal/v1/admin/knowledge/{knowledge_id}/withdraw'
    key, fingerprint, replay = _idempotent(
        request, principal, idempotency_key, route, {'knowledge_id': knowledge_id}
    )
    if replay is not None:
        return replay
    repository = repository_for(request)
    current = repository.get(knowledge_id)
    if current is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    if current.state in {KnowledgeVersionState.WITHDRAWN, KnowledgeVersionState.SUPERSEDED}:
        raise ApiError(
            status_code=400,
            code='INVALID_KNOWLEDGE_TRANSITION',
            message='The knowledge version cannot be withdrawn from its current state.',
        )
    saved = repository.save(
        current.model_copy(
            update={
                'revision': current.revision + 1,
                'state': KnowledgeVersionState.WITHDRAWN,
                'updated_at': datetime.now(UTC),
            }
        ),
        current.revision,
    )
    _audit(
        request,
        principal,
        saved.knowledge_id,
        'withdraw',
        'Knowledge version withdrawn.',
        AuditOutcome.SUCCEEDED,
    )
    _remember(
        request,
        principal,
        route,
        key,
        fingerprint,
        saved.model_dump(mode='json'),
        status.HTTP_200_OK,
    )
    return saved


@router.get('/{knowledge_id}/audit', response_model=dict)
def audit_source(
    knowledge_id: str,
    request: Request,
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    if repository_for(request).get(knowledge_id) is None:
        raise ApiError(
            status_code=404,
            code='KNOWLEDGE_NOT_FOUND',
            message='The knowledge version was not found.',
        )
    repository = cast(Any, request.app.state.data_runtime_bundle.repository)
    subject = AuditSubject(
        subject_type=AuditSubjectType.CONFIGURATION,
        subject_id=f'knowledge:{knowledge_id}',
    )
    events = repository.list_audit_events_internal(subject)
    return {'items': events, 'page': {'next_cursor': None}}
