from fastapi import APIRouter, Depends, Header, Request

from backend.core.auth import Principal, require_staff
from backend.core.errors import ApiError
from backend.domain.models import DemoResetResponse, DemoSeedResponse
from backend.services.demo_reset import reset_demo_components
from backend.services.demo_seed import seed_validation_scenarios, seed_workbench_demo_scenarios

router = APIRouter(prefix='/api/v1/workbench/demo', tags=['workbench-demo'])


def require_local_demo(request: Request) -> None:
    if request.app.state.settings.environment not in {'development', 'test'}:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The demo endpoint is not available in this environment.',
        )


@router.post('/reset', response_model=DemoResetResponse)
def reset_demo(
    request: Request,
    _principal: Principal = Depends(require_staff),
) -> DemoResetResponse:
    require_local_demo(request)
    cleared = reset_demo_components(
        {
            'repository': request.app.state.claim_repository,
            'claims adapter': request.app.state.claims_service_adapter,
            'assessor adapter': request.app.state.assessor_service_adapter,
            'evidence storage': request.app.state.evidence_storage,
            'retrieval adapter': request.app.state.policy_history_adapter,
            'handoff dispatch': request.app.state.handoff_dispatch_adapter,
        }
    )
    return DemoResetResponse(status='reset', cleared=cleared)


@router.post('/seed-scenarios', response_model=DemoSeedResponse)
def seed_scenarios(
    request: Request,
    _principal: Principal = Depends(require_staff),
) -> DemoSeedResponse:
    require_local_demo(request)
    result = seed_workbench_demo_scenarios(request.app.state.claim_repository)
    return DemoSeedResponse(
        status='seeded',
        scenario_ids=list(result.scenario_ids),
        claim_ids=list(result.claim_ids),
    )


@router.post('/seed-validation', response_model=DemoSeedResponse)
def seed_validation(
    request: Request,
    principal: Principal = Depends(require_staff),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> DemoSeedResponse:
    require_local_demo(request)
    return seed_validation_scenarios(
        request.app.state.claim_repository,
        request.app.state.identity_repository,
        request.app.state.staff_identity_repository,
        principal.subject,
        idempotency_key,
    )
