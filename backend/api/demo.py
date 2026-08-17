from fastapi import APIRouter, Depends, Request

from backend.core.auth import Principal, require_staff
from backend.domain.models import DemoResetResponse, DemoSeedResponse
from backend.services.demo_reset import reset_demo_components
from backend.services.demo_seed import HANDOFF_QUEUE_SCENARIO_IDS, seed_handoff_queue_scenarios

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


@router.post('/seed-scenarios', response_model=DemoSeedResponse)
def seed_scenarios(
    request: Request,
    _principal: Principal = Depends(require_staff),
) -> DemoSeedResponse:
    claim_ids = seed_handoff_queue_scenarios(request.app.state.claim_repository)
    return DemoSeedResponse(
        status='seeded',
        scenario_ids=list(HANDOFF_QUEUE_SCENARIO_IDS),
        claim_ids=claim_ids,
    )
