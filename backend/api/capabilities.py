from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.auth import Principal, require_claimant
from backend.core.config import AgentRuntimeProfile


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


router = APIRouter(prefix='/api/v1/claims', tags=['capabilities'])


@router.get('/capabilities', response_model=RuntimeCapabilitiesResponse)
def capabilities(
    request: Request,
    _: Principal = Depends(require_claimant),
) -> RuntimeCapabilitiesResponse:
    settings = request.app.state.settings
    models: list[ModelCapability] = []
    if settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY:
        models.append(
            ModelCapability(
                id=settings.model_identifier,
                label=settings.model_identifier,
                protocol=settings.model_protocol_adapter,
                structured_output=settings.model_supports_structured_output,
                tools=settings.model_supports_tools,
            )
        )
    return RuntimeCapabilitiesResponse(
        claim_types=['motor', 'home', 'contents'],
        models=models,
    )
