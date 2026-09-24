"""Issue #928 final claimant agreement and submission authority."""

from hashlib import sha256

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import (
    AcceptClaimAgreementRequest,
    ActorType,
    AgreementAcceptanceResponse,
    ClaimAgreementAcceptance,
    ClaimAgreementAcceptanceProjection,
    ClaimAgreementConfirmationDefinition,
    ClaimSubmissionAgreement,
    WorkingClaim,
)
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.external_services import (
    claimant_current_action_projection,
    payout_contact_is_complete,
)
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

_AGREEMENT = ClaimSubmissionAgreement(
    agreement_id='northwind-fnol-claim-submission',
    version='1',
    display_copy=(
        'I have reviewed the information shown for this claim and confirm that I want '
        'to submit the claim using the information currently recorded.'
    ),
    confirmations=[
        ClaimAgreementConfirmationDefinition(
            key='reviewed_and_confirmed',
            label=(
                'I have reviewed the claim information and confirm that I want to '
                'submit it as currently recorded.'
            ),
            required=True,
        )
    ],
)


def current_submission_agreement() -> ClaimSubmissionAgreement:
    """Return an isolated copy of the authoritative current agreement."""

    return _AGREEMENT.model_copy(deep=True)


def agreement_acceptance_is_current(claim: WorkingClaim) -> bool:
    """Return whether the latest acceptance authorises this exact Claim revision."""

    required = {item.key for item in _AGREEMENT.confirmations if item.required}
    for acceptance in reversed(claim.agreement_acceptances):
        if (
            acceptance.agreement_id == _AGREEMENT.agreement_id
            and acceptance.agreement_version == _AGREEMENT.version
            and acceptance.resulting_claim_revision == claim.revision
            and all(acceptance.confirmations.get(key) is True for key in required)
        ):
            return True
    return False


def _invalid_state(message: str) -> ApiError:
    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message=message,
    )


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The idempotency key was reused for a different agreement acceptance.',
    )


def _validate_request(payload: AcceptClaimAgreementRequest) -> None:
    if payload.agreement_id != _AGREEMENT.agreement_id or payload.version != _AGREEMENT.version:
        raise _invalid_state(
            'The submission agreement changed. Reload the Claim and review the current version.'
        )

    known = {item.key for item in _AGREEMENT.confirmations}
    unknown = sorted(set(payload.confirmations) - known)
    if unknown:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The agreement confirmation payload contains unknown fields.',
            details=[
                ErrorDetail(
                    field=f'confirmations.{key}',
                    reason='This confirmation key is not part of the current agreement.',
                )
                for key in unknown
            ],
        )

    invalid_required = [
        item.key
        for item in _AGREEMENT.confirmations
        if item.required and payload.confirmations.get(item.key) is not True
    ]
    if invalid_required:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='Every required agreement confirmation must be explicitly accepted.',
            details=[
                ErrorDetail(
                    field=f'confirmations.{key}',
                    reason='Explicit confirmation is required.',
                )
                for key in invalid_required
            ],
        )


def accept_claim_agreement(
    repository: PersistenceRepository,
    identity_repository: IdentityRepository,
    principal: Principal,
    claim_id: str,
    payload: AcceptClaimAgreementRequest,
    idempotency_header: str | None,
    if_match: str | None,
) -> tuple[AgreementAcceptanceResponse, bool]:
    """Record one explicit, versioned and revision-bound claimant acceptance."""

    key = require_idempotency_key(idempotency_header)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/agreement-acceptances'
    fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'expected_revision': expected_revision,
            **payload.model_dump(mode='json'),
        }
    )

    replay = repository.find_idempotency(principal.subject, route, key)
    if replay is not None:
        if replay.request_fingerprint != fingerprint or replay.response_payload is None:
            raise _idempotency_conflict()
        return AgreementAcceptanceResponse.model_validate(replay.response_payload), True

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )

    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )

    if claim.external_claim is not None or claim.terminal_disposition is not None:
        raise _invalid_state(
            'A completed or terminal Claim cannot accept a new submission agreement.'
        )

    _external_action, _next_step, current_action = claimant_current_action_projection(
        repository,
        claim,
        identity_repository=identity_repository,
    )
    if (
        current_action.action_code != 'claimant.review_agreement'
        or not current_action.available
        or not payout_contact_is_complete(repository, claim, identity_repository)
    ):
        raise _invalid_state(
            'Complete the current payout and contact step before confirming submission.'
        )

    _validate_request(payload)

    timestamp = now_utc()
    seed = (
        f'{principal.subject}:{claim_id}:{key}:{payload.agreement_id}:{payload.version}'
    ).encode()
    acceptance_id = f'aga_{sha256(seed).hexdigest()[:24]}'

    acceptance = ClaimAgreementAcceptance(
        acceptance_id=acceptance_id,
        customer_id=principal.subject,
        claim_id=claim_id,
        agreement_id=payload.agreement_id,
        agreement_version=payload.version,
        confirmations=dict(payload.confirmations),
        accepted_against_claim_revision=claim.revision,
        resulting_claim_revision=claim.revision + 1,
        accepted_at=timestamp,
    )

    updated = claim.model_copy(
        deep=True,
        update={
            'revision': claim.revision + 1,
            'updated_at': timestamp,
            'agreement_acceptances': [
                *claim.agreement_acceptances,
                acceptance,
            ],
        },
    )

    _external_action, projected_next_step, primary_action = (
        claimant_current_action_projection(
            repository,
            updated,
            identity_repository=identity_repository,
            agreement_accepted=True,
        )
    )

    response = AgreementAcceptanceResponse(
        claim_id=updated.claim_id,
        revision=updated.revision,
        agreement=current_submission_agreement(),
        acceptance=ClaimAgreementAcceptanceProjection(
            acceptance_id=acceptance.acceptance_id,
            agreement_id=acceptance.agreement_id,
            version=acceptance.agreement_version,
            confirmations=dict(acceptance.confirmations),
            accepted_at=acceptance.accepted_at,
        ),
        customer_next_step=projected_next_step,
        primary_action=primary_action,
    )

    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=updated.claim_id,
        session_id=updated.active_session_id or '',
        action_code='claimant.review_agreement',
        target_ref=updated.claim_id,
        response_payload=response.model_dump(mode='json'),
    )

    audit_event = AuditEventEnvelope(
        event_id=f'aud_{sha256(f"agreement:{acceptance_id}".encode()).hexdigest()[:24]}',
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=updated.claim_id,
            claim_id=updated.claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason='Claimant explicitly confirmed the current submission agreement.',
        source_refs=[
            f'agreement:{acceptance.agreement_id}:version:{acceptance.agreement_version}',
            f'agreement_acceptance:{acceptance.acceptance_id}',
        ],
        visibility=AuditVisibility.AUDIT_ONLY,
        correlation_id=key,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=timestamp,
    )

    try:
        repository.save_claim_mutation_with_audit(
            updated,
            expected_revision=claim.revision,
            idempotency=idempotency,
            audit_events=(audit_event,),
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed while the agreement was being recorded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise _idempotency_conflict() from conflict

    return response, False
