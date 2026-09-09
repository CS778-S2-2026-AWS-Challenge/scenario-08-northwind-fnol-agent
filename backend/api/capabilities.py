from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth import Principal, require_claimant
from backend.core.config import AgentRuntimeProfile
from backend.domain.configuration import ModelRuntimeConfiguration
from backend.services.model_profiles import model_catalog


class ModelCapability(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    structured_output: bool
    tools: bool


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
    if settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY:
        for record in model_catalog(request):
            configuration = ModelRuntimeConfiguration.model_validate(record.values)
            models.append(
                ModelCapability(
                    id=configuration.profile_id,
                    label=configuration.model_identifier,
                    protocol=configuration.protocol,
                    structured_output=configuration.structured_output,
                    tools=configuration.tools,
                )
            )
    return RuntimeCapabilitiesResponse(
        claim_types=['motor', 'home', 'contents'],
        models=models,
        default_model_profile_id=(
            'qwen-local'
            if any(model.id == 'qwen-local' for model in models)
            else (models[0].id if models else None)
        ),
    )
