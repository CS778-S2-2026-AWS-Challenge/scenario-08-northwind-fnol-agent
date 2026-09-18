from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth import Principal, require_claimant
from backend.core.config import AgentRuntimeProfile
from backend.domain.configuration import ModelRuntimeConfiguration
from backend.services.model_profiles import (
    default_model_profile_id,
    model_catalog,
    model_runtime_status,
)


class ModelCapability(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    structured_output: bool
    tools: bool
    image_input: bool
    document_input: bool
    published: bool = True
    runtime_ready: bool
    healthy: bool | None = None
    unavailable_reason: str | None = None
    availability: str = Field(default='available', pattern=r'^(available|unavailable)$')


class RuntimeCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    claim_types: list[str]
    models: list[ModelCapability]
    default_model_profile_id: str | None = None


router = APIRouter(prefix='/api/v1/claims', tags=['capabilities'])


@router.get('/capabilities', response_model=RuntimeCapabilitiesResponse)
def capabilities(
    request: Request,
    _: Principal = Depends(require_claimant),
) -> RuntimeCapabilitiesResponse:
    settings = request.app.state.settings
    models: list[ModelCapability] = []
    catalog = []
    if settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY:
        catalog = model_catalog(request)
        for record in catalog:
            configuration = ModelRuntimeConfiguration.model_validate(record.values)
            runtime_status = model_runtime_status(configuration)
            models.append(
                ModelCapability(
                    id=configuration.profile_id,
                    label=configuration.model_identifier,
                    protocol=configuration.protocol,
                    structured_output=configuration.structured_output,
                    tools=configuration.tools,
                    image_input=configuration.image_input,
                    document_input=configuration.document_input,
                    published=runtime_status.published,
                    runtime_ready=runtime_status.runtime_ready,
                    healthy=runtime_status.healthy,
                    unavailable_reason=runtime_status.unavailable_reason,
                    availability=('available' if runtime_status.runtime_ready else 'unavailable'),
                )
            )
    return RuntimeCapabilitiesResponse(
        claim_types=['motor', 'home', 'contents'],
        models=models,
        default_model_profile_id=default_model_profile_id(request, catalog) if models else None,
    )
