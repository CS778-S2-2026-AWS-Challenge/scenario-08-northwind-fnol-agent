from typing import cast

from fastapi import APIRouter, Depends, Request, status

from backend.core.auth import Principal, require_staff
from backend.domain.knowledge import KnowledgeRetriever
from backend.domain.staff_agent import (
    CreateStaffAgentMessageRequest,
    CreateStaffAgentSessionRequest,
    StaffAgentMessagesResponse,
    StaffAgentSession,
    StaffAgentSessionsResponse,
    StaffAgentTurnResponse,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.staff_agent import (
    StaffAgentTurnProvider,
    create_staff_agent_session,
    list_staff_agent_messages,
    list_staff_agent_sessions,
    submit_staff_agent_message,
)

router = APIRouter(prefix='/api/v1/workbench/agent', tags=['workbench-agent'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def retriever_for(request: Request) -> KnowledgeRetriever:
    return cast(KnowledgeRetriever, request.app.state.knowledge_retriever)


def provider_for(request: Request) -> StaffAgentTurnProvider | None:
    return cast(StaffAgentTurnProvider | None, request.app.state.staff_agent_turn_provider)


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
    return create_staff_agent_session(repository_for(request), principal, payload)


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
    )
