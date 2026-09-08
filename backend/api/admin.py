from collections.abc import Callable
from typing import TypeVar, cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.core.auth import Principal, require_administrator
from backend.domain.configuration import (
    AdminConfigurationPage,
    AdminConfigurationProjection,
    ApprovalRequest,
    AuditEvent,
    AuditPage,
    ConfigurationApprovalRecord,
    ConfigurationCreate,
    ConfigurationPatch,
    ConfigurationRecord,
    ModelRuntimeBinding,
    TransitionRequest,
    ValidationRequest,
)
from backend.domain.model_gateway import CLAIMANT_AGENT_PRIVACY_CLASS, CLAIMANT_AGENT_PURPOSE
from backend.prompts import MOTOR_CLAIMANT_PROMPT_ID
from backend.repositories.configuration import (
    ConfigurationIdempotencyRecord,
    ConfigurationRepository,
)
from backend.services import configuration as service
from backend.services.admin_action_projection import configuration_projection
from backend.services.support import (
    paginate,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

router = APIRouter(prefix='/internal/v1/admin', tags=['administration'])
ModelT = TypeVar('ModelT', bound=BaseModel)


def repo(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


def _model_runtime_binding(request: Request) -> ModelRuntimeBinding:
    settings = request.app.state.settings
    return ModelRuntimeBinding(
        protocol=settings.model_protocol_adapter,
        base_url=settings.model_base_url,
        credential_environment_variable=settings.model_api_key_env,
        purpose=CLAIMANT_AGENT_PURPOSE,
        privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
        prompt_version=MOTOR_CLAIMANT_PROMPT_ID,
        structured_output=True,
    )


def _idempotent(
    request: Request,
    principal: Principal,
    key: str | None,
    route: str,
    payload: object,
    operation: Callable[[], ModelT],
    success_status: int = status.HTTP_200_OK,
) -> ModelT | JSONResponse:
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


@router.get('/configurations', response_model=AdminConfigurationPage)
def list_configurations(
    request: Request,
    domain: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AdminConfigurationPage:
    records, page = paginate(repo(request).list_configurations(domain), limit, cursor)
    items = [
        configuration_projection(
            item,
            _principal.subject,
            repo(request).approvals(item.configuration_id, item.revision),
        )
        for item in records
    ]
    return AdminConfigurationPage(items=items, page=page)


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


@router.get('/configurations/{configuration_id}', response_model=AdminConfigurationProjection)
def get_configuration(
    request: Request, configuration_id: str, principal: Principal = Depends(require_administrator)
) -> AdminConfigurationProjection:
    record = service.read(repo(request), configuration_id)
    return configuration_projection(
        record,
        principal.subject,
        repo(request).approvals(record.configuration_id, record.revision),
    )


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
            repo(request),
            configuration_id,
            payload,
            principal.subject,
            expected,
            _model_runtime_binding(request),
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


@router.post(
    '/configurations/{configuration_id}/approval',
    response_model=ConfigurationApprovalRecord,
)
def approve_configuration(
    request: Request,
    configuration_id: str,
    payload: ApprovalRequest,
    if_match: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationApprovalRecord | JSONResponse:
    expected = _expected_revision(if_match)
    return _idempotent(
        request,
        principal,
        idempotency_key,
        f'POST /internal/v1/admin/configurations/{configuration_id}/approval',
        {'payload': payload.model_dump(mode='json'), 'revision': expected},
        lambda: service.approve(
            repo(request), configuration_id, payload, principal.subject, expected
        ),
    )


@router.get('/configurations/{configuration_id}/approvals', response_model=dict)
def list_configuration_approvals(
    request: Request,
    configuration_id: str,
    revision: int | None = Query(default=None, ge=1),
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    service.read(repo(request), configuration_id)
    return {
        'items': repo(request).approvals(configuration_id, revision),
        'page': {'next_cursor': None},
    }


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
