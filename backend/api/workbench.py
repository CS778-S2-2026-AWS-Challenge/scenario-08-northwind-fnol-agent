from typing import cast

from fastapi import APIRouter, Depends, Request

from backend.core.auth import Principal, require_staff
from backend.domain.models import WorkbenchClaimDetail
from backend.repositories.protocols import PersistenceRepository
from backend.services.workbench import get_workbench_claim_detail

router = APIRouter(prefix='/api/v1/workbench/claims', tags=['workbench'])


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


@router.get('/{claim_id}', response_model=WorkbenchClaimDetail)
def read_workbench_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_staff),
) -> WorkbenchClaimDetail:
    return get_workbench_claim_detail(repository_for(request), principal, claim_id)
