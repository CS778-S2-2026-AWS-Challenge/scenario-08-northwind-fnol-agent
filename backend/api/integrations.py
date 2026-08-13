from typing import cast

from fastapi import APIRouter, Depends, Request, Response, status

from backend.adapters.claims_service import AssessorServiceAdapter, ClaimsServiceAdapter
from backend.core.auth import Principal, require_integration_service
from backend.domain.models import (
    AssessorRoutingResult,
    CreateExternalClaimRequest,
    ExternalClaimResult,
    RouteAssessorRequest,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.integrations import create_external_claim, route_assessor

router = APIRouter(prefix='/internal/v1', tags=['internal-integrations'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def claims_adapter_for(request: Request) -> ClaimsServiceAdapter:
    return cast(ClaimsServiceAdapter, request.app.state.claims_service_adapter)


def assessor_adapter_for(request: Request) -> AssessorServiceAdapter:
    return cast(AssessorServiceAdapter, request.app.state.assessor_service_adapter)


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
