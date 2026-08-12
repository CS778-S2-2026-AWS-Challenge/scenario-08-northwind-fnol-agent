from fastapi import APIRouter, Depends, Query, Request

from backend.core.auth import Principal, require_staff
from backend.domain.models import WorkbenchClaimDetail, WorkbenchClaimListResponse
from backend.repositories.protocols import PersistenceRepository
from backend.services.workbench import get_workbench_claim, list_workbench_claims

router = APIRouter(prefix='/api/v1/workbench/claims', tags=['workbench'])


def repository_for(request: Request) -> PersistenceRepository:
    return request.app.state.claim_repository


@router.get('', response_model=WorkbenchClaimListResponse)
def read_workbench_claims(
    request: Request,
    principal: Principal = Depends(require_staff),
    view: str | None = Query(default=None),
) -> WorkbenchClaimListResponse:
    return list_workbench_claims(repository_for(request), principal, view=view)


@router.get('/{claim_id}', response_model=WorkbenchClaimDetail)
def read_workbench_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> WorkbenchClaimDetail:
    return get_workbench_claim(repository_for(request), principal, claim_id)
