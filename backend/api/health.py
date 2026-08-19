from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.adapters.handoff_dispatch import HandoffDispatchAdapter
from backend.adapters.policy_history import PolicyHistoryAdapter

router = APIRouter(tags=['health'])


class LivenessResponse(BaseModel):
    status: Literal['ok']


class ReadinessResponse(BaseModel):
    status: Literal['ok', 'degraded', 'unavailable']
    checks: dict[str, str]
    checked_at: datetime


@router.get('/health', response_model=LivenessResponse, deprecated=True)
@router.get('/health/live', response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return LivenessResponse(status='ok')


@router.get('/health/ready', response_model=ReadinessResponse)
def readiness(request: Request) -> ReadinessResponse:
    # Retrieval reports what the configured adapter actually says, so an
    # unavailable provider is visible here rather than only at call time.
    retrieval = cast(
        PolicyHistoryAdapter, request.app.state.policy_history_adapter
    ).connection_status()
    handoff_dispatch = cast(
        HandoffDispatchAdapter, request.app.state.handoff_dispatch_adapter
    ).connection_status()
    return ReadinessResponse(
        status='degraded',
        checks={
            'persistence': 'not_configured',
            'agent': 'not_configured',
            'policy': retrieval,
            'claim_history': retrieval,
            'aws_policy_history': 'pending_confirmation',
            'claims_service': 'using_fixture',
            'aws_claims_service': 'pending_confirmation',
            'handoff_dispatch': handoff_dispatch,
            'evidence_storage': 'not_configured',
        },
        checked_at=datetime.now(UTC),
    )
