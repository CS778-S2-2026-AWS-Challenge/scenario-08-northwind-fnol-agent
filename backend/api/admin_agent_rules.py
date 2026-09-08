from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from backend.core.auth import Principal, require_administrator
from backend.core.errors import ApiError
from backend.domain.agent_rule_admin import AgentRuleComponent, AgentRuleCreate, AgentRulePage
from backend.domain.configuration import (
    ConfigurationCreate,
    ConfigurationImpact,
    ConfigurationRecord,
)
from backend.repositories.configuration import (
    ConfigurationIdempotencyRecord,
    ConfigurationRepository,
)
from backend.services import configuration as service
from backend.services.support import paginate, request_fingerprint, require_idempotency_key

router = APIRouter(prefix='/internal/v1/admin/agent-rules', tags=['administration'])

_DOMAINS = {
    AgentRuleComponent.INSTRUCTIONS: 'agent_instruction',
    AgentRuleComponent.TOOL_PERMISSIONS: 'agent_tool_policy',
    AgentRuleComponent.CONTROLLED_RULES: 'agent_rule',
    AgentRuleComponent.FEATURE_SETTINGS: 'feature',
}


def repository_for(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


@router.get('', response_model=AgentRulePage)
def list_components(
    request: Request,
    component: AgentRuleComponent | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    _principal: Principal = Depends(require_administrator),
) -> AgentRulePage:
    domains = {_DOMAINS[component]} if component is not None else set(_DOMAINS.values())
    records = [
        item for domain in domains for item in repository_for(request).list_configurations(domain)
    ]
    records.sort(key=lambda item: (item.domain, item.updated_at), reverse=True)
    items, page = paginate(records, limit, cursor)
    return AgentRulePage(items=items, page=page)


@router.post(
    '/{component}', response_model=ConfigurationRecord, status_code=status.HTTP_201_CREATED
)
def create_component(
    component: AgentRuleComponent,
    payload: AgentRuleCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(require_administrator),
) -> ConfigurationRecord | JSONResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'POST /internal/v1/admin/agent-rules/{component.value}'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    repository = repository_for(request)
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='Idempotency-Key was reused with a different request.',
            )
        return JSONResponse(status_code=existing.status_code, content=existing.response)
    effective_impact = payload.impact
    if component is not AgentRuleComponent.FEATURE_SETTINGS:
        effective_impact = ConfigurationImpact.HIGH
    record = service.create(
        repository,
        ConfigurationCreate(
            domain=_DOMAINS[component],
            impact=effective_impact,
            values=payload.values.model_dump(mode='python'),
            reason=payload.reason,
        ),
        principal.subject,
    )
    repository.save_idempotency(
        ConfigurationIdempotencyRecord(
            actor=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            response=record.model_dump(mode='json'),
            status_code=status.HTTP_201_CREATED,
        )
    )
    return record
