from typing import cast

from fastapi import APIRouter, Depends, Request, Response, status

from backend.adapters.claims_service import AssessorServiceAdapter, ClaimsServiceAdapter
from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.core.auth import Principal, require_integration_service
from backend.domain.models import (
    AssessorRoutingResult,
    CreateExternalClaimRequest,
    ExternalClaimResult,
    RouteAssessorRequest,
)
from backend.domain.retrieval import (
    ClaimHistorySearchRequest,
    ClaimHistorySearchResponse,
    PolicySearchRequest,
    PolicySearchResponse,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.integrations import create_external_claim, route_assessor
from backend.services.retrieval import search_claim_history, search_policy

router = APIRouter(prefix='/internal/v1', tags=['internal-integrations'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def claims_adapter_for(request: Request) -> ClaimsServiceAdapter:
    return cast(ClaimsServiceAdapter, request.app.state.claims_service_adapter)


def assessor_adapter_for(request: Request) -> AssessorServiceAdapter:
    return cast(AssessorServiceAdapter, request.app.state.assessor_service_adapter)


def policy_history_adapter_for(request: Request) -> PolicyHistoryAdapter:
    return cast(PolicyHistoryAdapter, request.app.state.policy_history_adapter)


@router.post('/policy/search', response_model=PolicySearchResponse)
def search_policy_integration(
    payload: PolicySearchRequest,
    request: Request,
    _principal: Principal = Depends(require_integration_service),
) -> PolicySearchResponse:
    return search_policy(
        repository_for(request),
        policy_history_adapter_for(request),
        payload,
    )


@router.post('/claim-history/search', response_model=ClaimHistorySearchResponse)
def search_claim_history_integration(
    payload: ClaimHistorySearchRequest,
    request: Request,
    _principal: Principal = Depends(require_integration_service),
) -> ClaimHistorySearchResponse:
    return search_claim_history(
        repository_for(request),
        policy_history_adapter_for(request),
        payload,
    )


@router.post('/claims/create', response_model=ExternalClaimResult)
def create_claim_integration(
    payload: CreateExternalClaimRequest,
    request: Request,
    response: Response,
    _principal: Principal = Depends(require_integration_service),
) -> ExternalClaimResult:
    result, replayed = create_external_claim(
        repository_for(request),
        claims_adapter_for(request),
        payload,
    )
    response.status_code = status.HTTP_200_OK if replayed else status.HTTP_201_CREATED
    return result


@router.post('/assessors/route', response_model=AssessorRoutingResult)
def route_assessor_integration(
    payload: RouteAssessorRequest,
    request: Request,
    response: Response,
    _principal: Principal = Depends(require_integration_service),
) -> AssessorRoutingResult:
    result, replayed = route_assessor(
        repository_for(request),
        assessor_adapter_for(request),
        payload,
    )
    response.status_code = status.HTTP_200_OK if replayed else status.HTTP_201_CREATED
    return result
