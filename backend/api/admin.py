from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status

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
from backend.repositories.configuration import ConfigurationRepository
from backend.services import configuration as service

router = APIRouter(prefix='/internal/v1/admin', tags=['administration'])


def repo(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


def revision(value: str | None) -> int:
    if value is None:
        raise ValueError('If-Match is required.')
    return int(value.strip('"'))


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
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord:
    return service.create(repo(request), payload, principal.subject)


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
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord:
    try:
        expected = revision(if_match)
    except (ValueError, TypeError):
        raise service._error(400, 'REVISION_REQUIRED', 'If-Match revision is required.') from None
    return service.patch(repo(request), configuration_id, payload, principal.subject, expected)


@router.post('/configurations/{configuration_id}/validate', response_model=ConfigurationRecord)
def validate_configuration(
    request: Request,
    configuration_id: str,
    payload: ValidationRequest,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord:
    try:
        expected = revision(if_match)
    except (ValueError, TypeError):
        raise service._error(400, 'REVISION_REQUIRED', 'If-Match revision is required.') from None
    return service.validate(repo(request), configuration_id, payload, principal.subject, expected)


@router.post('/configurations/{configuration_id}/publish', response_model=ConfigurationRecord)
def publish_configuration(
    request: Request,
    configuration_id: str,
    payload: TransitionRequest,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord:
    try:
        expected = revision(if_match)
    except (ValueError, TypeError):
        raise service._error(400, 'REVISION_REQUIRED', 'If-Match revision is required.') from None
    return service.publish(repo(request), configuration_id, payload, principal.subject, expected)


@router.post('/configurations/{configuration_id}/withdraw', response_model=ConfigurationRecord)
def withdraw_configuration(
    request: Request,
    configuration_id: str,
    payload: TransitionRequest,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord:
    try:
        expected = revision(if_match)
    except (ValueError, TypeError):
        raise service._error(400, 'REVISION_REQUIRED', 'If-Match revision is required.') from None
    return service.withdraw(repo(request), configuration_id, payload, principal.subject, expected)


@router.post('/configurations/{configuration_id}/rollback', response_model=ConfigurationRecord)
def rollback_configuration(
    request: Request,
    configuration_id: str,
    payload: TransitionRequest,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord:
    try:
        expected = revision(if_match)
    except (ValueError, TypeError):
        raise service._error(400, 'REVISION_REQUIRED', 'If-Match revision is required.') from None
    return service.rollback(repo(request), configuration_id, payload, principal.subject, expected)


@router.get('/configurations/{configuration_id}/audit', response_model=AuditPage)
def audit_configuration(
    request: Request, configuration_id: str, _principal: Principal = Depends(require_administrator)
) -> AuditPage:
    items: list[AuditEvent] = service.audit(repo(request), configuration_id)
    return AuditPage(items=items, page={'next_cursor': None})
