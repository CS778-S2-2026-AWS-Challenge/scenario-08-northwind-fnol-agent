"""What a request actually reached, told apart from what was configured for it.

The Workbench projection carried the source class only as prose, in a `limitation`
sentence that appears for a fixture and is absent otherwise. A staff member could not
read whether a provider had been contacted; they could read that someone had written a
warning. These hold the three classes P11.2 names to the two facts the task already
records, so the distinction is derived from data rather than asserted in text.

`live_attempted` is deliberately unreachable today. `docs/third-party-service-consent-and-
shared-data-contract.md` records the only implemented service identity as a controlled
fixture and `P3-ASSESSOR` as simulation-only, so nothing in this repository may contact a
production assessor. Deriving the class rather than storing it is what keeps that true
without an enum member nothing can produce.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.domain.external_services import (
    ASSESSOR_SERVICE_IDENTITY,
    CATALOGUE_REFERENCE_BY_SERVICE,
    ExternalRequestProvenance,
    ExternalTaskDelivery,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    catalogue_reference,
    request_provenance,
)
from backend.domain.models import IntegrationSource

AT = datetime(2026, 9, 10, 3, 0, tzinfo=UTC)


def _task(
    *,
    source: IntegrationSource = IntegrationSource.FIXTURE,
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.NOT_SUBMITTED,
    evidence: str | None = None,
    service: str = ASSESSOR_SERVICE_IDENTITY,
) -> ExternalTaskRecord:
    # The record refuses `accepted` without a submission, so the status follows the
    # delivery rather than being chosen independently of it.
    submitted = delivery is ExternalTaskDelivery.SUBMITTED
    return ExternalTaskRecord(
        task_id='tsk_1',
        claim_id='clm_1',
        service_identity=service,
        requested_action='vehicle_damage_assessment',
        integration_source=source,
        status=(
            ExternalTaskOperationStatus.ACCEPTED
            if submitted
            else ExternalTaskOperationStatus.PREPARED
        ),
        delivery=delivery,
        delivery_evidence=evidence,
        created_at=AT,
        updated_at=AT,
    )


def test_a_fixture_is_simulated_however_far_it_got() -> None:
    """Delivery on a fixture says a synthetic adapter accepted it, not that a provider did.

    This is the case that matters, because it is the only one the repository can currently
    produce: reading a submitted fixture as provider contact would claim a relationship
    the consent contract says does not exist.
    """

    not_sent = _task()
    sent = _task(delivery=ExternalTaskDelivery.SUBMITTED, evidence='fixture-ack-1')

    assert request_provenance(not_sent) is ExternalRequestProvenance.SIMULATED
    assert request_provenance(sent) is ExternalRequestProvenance.SIMULATED


def test_a_configured_service_that_was_not_sent_is_not_contact() -> None:
    """Configuration is not contact. A demonstration must not read one as the other."""

    task = _task(source=IntegrationSource.CONFIGURED_SERVICE)

    assert request_provenance(task) is ExternalRequestProvenance.CONFIGURED


def test_only_a_submitted_configured_service_is_live_attempted() -> None:
    """And it says an attempt reached a provider, not that the result is good."""

    task = _task(
        source=IntegrationSource.CONFIGURED_SERVICE,
        delivery=ExternalTaskDelivery.SUBMITTED,
        evidence='provider-ack-9f2',
    )

    assert request_provenance(task) is ExternalRequestProvenance.LIVE_ATTEMPTED


def test_live_attempted_cannot_be_reached_by_the_only_implemented_service() -> None:
    """The consent contract makes the assessor path a controlled fixture, simulation-only.

    So the third class is currently unreachable, which is the argument for deriving it
    rather than storing it: an enum member on a persisted record would be a value nothing
    can produce, and a projection could still state it.
    """

    for delivery in ExternalTaskDelivery:
        task = _task(
            delivery=delivery,
            evidence='fixture-ack-1' if delivery is ExternalTaskDelivery.SUBMITTED else None,
        )
        assert request_provenance(task) is not ExternalRequestProvenance.LIVE_ATTEMPTED


def test_the_task_can_cite_the_catalogue_row_that_authorises_it() -> None:
    """A reader gets from a persisted task to the merged P3 entry, and back."""

    assert catalogue_reference(_task()) == 'P3-ASSESSOR'
    assert CATALOGUE_REFERENCE_BY_SERVICE[ASSESSOR_SERVICE_IDENTITY] == 'P3-ASSESSOR'


def test_a_service_the_catalogue_does_not_name_cites_nothing() -> None:
    """Better an absent reference than an invented one."""

    assert catalogue_reference(_task(service='some_unlisted_service')) is None


@pytest.mark.parametrize('source', list(IntegrationSource))
def test_every_source_class_resolves(source: IntegrationSource) -> None:
    """No source may fall through without a provenance, whatever is added later."""

    assert request_provenance(_task(source=source)) in ExternalRequestProvenance
