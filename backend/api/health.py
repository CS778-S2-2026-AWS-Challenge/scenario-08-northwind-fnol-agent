from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.adapters.handoff_dispatch import HandoffDispatchAdapter
from backend.core.runtime_profiles import DataRuntimeBundle
from backend.services.runtime_configuration import RuntimeConfigurationResolutionError

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
    resolver = getattr(request.app.state, 'runtime_configuration_resolver', None)
    if resolver is None:
        release_check = 'not_configured'
        domain_check = 'not_configured'
    else:
        try:
            runtime_snapshot = resolver.snapshot()
        except RuntimeConfigurationResolutionError:
            release_check = 'unavailable'
            domain_check = 'unavailable'
            status = 'unavailable'
        else:
            release_check = runtime_snapshot.release_set_id or 'none'
            domain_check = ','.join(sorted(runtime_snapshot.configurations)) or 'none'
    return ReadinessResponse(
        status=status,
        checks={
            **data_checks,
            'data_runtime_profile': data_runtime.profile.value,
            'object_storage_adapter': request.app.state.settings.object_storage_adapter.value,
            'agent': agent_runtime_status,
            'control_plane_release_set': release_check,
            'control_plane_domains': domain_check,
            'aws_policy_history': 'pending_confirmation',
            'claims_service': 'using_fixture',
            'aws_claims_service': 'pending_confirmation',
            'handoff_dispatch': handoff_dispatch,
            'aws_evidence_storage': 'pending_confirmation',
        },
        checked_at=datetime.now(UTC),
    )
