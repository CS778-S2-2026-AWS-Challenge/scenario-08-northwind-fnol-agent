from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.core.runtime_profiles import RuntimeCapabilityStatus
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import IntegrationSource
from backend.services.external_service_entry import (
    ExternalServiceEntry,
    ExternalServiceEntryDecision,
    ForgedIntegrationSource,
    assert_task_matches_entry,
    resolve_external_service_entry,
)

CREATED_AT = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)


def _task(integration_source: IntegrationSource) -> ExternalTaskRecord:
    return ExternalTaskRecord(
        task_id='ext_task_1',
        claim_id='clm_1',
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        integration_source=integration_source,
        status=ExternalTaskOperationStatus.PREPARED,
        delivery=ExternalTaskDelivery.NOT_SUBMITTED,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(minutes=1),
    )


def test_verified_capability_serves_a_live_configured_service() -> None:
    decision = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.VERIFIED,
        allow_test_fixture=False,
    )

    assert decision.entry is ExternalServiceEntry.LIVE
    assert decision.integration_source is IntegrationSource.CONFIGURED_SERVICE
    assert decision.limitation is None


def test_fixture_capability_serves_a_caller_that_asked_for_a_fixture() -> None:
    decision = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.USING_FIXTURE,
        allow_test_fixture=True,
    )

    assert decision.entry is ExternalServiceEntry.TEST_FIXTURE
    assert decision.integration_source is IntegrationSource.FIXTURE


def test_fixture_is_withheld_from_a_caller_that_did_not_ask_for_one() -> None:
    """This is the rule that stops a fixture becoming a silent runtime fallback."""

    decision = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.USING_FIXTURE,
        allow_test_fixture=False,
    )

    assert decision.entry is ExternalServiceEntry.UNAVAILABLE
    assert decision.integration_source is None
    assert decision.limitation is not None


@pytest.mark.parametrize(
    'capability_status',
    [RuntimeCapabilityStatus.PENDING_CONFIRMATION, RuntimeCapabilityStatus.UNAVAILABLE],
)
@pytest.mark.parametrize('allow_test_fixture', [True, False])
def test_unready_capability_is_unavailable_with_a_readable_limitation(
    capability_status: RuntimeCapabilityStatus,
    allow_test_fixture: bool,
) -> None:
    """An unverified service must never be served by a fixture, even on request."""

    decision = resolve_external_service_entry(
        capability_status=capability_status,
        allow_test_fixture=allow_test_fixture,
    )

    assert decision.entry is ExternalServiceEntry.UNAVAILABLE
    assert decision.integration_source is None
    assert decision.limitation is not None


@pytest.mark.parametrize('capability_status', list(RuntimeCapabilityStatus))
@pytest.mark.parametrize('allow_test_fixture', [True, False])
def test_every_decision_that_produces_no_result_explains_why(
    capability_status: RuntimeCapabilityStatus,
    allow_test_fixture: bool,
) -> None:
    decision = resolve_external_service_entry(
        capability_status=capability_status,
        allow_test_fixture=allow_test_fixture,
    )

    if decision.integration_source is None:
        assert decision.entry is ExternalServiceEntry.UNAVAILABLE
        assert decision.limitation is not None
    else:
        assert decision.limitation is None


def test_fixture_entry_cannot_produce_a_configured_service_task() -> None:
    """The hidden-fixture-success case the card exists to prevent."""

    decision = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.USING_FIXTURE,
        allow_test_fixture=True,
    )

    with pytest.raises(ForgedIntegrationSource, match='provides fixture'):
        assert_task_matches_entry(_task(IntegrationSource.CONFIGURED_SERVICE), decision)


def test_live_entry_cannot_produce_a_fixture_task() -> None:
    decision = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.VERIFIED,
        allow_test_fixture=False,
    )

    with pytest.raises(ForgedIntegrationSource, match='provides configured_service'):
        assert_task_matches_entry(_task(IntegrationSource.FIXTURE), decision)


@pytest.mark.parametrize('integration_source', list(IntegrationSource))
def test_an_unavailable_entry_accepts_no_task_at_all(
    integration_source: IntegrationSource,
) -> None:
    decision = ExternalServiceEntryDecision(
        entry=ExternalServiceEntry.UNAVAILABLE,
        limitation='unavailable',
    )

    with pytest.raises(ForgedIntegrationSource, match='produces no result'):
        assert_task_matches_entry(_task(integration_source), decision)


@pytest.mark.parametrize(
    ('entry', 'integration_source'),
    [
        (ExternalServiceEntry.LIVE, IntegrationSource.FIXTURE),
        (ExternalServiceEntry.TEST_FIXTURE, IntegrationSource.CONFIGURED_SERVICE),
        (ExternalServiceEntry.UNAVAILABLE, IntegrationSource.FIXTURE),
        (ExternalServiceEntry.UNAVAILABLE, IntegrationSource.CONFIGURED_SERVICE),
    ],
)
def test_a_contradictory_decision_cannot_be_constructed(
    entry: ExternalServiceEntry,
    integration_source: IntegrationSource,
) -> None:
    """The guard trusted this pair, so the pair must not be constructible."""

    with pytest.raises(ValidationError, match='provides'):
        ExternalServiceEntryDecision(
            entry=entry,
            integration_source=integration_source,
            limitation='contradictory' if entry is ExternalServiceEntry.UNAVAILABLE else None,
        )


def test_a_resultless_decision_must_explain_itself() -> None:
    with pytest.raises(ValidationError, match='must say why'):
        ExternalServiceEntryDecision(entry=ExternalServiceEntry.UNAVAILABLE)


@pytest.mark.parametrize(
    ('entry', 'integration_source'),
    [
        (ExternalServiceEntry.LIVE, IntegrationSource.CONFIGURED_SERVICE),
        (ExternalServiceEntry.TEST_FIXTURE, IntegrationSource.FIXTURE),
    ],
)
def test_a_result_bearing_decision_carries_no_limitation(
    entry: ExternalServiceEntry,
    integration_source: IntegrationSource,
) -> None:
    with pytest.raises(ValidationError, match='carries no limitation'):
        ExternalServiceEntryDecision(
            entry=entry,
            integration_source=integration_source,
            limitation='should not be here',
        )


def test_the_guard_derives_the_permitted_source_from_the_entry() -> None:
    """A decision built past validation must not be able to widen the guard."""

    forged = ExternalServiceEntryDecision.model_construct(
        entry=ExternalServiceEntry.TEST_FIXTURE,
        integration_source=IntegrationSource.CONFIGURED_SERVICE,
        limitation=None,
    )

    with pytest.raises(ForgedIntegrationSource, match='provides fixture'):
        assert_task_matches_entry(_task(IntegrationSource.CONFIGURED_SERVICE), forged)


def test_matching_source_and_entry_pass() -> None:
    live = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.VERIFIED,
        allow_test_fixture=False,
    )
    fixture = resolve_external_service_entry(
        capability_status=RuntimeCapabilityStatus.USING_FIXTURE,
        allow_test_fixture=True,
    )

    assert_task_matches_entry(_task(IntegrationSource.CONFIGURED_SERVICE), live)
    assert_task_matches_entry(_task(IntegrationSource.FIXTURE), fixture)
