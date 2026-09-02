from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.adapters.handoff_dispatch import HandoffDispatchAdapter
from backend.core.runtime_profiles import DataRuntimeBundle

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
    handoff_dispatch = cast(
        HandoffDispatchAdapter, request.app.state.handoff_dispatch_adapter
    ).connection_status()
    data_runtime = cast(DataRuntimeBundle, request.app.state.data_runtime_bundle)
    data_checks = data_runtime.readiness_checks()
    agent_runtime_status = cast(str, request.app.state.agent_runtime_status)
    status: Literal['degraded', 'unavailable'] = (
        'unavailable' if 'unavailable' in data_checks.values() else 'degraded'
    )
    return ReadinessResponse(
        status=status,
        checks={
            **data_checks,
            'data_runtime_profile': data_runtime.profile.value,
            'object_storage_adapter': request.app.state.settings.object_storage_adapter.value,
            'agent': agent_runtime_status,
            'aws_policy_history': 'pending_confirmation',
            'claims_service': 'using_fixture',
            'aws_claims_service': 'pending_confirmation',
            'handoff_dispatch': handoff_dispatch,
            'aws_evidence_storage': 'pending_confirmation',
        },
        checked_at=datetime.now(UTC),
    )
