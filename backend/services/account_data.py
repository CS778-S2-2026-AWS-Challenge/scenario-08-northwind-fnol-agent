"""Owner-scoped account policy and protected-data behavior."""

import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TypeVar

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.account_data import (
    ClaimPayoutContactSelectionResponse,
    ClaimPolicySelectionResponse,
    CreateIdentityDocumentRequest,
    CreatePaymentDestinationRequest,
    CreatePolicyNumberRequest,
    IdentityDocumentListResponse,
    IdentityDocumentProjection,
    IdentityDocumentRecord,
    PaymentDestinationListResponse,
    PaymentDestinationProjection,
    PaymentDestinationRecord,
    PolicyNumberListResponse,
    PolicyNumberProjection,
    PolicyNumberRecord,
    SelectPayoutContactRequest,
    SelectPolicyNumberRequest,
    UpdateIdentityDocumentRequest,
    UpdatePaymentDestinationRequest,
    UpdatePolicyNumberRequest,
    project_identity_document,
    project_payment_destination,
    project_policy,
)
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.branch_registry import validate_registered_field_value
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    FormSource,
    FormStatus,
    NeededFor,
    PageInfo,
    ProposedFormChange,
    WorkingClaim,
)
from backend.repositories.account_data import (
    AccountCursorKey,
    AccountDataRepository,
    AccountRecord,
    ClaimantContactSelectionConflict,
    PaymentDestinationSelectionConflict,
    PolicySelectionConflict,
    account_record_identity,
)
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.claimant_action_projection import project_claimant_primary_action
from backend.services.external_services import claimant_assessor_action, claimant_next_step
from backend.services.fact_resolution import resolve_form_change
from backend.services.protected_values import (
    ProtectedValueAdapter,
    ProtectedValueError,
    masked_value,
)
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)


@dataclass(frozen=True, slots=True)
class RetirementResult:
    resource_id: str
    revision: int


RecordT = TypeVar('RecordT', PolicyNumberRecord, PaymentDestinationRecord, IdentityDocumentRecord)
ProjectionT = TypeVar(
    'ProjectionT', PolicyNumberProjection, PaymentDestinationProjection, IdentityDocumentProjection
)


def _not_found(resource: str) -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message=f'The {resource} was not found.',
    )


def _revision_conflict(revision: int) -> ApiError:
    return ApiError(
        status_code=409,
        code='REVISION_CONFLICT',
        message='The resource changed after this page was loaded.',
        retryable=True,
        current_revision=revision,
    )


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The Idempotency-Key was already used with a different request.',
    )


def _seal(protected_values: ProtectedValueAdapter, value: str) -> str:
    try:
        return protected_values.seal(value)
    except ProtectedValueError as error:
        raise ApiError(
            status_code=503,
            code='PROTECTED_DATA_UNAVAILABLE',
            message='Protected account data is temporarily unavailable.',
            retryable=True,
        ) from error


def _account_audit(
    record: AccountRecord,
    principal: Principal,
    *,
    action: str,
    idempotency_key: str | None = None,
) -> AuditEventEnvelope:
    kind, identifier, subject_type = account_record_identity(record)
    return AuditEventEnvelope(
        event_id=new_id('aud'),
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(subject_type=subject_type, subject_id=identifier),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason=f'Claimant {action} an account {kind.replace("_", " ")}.',
        source_refs=[f'{kind}:{identifier}:revision:{record.revision}'],
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=idempotency_key,
        created_at=record.updated_at,
    )


def _create(
    repository: AccountDataRepository,
    idempotency_repository: PersistenceRepository,
    principal: Principal,
    route: str,
    payload: dict[str, object],
    key_header: str | None,
    build: Callable[[], RecordT],
    project: Callable[[RecordT], ProjectionT],
    projection_type: type[ProjectionT],
) -> ProjectionT:
    key = require_idempotency_key(key_header)
    fingerprint = request_fingerprint(payload)
    existing = idempotency_repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.response_payload is None:
            raise _idempotency_conflict()
        return projection_type.model_validate(existing.response_payload)
    record = build()
    projection = project(record)
    _, identifier, _ = account_record_identity(record)
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=identifier,
        session_id='',
        response_payload=projection.model_dump(mode='json'),
    )
    try:
        repository.create_account_record(
            record,
            idempotency,
            _account_audit(record, principal, action='created', idempotency_key=key),
        )
    except IdempotencyConflict as error:
        replay = idempotency_repository.find_idempotency(principal.subject, route, key)
        if (
            replay is None
            or replay.request_fingerprint != fingerprint
            or replay.response_payload is None
        ):
            raise _idempotency_conflict() from error
        return projection_type.model_validate(replay.response_payload)
    return projection


def create_policy(
    repository: AccountDataRepository,
    persistence: PersistenceRepository,
    principal: Principal,
    payload: CreatePolicyNumberRequest,
    idempotency_key: str | None,
) -> PolicyNumberProjection:
    now = now_utc()
    return _create(
        repository,
        persistence,
        principal,
        '/api/v1/account/policies',
        payload.model_dump(mode='json'),
        idempotency_key,
        lambda: PolicyNumberRecord(
            policy_id=new_id('pol'),
            customer_id=principal.subject,
            policy_number=payload.policy_number,
            created_at=now,
            updated_at=now,
        ),
        project_policy,
        PolicyNumberProjection,
    )


def create_payment_destination(
    repository: AccountDataRepository,
    persistence: PersistenceRepository,
    protected_values: ProtectedValueAdapter,
    principal: Principal,
    payload: CreatePaymentDestinationRequest,
    idempotency_key: str | None,
) -> PaymentDestinationProjection:
    now = now_utc()
    return _create(
        repository,
        persistence,
        principal,
        '/api/v1/account/payment-destinations',
        payload.model_dump(mode='json'),
        idempotency_key,
        lambda: PaymentDestinationRecord(
            payment_destination_id=new_id('pyd'),
            customer_id=principal.subject,
            account_type=payload.account_type,
            protected_value=_seal(protected_values, payload.account_number),
            masked_value=masked_value(payload.account_number),
            created_at=now,
            updated_at=now,
        ),
        project_payment_destination,
        PaymentDestinationProjection,
    )


def create_identity_document(
    repository: AccountDataRepository,
    persistence: PersistenceRepository,
    protected_values: ProtectedValueAdapter,
    principal: Principal,
    payload: CreateIdentityDocumentRequest,
    idempotency_key: str | None,
) -> IdentityDocumentProjection:
    now = now_utc()
    return _create(
        repository,
        persistence,
        principal,
        '/api/v1/account/identity-documents',
        payload.model_dump(mode='json'),
        idempotency_key,
        lambda: IdentityDocumentRecord(
            identity_id=new_id('idn'),
            customer_id=principal.subject,
            document_type=payload.document_type,
            protected_value=_seal(protected_values, payload.document_number),
            masked_value=masked_value(payload.document_number),
            created_at=now,
            updated_at=now,
        ),
        project_identity_document,
        IdentityDocumentProjection,
    )


def _invalid_cursor() -> ApiError:
    return ApiError(
        status_code=422,
        code='VALIDATION_ERROR',
        message='The pagination cursor is invalid.',
        details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this list.')],
    )


def _encode_account_cursor(
    customer_id: str,
    kind: str,
    include_inactive: bool,
    created_at: datetime,
    identifier: str,
) -> str:
    payload = json.dumps(
        {
            'v': 1,
            'kind': kind,
            'owner': sha256(customer_id.encode()).hexdigest(),
            'include_inactive': include_inactive,
            'created_at': created_at.isoformat(),
            'id': identifier,
        },
        separators=(',', ':'),
        sort_keys=True,
    )
    return urlsafe_b64encode(payload.encode()).decode().rstrip('=')


def _decode_account_cursor(
    cursor: str | None, customer_id: str, kind: str, include_inactive: bool
) -> AccountCursorKey | None:
    if cursor is None:
        return None
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        payload = json.loads(urlsafe_b64decode(padded).decode())
        expected_prefix = {
            'policy': 'pol',
            'payment_destination': 'pyd',
            'identity_document': 'idn',
        }[kind]
        if (
            not isinstance(payload, dict)
            or set(payload) != {'v', 'kind', 'owner', 'include_inactive', 'created_at', 'id'}
            or payload.get('v') != 1
            or payload.get('kind') != kind
            or payload.get('owner') != sha256(customer_id.encode()).hexdigest()
            or payload.get('include_inactive') is not include_inactive
            or not isinstance(payload.get('created_at'), str)
            or not isinstance(payload.get('id'), str)
            or re.fullmatch(rf'{expected_prefix}_[a-f0-9]{{20}}', payload['id']) is None
        ):
            raise ValueError('cursor_scope')
        created_at = datetime.fromisoformat(payload['created_at'])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError('cursor_timezone')
        return created_at, payload['id']
    except (Base64Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise _invalid_cursor() from error


def _page(
    records: list[RecordT],
    has_more: bool,
    customer_id: str,
    kind: str,
    include_inactive: bool,
) -> PageInfo:
    if not has_more or not records:
        return PageInfo(next_cursor=None)
    record = records[-1]
    _, identifier, _ = account_record_identity(record)
    return PageInfo(
        next_cursor=_encode_account_cursor(
            customer_id, kind, include_inactive, record.created_at, identifier
        )
    )


def list_policies(
    repository: AccountDataRepository,
    principal: Principal,
    include_inactive: bool,
    limit: int,
    cursor: str | None,
) -> PolicyNumberListResponse:
    bounded_limit = min(limit, 100)
    after = _decode_account_cursor(cursor, principal.subject, 'policy', include_inactive)
    records, more = repository.list_policies(
        principal.subject,
        include_inactive=include_inactive,
        after=after,
        limit=bounded_limit,
    )
    return PolicyNumberListResponse(
        items=[project_policy(record) for record in records],
        page=_page(records, more, principal.subject, 'policy', include_inactive),
    )


def list_payment_destinations(
    repository: AccountDataRepository,
    principal: Principal,
    include_inactive: bool,
    limit: int,
    cursor: str | None,
) -> PaymentDestinationListResponse:
    bounded_limit = min(limit, 100)
    after = _decode_account_cursor(
        cursor, principal.subject, 'payment_destination', include_inactive
    )
    records, more = repository.list_payment_destinations(
        principal.subject,
        include_inactive=include_inactive,
        after=after,
        limit=bounded_limit,
    )
    return PaymentDestinationListResponse(
        items=[project_payment_destination(record) for record in records],
        page=_page(records, more, principal.subject, 'payment_destination', include_inactive),
    )


def list_identity_documents(
    repository: AccountDataRepository,
    principal: Principal,
    include_inactive: bool,
    limit: int,
    cursor: str | None,
) -> IdentityDocumentListResponse:
    bounded_limit = min(limit, 100)
    after = _decode_account_cursor(cursor, principal.subject, 'identity_document', include_inactive)
    records, more = repository.list_identity_documents(
        principal.subject,
        include_inactive=include_inactive,
        after=after,
        limit=bounded_limit,
    )
    return IdentityDocumentListResponse(
        items=[project_identity_document(record) for record in records],
        page=_page(records, more, principal.subject, 'identity_document', include_inactive),
    )


def _update(
    repository: AccountDataRepository,
    principal: Principal,
    record: RecordT,
    expected_revision: int,
    changes: dict[str, object],
    project: Callable[[RecordT], ProjectionT],
) -> ProjectionT:
    updated = record.model_copy(
        update={**changes, 'revision': record.revision + 1, 'updated_at': now_utc()}
    )
    try:
        repository.update_account_record(
            updated,
            expected_revision,
            _account_audit(updated, principal, action='updated'),
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    return project(updated)


def update_policy(
    repository: AccountDataRepository,
    principal: Principal,
    policy_id: str,
    payload: UpdatePolicyNumberRequest,
    if_match: str | None,
) -> PolicyNumberProjection:
    expected = parse_if_match(if_match)
    record = repository.get_policy(policy_id, principal.subject)
    if record is None:
        raise _not_found('policy')
    if record.revision != expected:
        raise _revision_conflict(record.revision)
    return _update(
        repository,
        principal,
        record,
        expected,
        payload.model_dump(exclude_unset=True),
        project_policy,
    )


def update_payment_destination(
    repository: AccountDataRepository,
    protected_values: ProtectedValueAdapter,
    principal: Principal,
    resource_id: str,
    payload: UpdatePaymentDestinationRequest,
    if_match: str | None,
) -> PaymentDestinationProjection:
    expected = parse_if_match(if_match)
    record = repository.get_payment_destination(resource_id, principal.subject)
    if record is None:
        raise _not_found('payment destination')
    if record.revision != expected:
        raise _revision_conflict(record.revision)
    changes = payload.model_dump(exclude_unset=True, exclude={'account_number'})
    if 'account_number' in payload.model_fields_set:
        changes.update(
            protected_value=_seal(protected_values, payload.account_number),
            masked_value=masked_value(payload.account_number),
        )
    return _update(repository, principal, record, expected, changes, project_payment_destination)


def update_identity_document(
    repository: AccountDataRepository,
    protected_values: ProtectedValueAdapter,
    principal: Principal,
    resource_id: str,
    payload: UpdateIdentityDocumentRequest,
    if_match: str | None,
) -> IdentityDocumentProjection:
    expected = parse_if_match(if_match)
    record = repository.get_identity_document(resource_id, principal.subject)
    if record is None:
        raise _not_found('identity document')
    if record.revision != expected:
        raise _revision_conflict(record.revision)
    changes = payload.model_dump(exclude_unset=True, exclude={'document_number'})
    if 'document_number' in payload.model_fields_set:
        changes.update(
            protected_value=_seal(protected_values, payload.document_number),
            masked_value=masked_value(payload.document_number),
        )
    return _update(repository, principal, record, expected, changes, project_identity_document)


def deactivate_record(
    repository: AccountDataRepository,
    principal: Principal,
    kind: str,
    resource_id: str,
    if_match: str | None,
) -> RetirementResult:
    expected = parse_if_match(if_match)
    getters = {
        'policy': repository.get_policy,
        'payment destination': repository.get_payment_destination,
        'identity document': repository.get_identity_document,
    }
    record = getters[kind](resource_id, principal.subject)
    if record is None:
        raise _not_found(kind)
    if record.revision != expected:
        raise _revision_conflict(record.revision)
    if not record.active:
        _, identifier, _ = account_record_identity(record)
        return RetirementResult(resource_id=identifier, revision=record.revision)
    updated = record.model_copy(
        update={'active': False, 'revision': record.revision + 1, 'updated_at': now_utc()}
    )
    try:
        repository.update_account_record(
            updated, expected, _account_audit(updated, principal, action='retired')
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    _, identifier, _ = account_record_identity(updated)
    return RetirementResult(resource_id=identifier, revision=updated.revision)


def select_policy(
    repository: AccountDataRepository,
    persistence: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: SelectPolicyNumberRequest,
    idempotency_header: str | None,
    if_match: str | None,
) -> ClaimPolicySelectionResponse:
    key = require_idempotency_key(idempotency_header)
    expected = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/policy-selections'
    fingerprint = request_fingerprint(
        {'claim_id': claim_id, 'policy_id': payload.policy_id, 'expected_revision': expected}
    )
    replay = persistence.find_idempotency(principal.subject, route, key)
    if replay is not None:
        if replay.request_fingerprint != fingerprint or replay.response_payload is None:
            raise _idempotency_conflict()
        return ClaimPolicySelectionResponse.model_validate(replay.response_payload)
    claim = persistence.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found('claim')
    if claim.revision != expected:
        raise _revision_conflict(claim.revision)
    if claim.terminal_disposition is not None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='A terminal claim cannot select a policy.',
        )
    policy = repository.get_policy(payload.policy_id, principal.subject)
    if policy is None or not policy.active:
        raise _not_found('policy')
    validate_registered_field_value(
        'policy.policy_number', policy.policy_number, status=FormStatus.PROPOSED
    )
    timestamp = now_utc()
    source_ref = f'policy:{policy.policy_id}:revision:{policy.revision}'
    proposed = resolve_form_change(
        field_code='policy.policy_number',
        existing=claim.form.get('policy.policy_number'),
        proposal=ProposedFormChange(
            field_code='policy.policy_number',
            value=policy.policy_number,
            source=FormSource.CLAIMANT,
            status=FormStatus.PROPOSED,
            needed_for=NeededFor.CURRENT_ACTION,
            reported_text='Selected a saved policy number.',
        ),
        source_ref=source_ref,
        message_text=None,
        timestamp=timestamp,
        accepted_status=FormStatus.PROPOSED,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
    )
    updated_claim = claim.model_copy(
        update={
            'form': {**claim.form, 'policy.policy_number': proposed},
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    response = ClaimPolicySelectionResponse(
        claim_id=claim_id, revision=updated_claim.revision, proposed_field=proposed
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=persistence,
        recomputation_reason='account_policy_selected',
        trigger_source_refs=[source_ref],
        created_at=timestamp,
    )
    audit = AuditEventEnvelope(
        event_id=new_id('aud'),
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM, subject_id=claim_id, claim_id=claim_id
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason='Claimant selected a saved policy number for Claim prefill.',
        source_refs=[source_ref],
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=key,
        claim_revision=updated_claim.revision,
        created_at=timestamp,
    )
    try:
        repository.save_policy_selection(
            updated_claim,
            expected,
            policy.policy_id,
            policy.revision,
            idempotency,
            evaluation,
            audit,
        )
    except PolicySelectionConflict as error:
        raise ApiError(
            status_code=409,
            code='POLICY_SELECTION_CONFLICT',
            message='The selected policy changed or is no longer available. Reload policy state.',
            details=[ErrorDetail(field='policy_id', reason=error.reason)],
            retryable=True,
        ) from error
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    except (IdempotencyConflict, KeyError) as error:
        replay = persistence.find_idempotency(principal.subject, route, key)
        if (
            replay is None
            or replay.request_fingerprint != fingerprint
            or replay.response_payload is None
        ):
            if isinstance(error, KeyError):
                raise _not_found('policy') from error
            raise _idempotency_conflict() from error
        return ClaimPolicySelectionResponse.model_validate(replay.response_payload)
    return response


def _payout_contact_response(
    persistence: PersistenceRepository,
    identity_repository: IdentityRepository,
    claim: WorkingClaim,
) -> ClaimPayoutContactSelectionResponse:
    contact_preference = claim.form.get('claimant.contact_preference')
    if claim.payment_destination_id is None or contact_preference is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The saved payout and contact selection could not be restored.',
            retryable=True,
        )
    projected_next_step = claimant_next_step(
        persistence,
        claim,
        None,
        identity_repository=identity_repository,
    )
    primary_action = project_claimant_primary_action(
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        next_step=projected_next_step,
        external_service_action=None,
    )
    return ClaimPayoutContactSelectionResponse(
        claim_id=claim.claim_id,
        revision=claim.revision,
        payment_destination_id=claim.payment_destination_id,
        contact_preference=contact_preference,
        customer_next_step=projected_next_step,
        primary_action=primary_action,
    )


def select_payout_contact(
    repository: AccountDataRepository,
    persistence: PersistenceRepository,
    identity_repository: IdentityRepository,
    principal: Principal,
    claim_id: str,
    payload: SelectPayoutContactRequest,
    idempotency_header: str | None,
    if_match: str | None,
) -> ClaimPayoutContactSelectionResponse:
    key = require_idempotency_key(idempotency_header)
    expected = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/payout-contact-selections'
    fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'payment_destination_id': payload.payment_destination_id,
            'contact_preference': payload.contact_preference,
            'expected_revision': expected,
        }
    )
    replay = persistence.find_idempotency(principal.subject, route, key)
    if replay is not None:
        if replay.request_fingerprint != fingerprint or replay.response_payload is None:
            raise _idempotency_conflict()
        restored = ClaimPayoutContactSelectionResponse.model_validate(replay.response_payload)
        replay_claim = persistence.get_claim(claim_id, principal.subject)
        if (
            replay_claim is not None
            and replay_claim.revision == restored.revision
            and replay_claim.payment_destination_id == restored.payment_destination_id
        ):
            return _payout_contact_response(persistence, identity_repository, replay_claim)
        return restored

    claim = persistence.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found('claim')
    if claim.revision != expected:
        raise _revision_conflict(claim.revision)
    if claim.terminal_disposition is not None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='A terminal claim cannot change payout and contact selection.',
        )

    external_action = claimant_assessor_action(persistence, claim)
    projected_next_step = claimant_next_step(
        persistence,
        claim,
        external_action,
        identity_repository=identity_repository,
    )
    current_action = project_claimant_primary_action(
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        next_step=projected_next_step,
        external_service_action=external_action,
    )
    if (
        current_action.action_code != 'claimant.review_payout_contact'
        or not current_action.available
    ):
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Payout and contact selection is not the current claimant action.',
        )

    destination = repository.get_payment_destination(
        payload.payment_destination_id, principal.subject
    )
    if destination is None or not destination.active:
        raise _not_found('payment destination')

    contact_preference = payload.contact_preference.strip().lower()
    try:
        validate_registered_field_value(
            'claimant.contact_preference',
            contact_preference,
            status=FormStatus.CONFIRMED,
        )
    except ValueError as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The preferred contact method is not supported.',
            details=[ErrorDetail(field='contact_preference', reason=str(error))],
        ) from error

    account = identity_repository.get_account(principal.subject)
    if account is None or not account.active:
        raise _not_found('claimant account')
    if contact_preference == 'email' and not account.email.strip():
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The selected contact method has no usable destination.',
            details=[ErrorDetail(field='contact_preference', reason='Add an email address first.')],
        )
    if contact_preference in {'phone', 'sms'} and not account.phone.strip():
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The selected contact method has no usable destination.',
            details=[ErrorDetail(field='contact_preference', reason='Add a phone number first.')],
        )

    timestamp = now_utc()
    payment_source_ref = (
        f'payment_destination:{destination.payment_destination_id}:revision:{destination.revision}'
    )
    contact_field_ref = (
        f'claim:{claim.claim_id}:revision:{claim.revision + 1}:field:claimant.contact_preference'
    )
    contact_authority_ref = f'claimant_profile:revision:{account.revision}'
    contact_field = resolve_form_change(
        field_code='claimant.contact_preference',
        existing=claim.form.get('claimant.contact_preference'),
        proposal=ProposedFormChange(
            field_code='claimant.contact_preference',
            value=contact_preference,
            source=FormSource.CLAIMANT,
            status=FormStatus.CONFIRMED,
            needed_for=NeededFor.CURRENT_ACTION,
            reported_text='Selected the preferred contact method for this Claim.',
        ),
        source_ref=contact_field_ref,
        message_text=None,
        timestamp=timestamp,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
        explicit_correction=(
            claim.form.get('claimant.contact_preference') is not None
            and claim.form['claimant.contact_preference'].value != contact_preference
        ),
    )
    contact_field = contact_field.model_copy(
        update={
            'source_refs': list(dict.fromkeys([*contact_field.source_refs, contact_authority_ref])),
        }
    )
    updated_claim = claim.model_copy(
        update={
            'payment_destination_id': destination.payment_destination_id,
            'form': {**claim.form, 'claimant.contact_preference': contact_field},
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=persistence,
        recomputation_reason='payout_contact_selected',
        trigger_source_refs=[
            payment_source_ref,
            contact_field_ref,
            contact_authority_ref,
        ],
        created_at=timestamp,
    )
    response = _payout_contact_response(
        persistence,
        identity_repository,
        updated_claim,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    audit = AuditEventEnvelope(
        event_id=new_id('aud'),
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim_id,
            claim_id=claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason='Claimant selected a protected payout destination and preferred contact channel.',
        source_refs=[
            payment_source_ref,
            'field:claimant.contact_preference',
            contact_authority_ref,
        ],
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=key,
        claim_revision=updated_claim.revision,
        created_at=timestamp,
    )
    try:
        repository.save_payout_contact_selection(
            updated_claim,
            expected,
            destination.payment_destination_id,
            destination.revision,
            identity_repository,
            account.revision,
            contact_preference,
            idempotency,
            evaluation,
            audit,
        )
    except ClaimantContactSelectionConflict as error:
        raise ApiError(
            status_code=409,
            code='CONTACT_AUTHORITY_CONFLICT',
            message=(
                'The claimant contact details changed before the selection was saved. '
                'Reload contact details and try again.'
            ),
            details=[ErrorDetail(field='contact_preference', reason=error.reason)],
            retryable=True,
        ) from error
    except PaymentDestinationSelectionConflict as error:
        raise ApiError(
            status_code=409,
            code='PAYMENT_DESTINATION_SELECTION_CONFLICT',
            message=(
                'The selected payment destination changed or is no longer available. '
                'Reload payout details.'
            ),
            details=[ErrorDetail(field='payment_destination_id', reason=error.reason)],
            retryable=True,
        ) from error
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    except (IdempotencyConflict, KeyError) as error:
        replay = persistence.find_idempotency(principal.subject, route, key)
        if (
            replay is None
            or replay.request_fingerprint != fingerprint
            or replay.response_payload is None
        ):
            if isinstance(error, KeyError):
                raise _not_found('payment destination') from error
            raise _idempotency_conflict() from error
        return ClaimPayoutContactSelectionResponse.model_validate(replay.response_payload)

    persisted_claim = persistence.get_claim(claim_id, principal.subject)
    if persisted_claim is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The saved payout and contact selection could not be restored.',
            retryable=True,
        )
    return _payout_contact_response(persistence, identity_repository, persisted_claim)
