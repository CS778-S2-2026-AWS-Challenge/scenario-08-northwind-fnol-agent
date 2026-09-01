from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ExternalTaskAuthorisation,
    ExternalTaskRequest,
    UnauthorisedDisclosureError,
    assert_disclosure_within_consent,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
)

PREPARED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
SENT_AT = PREPARED_AT + timedelta(minutes=2)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'
PERMITTED = ['claim_id', 'external_claim_id', 'location.region']


def _authorisation(
    *,
    northwind: str = 'nw_authority_1',
    consent: str = 'consent_1',
    revision: int = 3,
) -> ExternalTaskAuthorisation:
    return ExternalTaskAuthorisation(
        northwind_authority_ref=northwind,
        claimant_consent_ref=consent,
        authorised_revision=revision,
    )


def _request(
    *,
    disclosed: list[str] | None = None,
    purpose: str = 'Request an assessor for the recorded vehicle damage.',
    sent_at: datetime | None = None,
    operation_id: str | None = None,
    service_identity: str = SERVICE,
    requested_action: str = ACTION,
    authorisation: ExternalTaskAuthorisation | None = None,
) -> ExternalTaskRequest:
    return ExternalTaskRequest(
        request_id='ext_req_1',
        task_id='ext_task_1',
        claim_id='clm_1',
        service_identity=service_identity,
        requested_action=requested_action,
        purpose=purpose,
        disclosed_fields=disclosed if disclosed is not None else ['claim_id', 'location.region'],
        authorisation=authorisation or _authorisation(),
        prepared_at=PREPARED_AT,
        sent_at=sent_at,
        operation_id=operation_id,
    )


def _consent(
    *,
    consent_ref: str = 'consent_1',
    service_identity: str = SERVICE,
    requested_action: str = ACTION,
    permitted: list[str] | None = None,
    status: ExternalServiceConsentStatus = ExternalServiceConsentStatus.GRANTED,
) -> ExternalServiceConsent:
    return ExternalServiceConsent(
        consent_ref=consent_ref,
        service_identity=service_identity,
        requested_action=requested_action,
        permitted_fields=permitted if permitted is not None else PERMITTED,
        status=status,
        granted_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
        granted_at=PREPARED_AT,
        withdrawn_at=None if status is ExternalServiceConsentStatus.GRANTED else SENT_AT,
    )


def test_a_prepared_request_carries_the_five_required_properties() -> None:
    request = _request()

    assert request.service_identity == SERVICE
    assert request.claim_id == 'clm_1'
    assert request.disclosed_fields == ['claim_id', 'location.region']
    assert request.authorisation.northwind_authority_ref == 'nw_authority_1'
    assert request.authorisation.claimant_consent_ref == 'consent_1'
    assert request.purpose


def test_the_two_authorities_cannot_be_the_same_reference() -> None:
    """Neither authority substitutes for the other, so one reference cannot be both."""

    with pytest.raises(ValueError, match='cannot be the same reference'):
        _authorisation(northwind='same_ref', consent='same_ref')


def test_send_time_and_operation_identity_travel_together() -> None:
    sent = _request(sent_at=SENT_AT, operation_id='ext_op_1')
    assert sent.operation_id == 'ext_op_1'

    with pytest.raises(ValueError, match='records both a send time and an operation'):
        _request(sent_at=SENT_AT)

    with pytest.raises(ValueError, match='records both a send time and an operation'):
        _request(operation_id='ext_op_1')


def test_a_request_cannot_be_sent_before_it_was_prepared() -> None:
    with pytest.raises(ValueError, match='cannot be sent before it was prepared'):
        _request(sent_at=PREPARED_AT - timedelta(seconds=1), operation_id='ext_op_1')


def test_disclosed_fields_must_be_unique_and_readable() -> None:
    with pytest.raises(ValueError, match='must be unique'):
        _request(disclosed=['claim_id', 'claim_id'])

    with pytest.raises(ValueError, match='name something readable'):
        _request(disclosed=['claim_id', '   '])


def test_a_request_must_state_a_readable_purpose() -> None:
    with pytest.raises(ValueError, match='readable purpose'):
        _request(purpose='   ')


def test_disclosure_within_consent_passes() -> None:
    assert_disclosure_within_consent(_request(), _consent())


def test_disclosure_beyond_consent_is_rejected() -> None:
    """The consent bounds what may leave Northwind, not the request."""

    with pytest.raises(UnauthorisedDisclosureError, match='does not permit'):
        assert_disclosure_within_consent(
            _request(disclosed=['claim_id', 'incident.description']),
            _consent(),
        )


def test_a_withdrawn_consent_authorises_nothing() -> None:
    with pytest.raises(UnauthorisedDisclosureError, match='authorises no disclosure'):
        assert_disclosure_within_consent(
            _request(),
            _consent(status=ExternalServiceConsentStatus.WITHDRAWN),
        )


def test_a_consent_for_another_service_or_action_does_not_transfer() -> None:
    with pytest.raises(UnauthorisedDisclosureError, match='covers service'):
        assert_disclosure_within_consent(_request(), _consent(service_identity='other_service'))

    with pytest.raises(UnauthorisedDisclosureError, match='covers action'):
        assert_disclosure_within_consent(_request(), _consent(requested_action='other_action'))


def test_a_consent_the_request_does_not_name_is_rejected() -> None:
    """Checking any granted consent would let an unrelated one authorise a send."""

    with pytest.raises(UnauthorisedDisclosureError, match='is not the consent this request names'):
        assert_disclosure_within_consent(_request(), _consent(consent_ref='consent_other'))
