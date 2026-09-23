"""Common trace shape for controlled paths that make no model invocation."""

from datetime import UTC, datetime
from typing import Any

from backend.domain.ids import new_id
from backend.domain.models import RuntimeTraceRecord


def build_controlled_runtime_trace(
    context: Any,
    *,
    action_code: str,
    runtime_action_code: str,
    reason_codes: list[str],
    deterministic_response_id: str,
) -> RuntimeTraceRecord:
    timestamp = datetime.now(UTC)
    return RuntimeTraceRecord(
        trace_id=new_id('trc'),
        claim_id=context.claim.claim_id,
        session_id=context.session_id,
        model_profile_id=context.model_profile_id,
        trigger_message_id=context.trigger_message_id,
        invocations=[],
        action_code=action_code,
        runtime_action_code=runtime_action_code,
        reason_codes=reason_codes,
        deterministic_response_id=deterministic_response_id,
        route=f'{context.claim.incident_type or "unresolved"}:controlled',
        model_invocations=0,
        tool_calls=0,
        total_latency_ms=0,
        status='succeeded',
        created_at=timestamp,
        finished_at=timestamp,
    )
