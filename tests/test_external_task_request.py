from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ExternalRequestTaskMismatchError,
    ExternalTaskAuthorisation,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskRequest,
    UnauthorisedDisclosureError,
    assert_disclosure_within_consent,
    assert_request_matches_task,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    IntegrationSource,
)

PREPARED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
SENT_AT = PREPARED_AT + timedelta(minutes=2)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'
PERMITTED = ['claim_id', 'external_claim_id', 'location.region']
CUSTOMER = 'cus_demo'


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
    dispatch_reserved_at: datetime | None = None,
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
        dispatch_reserved_at=dispatch_reserved_at,
        operation_id=operation_id,
    )


def _consent(
    *,
    consent_ref: str = 'consent_1',
    service_identity: str = SERVICE,
    requested_action: str = ACTION,
    permitted: list[str] | None = None,
    status: ExternalServiceConsentStatus = ExternalServiceConsentStatus.GRANTED,
    granted_by: ActorReference | None = None,
) -> ExternalServiceConsent:
    return ExternalServiceConsent(
        consent_ref=consent_ref,
        service_identity=service_identity,
        requested_action=requested_action,
        permitted_fields=permitted if permitted is not None else PERMITTED,
        status=status,
        granted_by=granted_by or ActorReference(actor_type=ActorType.CLAIMANT, actor_id=CUSTOMER),
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


def test_the_operation_identity_appears_when_the_dispatch_is_reserved_or_sent() -> None:
    """Three states, not two.

    The identity used to appear only with the send time. The dispatch reservation now
    records it earlier, so an attempt interrupted between reserving and sending still
    names the operation it was dispatching under and can be reconciled. What is still
    refused is an identity that belongs to neither state.
    """

    sent = _request(sent_at=SENT_AT, operation_id='ext_op_1')
    assert sent.operation_id == 'ext_op_1'

    reserved = _request(dispatch_reserved_at=SENT_AT, operation_id='ext_op_1')
    assert reserved.operation_id == 'ext_op_1'
    assert reserved.sent_at is None

    with pytest.raises(ValueError, match='records its operation identity'):
        _request(sent_at=SENT_AT)

    with pytest.raises(ValueError, match='records its operation identity'):
        _request(dispatch_reserved_at=SENT_AT)

    with pytest.raises(ValueError, match='only once its dispatch is'):
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
    assert_disclosure_within_consent(_request(), _consent(), claim_customer_id=CUSTOMER)


def test_disclosure_beyond_consent_is_rejected() -> None:
    """The consent bounds what may leave Northwind, not the request."""

    with pytest.raises(UnauthorisedDisclosureError, match='does not permit'):
        assert_disclosure_within_consent(
            _request(disclosed=['claim_id', 'incident.description']),
            _consent(),
            claim_customer_id=CUSTOMER,
        )


def test_a_withdrawn_consent_authorises_nothing() -> None:
    with pytest.raises(UnauthorisedDisclosureError, match='authorises no disclosure'):
        assert_disclosure_within_consent(
            _request(),
            _consent(status=ExternalServiceConsentStatus.WITHDRAWN),
            claim_customer_id=CUSTOMER,
        )


def test_a_consent_for_another_service_or_action_does_not_transfer() -> None:
    with pytest.raises(UnauthorisedDisclosureError, match='covers service'):
        assert_disclosure_within_consent(
            _request(), _consent(service_identity='other_service'), claim_customer_id=CUSTOMER
        )

    with pytest.raises(UnauthorisedDisclosureError, match='covers action'):
        assert_disclosure_within_consent(
            _request(), _consent(requested_action='other_action'), claim_customer_id=CUSTOMER
        )


def test_a_consent_the_request_does_not_name_is_rejected() -> None:
    """Checking any granted consent would let an unrelated one authorise a send."""

    with pytest.raises(UnauthorisedDisclosureError, match='is not the consent this request names'):
        assert_disclosure_within_consent(
            _request(), _consent(consent_ref='consent_other'), claim_customer_id=CUSTOMER
        )


def test_a_consent_granted_by_another_customer_authorises_nothing() -> None:
    """The consent must belong to the claimant this claim belongs to."""

    other = ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_someone_else')

    with pytest.raises(UnauthorisedDisclosureError, match='granted by another customer'):
        assert_disclosure_within_consent(
            _request(), _consent(granted_by=other), claim_customer_id=CUSTOMER
        )


@pytest.mark.parametrize('actor_type', [ActorType.STAFF, ActorType.AGENT, ActorType.SYSTEM])
def test_only_a_claimant_may_consent_to_a_disclosure(actor_type: ActorType) -> None:
    """Authorised-representative consent is unsupported until it is modelled explicitly."""

    granted_by = ActorReference(actor_type=actor_type, actor_id=CUSTOMER)

    with pytest.raises(UnauthorisedDisclosureError, match='only the claimant may consent'):
        assert_disclosure_within_consent(
            _request(), _consent(granted_by=granted_by), claim_customer_id=CUSTOMER
        )


def _task(
    *,
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
    service_identity: str = SERVICE,
    requested_action: str = ACTION,
) -> ExternalTaskRecord:
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim_id,
        service_identity=service_identity,
        requested_action=requested_action,
        integration_source=IntegrationSource.FIXTURE,
        status=ExternalTaskOperationStatus.PREPARED,
        created_at=PREPARED_AT,
        updated_at=PREPARED_AT,
    )


def test_a_request_agreeing_with_its_task_passes() -> None:
    assert_request_matches_task(_request(), _task())


def test_a_request_naming_another_task_is_rejected() -> None:
    with pytest.raises(ExternalRequestTaskMismatchError, match='names task'):
        assert_request_matches_task(_request(), _task(task_id='ext_task_other'))


def test_a_request_on_another_claim_cannot_use_this_task() -> None:
    """Same class as the cross-claim provenance defect fixed in #381."""

    with pytest.raises(ExternalRequestTaskMismatchError, match='claim clm_1 does not match'):
        assert_request_matches_task(_request(), _task(claim_id='clm_other'))


@pytest.mark.parametrize(
    ('field', 'kwargs', 'expected'),
    [
        ('service', {'service_identity': 'other_service'}, 'service'),
        ('action', {'requested_action': 'other_action'}, 'action'),
    ],
)
def test_a_request_disagreeing_with_its_task_is_rejected(
    field: str,
    kwargs: dict[str, str],
    expected: str,
) -> None:
    with pytest.raises(ExternalRequestTaskMismatchError, match=f'{expected} '):
        assert_request_matches_task(_request(), _task(**kwargs))
