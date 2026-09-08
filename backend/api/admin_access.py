from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from backend.core.auth import Principal, require_administrator
from backend.domain.configuration import ConfigurationCreate, ConfigurationRecord
from backend.repositories.configuration import (
    ConfigurationIdempotencyRecord,
    ConfigurationRepository,
)
from backend.services import configuration
from backend.services.support import paginate, request_fingerprint, require_idempotency_key

router = APIRouter(prefix='/internal/v1/admin/access', tags=['administration'])


def repository_for(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


@router.get('/policies', response_model=dict)
def list_policies(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> dict[str, object]:
    records = repository_for(request).list_configurations('access')
    items, page = paginate(records, limit, cursor)
    return {'items': items, 'page': page}


@router.post('/policies', response_model=ConfigurationRecord, status_code=201)
def create_policy(
    payload: ConfigurationCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    if payload.domain != 'access':
        from backend.core.errors import ApiError

        raise ApiError(
            status_code=422,
            code='ACCESS_POLICY_INVALID',
            message='Access policy requests must use the access configuration domain.',
        )
    key = require_idempotency_key(idempotency_key)
    route = 'POST /internal/v1/admin/access/policies'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    repository = repository_for(request)
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            from backend.core.errors import ApiError

            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Idempotency-Key was reused with a different request.',
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    record = configuration.create(repository, payload, principal.subject)
    repository.save_idempotency(
        ConfigurationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            response=record.model_dump(mode='json'),
            status_code=201,
        )
    )
    return record


__all__ = ['router']
