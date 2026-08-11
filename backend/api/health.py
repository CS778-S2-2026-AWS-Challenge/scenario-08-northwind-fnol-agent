from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

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
def readiness() -> ReadinessResponse:
    return ReadinessResponse(
        status='degraded',
        checks={
            'persistence': 'not_configured',
            'agent': 'not_configured',
            'policy': 'not_configured',
            'claim_history': 'not_configured',
            'claims_service': 'not_configured',
            'evidence_storage': 'not_configured',
        },
        checked_at=datetime.now(UTC),
    )
