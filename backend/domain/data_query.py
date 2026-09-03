"""Shared, provider-neutral projection for data-query outcomes."""

from enum import StrEnum

from pydantic import Field

from backend.domain.models import ContractModel


class DataConnectionState(StrEnum):
    """Connection classification exposed without leaking provider configuration."""

    USING_FIXTURE = 'using_fixture'
    VERIFIED = 'verified'
    CONFIGURED_SERVICE = 'configured_service'
    DEGRADED = 'degraded'
    UNAVAILABLE = 'unavailable'


class DataQueryErrorCode(StrEnum):
    TIMEOUT = 'timeout'
    UNAVAILABLE = 'unavailable'


class DataQueryError(ContractModel):
    code: DataQueryErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool


class DataQueryProjection(ContractModel):
    """Shared API fields for one provider-neutral data-query outcome."""

    connection_state: DataConnectionState
    errors: list[DataQueryError] = Field(default_factory=list, max_length=10)


def usable_connection_state(raw_status: str) -> DataConnectionState:
    """Map only approved start-capable adapter states into an API projection."""

    try:
        state = DataConnectionState(raw_status)
    except ValueError:
        return DataConnectionState.UNAVAILABLE
    if state in {
        DataConnectionState.USING_FIXTURE,
        DataConnectionState.VERIFIED,
        DataConnectionState.CONFIGURED_SERVICE,
    }:
        return state
    return DataConnectionState.UNAVAILABLE


__all__ = [
    'DataConnectionState',
    'DataQueryError',
    'DataQueryErrorCode',
    'DataQueryProjection',
    'usable_connection_state',
]
