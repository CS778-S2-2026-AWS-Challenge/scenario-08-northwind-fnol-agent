from fastapi import APIRouter, Depends, Request

from backend.core.auth import Principal, require_staff
from backend.domain.models import DemoResetResponse
from backend.services.demo_reset import reset_demo_components

router = APIRouter(prefix='/api/v1/workbench/demo', tags=['workbench-demo'])


@router.post('/reset', response_model=DemoResetResponse)
def reset_demo(
    request: Request,
    _principal: Principal = Depends(require_staff),
) -> DemoResetResponse:
    cleared = reset_demo_components(
        {
            'repository': request.app.state.claim_repository,
            'claims adapter': request.app.state.claims_service_adapter,
            'assessor adapter': request.app.state.assessor_service_adapter,
            'evidence storage': request.app.state.evidence_storage,
        }
    )
    return DemoResetResponse(status='reset', cleared=cleared)
