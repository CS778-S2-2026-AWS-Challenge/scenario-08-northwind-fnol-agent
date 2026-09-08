from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.auth import Principal, require_administrator
from backend.domain.release import (
    AdminReleaseSetPage,
    AdminReleaseSetProjection,
    ReleaseSetCreate,
    ReleaseSetRecord,
    ReleaseSetTransitionRequest,
    ReleaseSetValidationRequest,
    RuntimeSnapshot,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetIdempotencyRecord, ReleaseSetRepository
from backend.services import release_sets
from backend.services.admin_action_projection import release_set_projection
from backend.services.support import (
    paginate,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

router = APIRouter(prefix='/internal/v1/admin', tags=['administration'])


def release_repo(request: Request) -> ReleaseSetRepository:
    return cast(ReleaseSetRepository, request.app.state.release_set_repository)


def configuration_repo(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


def knowledge_repo(request: Request) -> KnowledgeAdminRepository:
    return cast(KnowledgeAdminRepository, request.app.state.knowledge_admin_repository)


def _idempotent(
    request: Request,
    principal: Principal,
    key: str | None,
    route: str,
    payload: object,
    operation: Callable[[], BaseModel],
    success_status: int = status.HTTP_200_OK,
) -> BaseModel | JSONResponse:
    idempotency_key = require_idempotency_key(key)
    fingerprint = request_fingerprint(payload)
    repository = release_repo(request)
    existing = repository.find_idempotency(principal.subject, route, idempotency_key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise release_sets._error(
                409, 'IDEMPOTENCY_CONFLICT', 'Idempotency-Key was reused with a different request.'
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    result = operation()
    repository.save_idempotency(
        ReleaseSetIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=idempotency_key,
            fingerprint=fingerprint,
            response=result.model_dump(mode='json'),
            status_code=success_status,
        )
    )
    return result


@router.get('/release-sets', response_model=AdminReleaseSetPage)
def list_release_sets(
    request: Request,
    environment: str | None = Query(default=None),
    runtime_profile: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AdminReleaseSetPage:
    records = release_repo(request).list_release_sets(environment, runtime_profile)
    selected, page = paginate(records, limit, cursor)
    items = [release_set_projection(item) for item in selected]
    return AdminReleaseSetPage(items=items, page=page)


@router.post(
    '/release-sets',
    response_model=ReleaseSetRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_release_set(
    request: Request,
    payload: ReleaseSetCreate,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    return _idempotent(
        request,
        principal,
        idempotency_key,
        'POST /internal/v1/admin/release-sets',
        payload.model_dump(mode='json'),
        lambda: release_sets.create(
            release_repo(request),
            configuration_repo(request),
            knowledge_repo(request),
            payload,
            principal.subject,
        ),
        status.HTTP_201_CREATED,
    )


@router.get('/release-sets/{release_set_id}', response_model=AdminReleaseSetProjection)
def get_release_set(
    request: Request,
    release_set_id: str,
    _principal: Principal = Depends(require_administrator),
) -> AdminReleaseSetProjection:
    return release_set_projection(release_sets.read(release_repo(request), release_set_id))


@router.post('/release-sets/{release_set_id}/validate', response_model=ReleaseSetRecord)
def validate_release_set(
    request: Request,
    release_set_id: str,
    payload: ReleaseSetValidationRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected = parse_if_match(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/release-sets/{release_set_id}/validate',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: release_sets.validate(
            release_repo(request),
            configuration_repo(request),
            knowledge_repo(request),
            release_set_id,
            payload,
            principal.subject,
            expected,
        ),
    )


@router.post('/release-sets/{release_set_id}/publish', response_model=ReleaseSetRecord)
def publish_release_set(
    request: Request,
    release_set_id: str,
    payload: ReleaseSetTransitionRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected = parse_if_match(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/release-sets/{release_set_id}/publish',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: release_sets.publish(
            release_repo(request), release_set_id, payload.reason, principal.subject, expected
        ),
    )


@router.post('/release-sets/{release_set_id}/rollback', response_model=ReleaseSetRecord)
def rollback_release_set(
    request: Request,
    release_set_id: str,
    payload: ReleaseSetTransitionRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> BaseModel | JSONResponse:
    expected = parse_if_match(if_match)
    if payload.rollback_target is None:
        raise release_sets._error(400, 'ROLLBACK_TARGET_REQUIRED', 'A rollback target is required.')
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/release-sets/{release_set_id}/rollback',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: release_sets.rollback(
            release_repo(request),
            release_set_id,
            payload.rollback_target or '',
            payload.reason,
            principal.subject,
            expected,
        ),
    )


@router.get('/release-sets/{release_set_id}/audit', response_model=dict)
def audit_release_set(
    request: Request,
    release_set_id: str,
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    return {
        'items': release_sets.audit(release_repo(request), release_set_id),
        'page': {'next_cursor': None},
    }


@router.get('/runtime-snapshots', response_model=RuntimeSnapshot)
def get_runtime_snapshot(
    request: Request,
    environment: str = Query(min_length=1),
    runtime_profile: str = Query(min_length=1),
    _principal: Principal = Depends(require_administrator),
) -> RuntimeSnapshot:
    return release_sets.snapshot(
        release_repo(request),
        configuration_repo(request),
        knowledge_repo(request),
        environment,
        runtime_profile,
    )
