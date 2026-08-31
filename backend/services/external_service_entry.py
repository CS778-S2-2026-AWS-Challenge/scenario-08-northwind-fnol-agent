"""Entry-point separation for third-party stakeholder services.

`backend/core/runtime_profiles.py` already refuses to assemble a runtime that
would silently substitute one data provider for another. This module applies the
same discipline to a single external service call: it decides which entry may
serve the call, and refuses a task whose recorded source does not match the
entry that produced it, so a controlled fixture result can never be read as a
configured-service result.
"""

from enum import Enum

from pydantic import Field, model_validator

from backend.core.runtime_profiles import RuntimeCapabilityStatus
from backend.domain.external_services import ExternalTaskRecord
from backend.domain.models import ContractModel, IntegrationSource


class ExternalServiceEntry(str, Enum):
    """Which entry point may serve one external service call.

    `UNAVAILABLE` is a first-class outcome, not an error state: the claim is
    preserved and both the claimant and staff surfaces can read why no result
    exists.
    """

    LIVE = 'live'
    TEST_FIXTURE = 'test_fixture'
    UNAVAILABLE = 'unavailable'


class ForgedIntegrationSource(ValueError):
    """A task claims a source class the entry that produced it cannot provide."""


_ENTRY_SOURCES: dict[ExternalServiceEntry, IntegrationSource | None] = {
    ExternalServiceEntry.LIVE: IntegrationSource.CONFIGURED_SERVICE,
    ExternalServiceEntry.TEST_FIXTURE: IntegrationSource.FIXTURE,
    ExternalServiceEntry.UNAVAILABLE: None,
}


class ExternalServiceEntryDecision(ContractModel):
    """Which entry serves a call, and the source class its results may carry.

    The entry alone determines the source class. The validator refuses every
    other combination, so a contradictory decision such as a live entry carrying
    a fixture source cannot be constructed and then trusted by the guard.
    """

    entry: ExternalServiceEntry
    integration_source: IntegrationSource | None = None
    limitation: str | None = Field(default=None, max_length=300)

    @model_validator(mode='after')
    def validate_entry_contract(self) -> 'ExternalServiceEntryDecision':
        expected = _ENTRY_SOURCES[self.entry]
        if self.integration_source is not expected:
            raise ValueError(
                f'Entry {self.entry.value} provides '
                f'{expected.value if expected else "no result"}, '
                f'not {self.integration_source.value if self.integration_source else "no result"}.'
            )
        if expected is None and self.limitation is None:
            raise ValueError(f'Entry {self.entry.value} produces no result and must say why.')
        if expected is not None and self.limitation is not None:
            raise ValueError(
                f'Entry {self.entry.value} produces a result and carries no limitation.'
            )
        return self


_PENDING_LIMITATION = (
    'The service connection, authority, schema, and result mapping are not verified, '
    'so no live result can be produced.'
)
_UNAVAILABLE_LIMITATION = 'The service is not available in the current runtime profile.'
_FIXTURE_WITHHELD_LIMITATION = (
    'Only a controlled test fixture is configured for this service, and this caller did '
    'not ask for fixture results.'
)


def resolve_external_service_entry(
    *,
    capability_status: RuntimeCapabilityStatus,
    allow_test_fixture: bool,
) -> ExternalServiceEntryDecision:
    """Decide which entry may serve one external service call.

    A fixture serves a call only when the caller explicitly asked for one. A
    caller that did not ask receives `UNAVAILABLE` rather than a synthetic
    success, which is what keeps a fixture from becoming a silent runtime
    fallback.

    Args:
        capability_status: Readiness of this service in the active runtime
            profile.
        allow_test_fixture: Whether this caller is a test, regression, or
            offline-validation path that asked for fixture results.

    Returns:
        The permitted entry, the source class its results may carry, and the
        limitation to surface when no result can be produced.
    """

    if capability_status is RuntimeCapabilityStatus.VERIFIED:
        return ExternalServiceEntryDecision(
            entry=ExternalServiceEntry.LIVE,
            integration_source=IntegrationSource.CONFIGURED_SERVICE,
        )
    if capability_status is RuntimeCapabilityStatus.USING_FIXTURE:
        if allow_test_fixture:
            return ExternalServiceEntryDecision(
                entry=ExternalServiceEntry.TEST_FIXTURE,
                integration_source=IntegrationSource.FIXTURE,
            )
        return ExternalServiceEntryDecision(
            entry=ExternalServiceEntry.UNAVAILABLE,
            limitation=_FIXTURE_WITHHELD_LIMITATION,
        )
    limitation = (
        _PENDING_LIMITATION
        if capability_status is RuntimeCapabilityStatus.PENDING_CONFIRMATION
        else _UNAVAILABLE_LIMITATION
    )
    return ExternalServiceEntryDecision(
        entry=ExternalServiceEntry.UNAVAILABLE,
        limitation=limitation,
    )


def assert_task_matches_entry(
    task: ExternalTaskRecord,
    decision: ExternalServiceEntryDecision,
) -> None:
    """Check that a task's recorded source is one the serving entry can provide.

    The permitted source is derived from `decision.entry`, not read from
    `decision.integration_source`. The model validator already refuses a
    contradictory pair, so the two agree for any validated decision; deriving
    here means the guard still holds for one built through a path that skips
    validation.

    Args:
        task: The task record produced by the call.
        decision: The entry decision that authorised the call.

    Raises:
        ForgedIntegrationSource: The entry produced no result at all, or the task
            records a source class other than the one the entry provides.
    """

    permitted = _ENTRY_SOURCES[decision.entry]
    if permitted is None:
        raise ForgedIntegrationSource(
            f'{task.task_id}: entry {decision.entry.value} produces no result, so the task '
            f'cannot record source {task.integration_source.value}.'
        )
    if task.integration_source is not permitted:
        raise ForgedIntegrationSource(
            f'{task.task_id}: entry {decision.entry.value} provides {permitted.value}, '
            f'but the task records {task.integration_source.value}.'
        )
