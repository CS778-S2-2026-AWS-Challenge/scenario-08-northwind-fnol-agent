from typing import cast

from fastapi import APIRouter, Depends, Request, status

from backend.core.auth import Principal, require_staff
from backend.core.config import AgentRuntimeProfile
from backend.domain.configuration import ModelRuntimeConfiguration
from backend.domain.knowledge import KnowledgeRetriever
from backend.domain.models import ContractModel
from backend.domain.staff_agent import (
    CreateStaffAgentMessageRequest,
    CreateStaffAgentSessionRequest,
    StaffAgentMessagesResponse,
    StaffAgentSession,
    StaffAgentSessionsResponse,
    StaffAgentTurnResponse,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.knowledge_manifest import approved_version_for_product
from backend.services.model_profiles import model_catalog, select_model_profile
from backend.services.staff_agent import (
    StaffAgentTurnProvider,
    create_staff_agent_session,
    list_staff_agent_messages,
    list_staff_agent_sessions,
    submit_staff_agent_message,
)


class StaffAgentModelCapability(ContractModel):
    id: str
    label: str
    protocol: str
    structured_output: bool
    tools: bool


class StaffAgentCapabilitiesResponse(ContractModel):
    models: list[StaffAgentModelCapability]
    default_model_profile_id: str | None = None


router = APIRouter(prefix='/api/v1/workbench/agent', tags=['workbench-agent'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def retriever_for(request: Request) -> KnowledgeRetriever:
    return cast(KnowledgeRetriever, request.app.state.knowledge_retriever)


def provider_for(request: Request) -> StaffAgentTurnProvider | None:
    return cast(StaffAgentTurnProvider | None, request.app.state.staff_agent_turn_provider)


def knowledge_version_for(request: Request, product: str) -> str | None:
    """Resolve the active approved knowledge version for one product family.

    Args:
        request: FastAPI request carrying the runtime configuration resolver.
        product: Canonical product family to resolve.

    Returns:
        The selected version or the fixture manifest version.

    Raises:
        RuntimeConfigurationResolutionError: If an active release cannot provide
            a version for the requested product.
    """

    selected = request.app.state.runtime_configuration_resolver.resolve_knowledge(product)
    return selected.version if selected is not None else approved_version_for_product(product)


@router.post(
    '/sessions',
    response_model=StaffAgentSession,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: CreateStaffAgentSessionRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffAgentSession:
    return create_staff_agent_session(
        repository_for(request),
        principal,
        payload,
        model_profile_selector=lambda requested: select_model_profile(request, requested),
    )


@router.get('/capabilities', response_model=StaffAgentCapabilitiesResponse)
def read_capabilities(
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffAgentCapabilitiesResponse:
    if request.app.state.settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
        return StaffAgentCapabilitiesResponse(models=[])
    models = [
        StaffAgentModelCapability(
            id=configuration.profile_id,
            label=configuration.model_identifier,
            protocol=configuration.protocol,
            structured_output=configuration.structured_output,
            tools=configuration.tools,
        )
        for record in model_catalog(request)
        if (configuration := ModelRuntimeConfiguration.model_validate(record.values))
    ]
    return StaffAgentCapabilitiesResponse(
        models=models,
        default_model_profile_id=(
            'qwen-local'
            if any(item.id == 'qwen-local' for item in models)
            else (models[0].id if models else None)
        ),
    )


@router.get('/sessions', response_model=StaffAgentSessionsResponse)
def read_sessions(
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffAgentSessionsResponse:
    return list_staff_agent_sessions(repository_for(request), principal)


@router.get(
    '/sessions/{session_id}/messages',
    response_model=StaffAgentMessagesResponse,
)
def read_messages(
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffAgentMessagesResponse:
    return list_staff_agent_messages(repository_for(request), principal, session_id)


@router.post(
    '/sessions/{session_id}/messages',
    response_model=StaffAgentTurnResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    session_id: str,
    payload: CreateStaffAgentMessageRequest,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> StaffAgentTurnResponse:
    return submit_staff_agent_message(
        repository_for(request),
        retriever_for(request),
        provider_for(request),
        principal,
        session_id,
        payload,
        knowledge_version_for=lambda product: knowledge_version_for(request, product),
    )
