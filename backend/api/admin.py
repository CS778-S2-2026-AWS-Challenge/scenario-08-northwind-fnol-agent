from collections.abc import Callable
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from backend.core.auth import Principal, require_administrator
from backend.domain.configuration import (
    AuditEvent,
    AuditPage,
    ConfigurationCreate,
    ConfigurationPatch,
    ConfigurationRecord,
    TransitionRequest,
    ValidationRequest,
)
from backend.repositories.configuration import (
    ConfigurationIdempotencyRecord,
    ConfigurationRepository,
)
from backend.services import configuration as service
from backend.services.support import parse_if_match, request_fingerprint, require_idempotency_key

router = APIRouter(prefix='/internal/v1/admin', tags=['administration'])


def repo(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


def _idempotent(
    request: Request,
    principal: Principal,
    key: str | None,
    route: str,
    payload: object,
    operation: Callable[[], ConfigurationRecord],
    success_status: int = status.HTTP_200_OK,
) -> ConfigurationRecord | JSONResponse:
    idempotency_key = require_idempotency_key(key)
    fingerprint = request_fingerprint(payload)
    repository = repo(request)
    existing = repository.find_idempotency(principal.subject, route, idempotency_key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise service._error(
                409,
                'IDEMPOTENCY_CONFLICT',
                'Idempotency-Key was reused with a different request.',
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    result = operation()
    repository.save_idempotency(
        ConfigurationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=idempotency_key,
            fingerprint=fingerprint,
            response=result.model_dump(mode='json'),
            status_code=success_status,
        )
    )
    return result


def _expected_revision(value: str | None) -> int:
    return parse_if_match(value)


@router.get('/configurations', response_model=dict)
def list_configurations(
    request: Request,
    domain: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    return {'items': repo(request).list_configurations(domain), 'page': {'next_cursor': None}}


@router.post(
    '/configurations', response_model=ConfigurationRecord, status_code=status.HTTP_201_CREATED
)
def create_configuration(
    request: Request,
    payload: ConfigurationCreate,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    return _idempotent(
        request,
        principal,
        idempotency_key,
        'POST /internal/v1/admin/configurations',
        payload.model_dump(mode='json'),
        lambda: service.create(repo(request), payload, principal.subject),
        status.HTTP_201_CREATED,
    )


@router.get('/configurations/{configuration_id}', response_model=ConfigurationRecord)
def get_configuration(
    request: Request, configuration_id: str, _principal: Principal = Depends(require_administrator)
) -> ConfigurationRecord:
    return service.read(repo(request), configuration_id)


@router.patch('/configurations/{configuration_id}', response_model=ConfigurationRecord)
def patch_configuration(
    request: Request,
    configuration_id: str,
    payload: ConfigurationPatch,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    expected = _expected_revision(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'PATCH /internal/v1/admin/configurations/{configuration_id}',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: service.patch(
            repo(request), configuration_id, payload, principal.subject, expected
        ),
    )


@router.post('/configurations/{configuration_id}/validate', response_model=ConfigurationRecord)
def validate_configuration(
    request: Request,
    configuration_id: str,
    payload: ValidationRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    expected = _expected_revision(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/configurations/{configuration_id}/validate',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: service.validate(
            repo(request), configuration_id, payload, principal.subject, expected
        ),
    )


@router.post('/configurations/{configuration_id}/publish', response_model=ConfigurationRecord)
def publish_configuration(
    request: Request,
    configuration_id: str,
    payload: TransitionRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    expected = _expected_revision(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/configurations/{configuration_id}/publish',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: service.publish(
            repo(request), configuration_id, payload, principal.subject, expected
        ),
    )


@router.post('/configurations/{configuration_id}/withdraw', response_model=ConfigurationRecord)
def withdraw_configuration(
    request: Request,
    configuration_id: str,
    payload: TransitionRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    expected = _expected_revision(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/configurations/{configuration_id}/withdraw',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: service.withdraw(
            repo(request), configuration_id, payload, principal.subject, expected
        ),
    )


@router.post('/configurations/{configuration_id}/rollback', response_model=ConfigurationRecord)
def rollback_configuration(
    request: Request,
    configuration_id: str,
    payload: TransitionRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    expected = _expected_revision(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/configurations/{configuration_id}/rollback',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: service.rollback(
            repo(request), configuration_id, payload, principal.subject, expected
        ),
    )


@router.get('/configurations/{configuration_id}/audit', response_model=AuditPage)
def audit_configuration(
    request: Request, configuration_id: str, _principal: Principal = Depends(require_administrator)
) -> AuditPage:
    items: list[AuditEvent] = service.audit(repo(request), configuration_id)
    return AuditPage(items=items, page={'next_cursor': None})
