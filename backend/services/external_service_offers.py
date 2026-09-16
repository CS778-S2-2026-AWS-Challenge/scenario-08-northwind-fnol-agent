"""Message-bound third-party service offers owned by the Runtime."""

from __future__ import annotations

import re
from contextlib import suppress
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from backend.adapters.claims_service import AssessorServiceAdapter
from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.external_service_registry import REGISTRY_VERSION, service_registry_entry
from backend.domain.external_services import (
    ExternalTaskAuthorisation,
    ExternalTaskDelivery,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskRequest,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    ClaimantExternalServiceAction,
    ClaimantExternalServiceResponse,
    ClaimantExternalServiceStatus,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    ExternalServiceOfferDecisionRequest,
    IntegrationSource,
    WorkingClaim,
)
from backend.domain.runtime import ExternalServiceOfferMetadata, RuntimeWorkItemRecord
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.claimant_action_projection import project_claimant_primary_action
from backend.services.external_capability_dispatcher import ExternalCapabilityDispatcher
from backend.services.external_service_entry import ExternalServiceEntryDecision
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

_INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        'vehicle_damage_assessment_routing',
        (
            r'\b(?:damage|vehicle|car)\s+assessment\b',
            r'\b(?:assessor|assess the damage)\b',
            r'\bestimate\b.*\brepair',
        ),
    ),
    ('vehicle_recovery_request', (r'\b(?:tow|towing|vehicle recovery)\b',)),
    ('vehicle_repairer_booking', (r'\b(?:book|arrange|schedule)\b.*\brepair',)),
    ('home_emergency_repair_request', (r'\bemergency\b.*\b(?:home|house|repair)',)),
    ('contents_specialist_assessment', (r'\bspecialist\b.*\b(?:contents|item|belonging)',)),
    ('repairer_information_or_link', (r'\b(?:find|recommend|contact)\b.*\brepairer',)),
    ('police_105_reporting_guidance', (r'\b(?:police|105)\b.*\b(?:report|contact|call)',)),
    ('police_traffic_crash_report_guidance', (r'\btraffic crash report\b',)),
)


def detected_service_intents(
    message_text: str | None,
    proposed: list[dict[str, str]],
    *,
    product_family: str | None,
) -> list[dict[str, str]]:
    """Merge model semantics with bounded direct-request recognition."""

    candidates = list(proposed)
    text = (message_text or '').lower()
    for service_identity, patterns in _INTENT_PATTERNS:
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            candidates.append(
                {'service_identity': service_identity, 'requested_action': 'submit_request'}
            )
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = candidate.get('service_identity')
        action = candidate.get('requested_action', 'submit_request')
        if not isinstance(identity, str) or identity in seen or action != 'submit_request':
            continue
        try:
            entry = service_registry_entry(identity)
        except KeyError:
            continue
        if product_family and product_family not in entry.product_families:
            continue
        seen.add(identity)
        result.append(
            {
                'service_identity': identity,
                'requested_action': entry.requested_action,
            }
        )
        if len(result) == 3:
            break
    return result


def build_offer_metadata(
    *,
    claim: WorkingClaim,
    agent_message_id: str,
    trigger_message_id: str,
    intent: dict[str, str],
    dispatcher: ExternalCapabilityDispatcher | None = None,
) -> ExternalServiceOfferMetadata:
    entry = service_registry_entry(intent['service_identity'])
    discovery = (dispatcher or ExternalCapabilityDispatcher()).discover(
        entry.service_identity,
        product_family=claim.incident_type or entry.product_families[0],
    )
    if discovery.status != 'available':
        raise ValueError('The requested external capability is unavailable for this Claim family.')
    disclosure_fields = list(entry.disclosure_fields)
    evidence_ids: list[str] = []
    manifest = [_claimant_disclosure_label(field) for field in disclosure_fields]
    scope = {
        'claim_id': claim.claim_id,
        'agent_message_id': agent_message_id,
        'service_identity': entry.service_identity,
        'registry_version': REGISTRY_VERSION,
        'requested_action': intent['requested_action'],
        'disclosure_fields': disclosure_fields,
        'evidence_ids': evidence_ids,
    }
    fingerprint = request_fingerprint(scope)
    return ExternalServiceOfferMetadata(
        offer_id=f'offer_{sha256(fingerprint.encode()).hexdigest()[:24]}',
        agent_message_id=agent_message_id,
        trigger_message_id=trigger_message_id,
        service_identity=entry.service_identity,
        registry_version=REGISTRY_VERSION,
        requested_action=intent['requested_action'],
        disclosure_fields=disclosure_fields,
        evidence_ids=evidence_ids,
        disclosure_manifest=manifest,
        disclosure_fingerprint=fingerprint,
    )


def offer_work_item(
    *,
    claim: WorkingClaim,
    turn_id: str,
    offer: ExternalServiceOfferMetadata,
    timestamp: datetime,
) -> RuntimeWorkItemRecord:
    return RuntimeWorkItemRecord(
        work_item_id=offer.offer_id,
        claim_id=claim.claim_id,
        turn_id=turn_id,
        kind='external',
        subject_ref=f'external-offer:{offer.service_identity}',
        owner='claimant',
        status='open',
        blocks_action=None,
        source_refs=[offer.trigger_message_id, offer.agent_message_id],
        created_at=timestamp,
        updated_at=timestamp,
        external_offer=offer,
    )


def find_offer(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    offer_id: str,
) -> RuntimeWorkItemRecord | None:
    return next(
        (
            item
            for item in repository.list_runtime_work_items(claim.claim_id, claim.customer_id)
            if item.kind == 'external'
            and item.work_item_id == offer_id
            and item.external_offer is not None
        ),
        None,
    )


def message_external_actions(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    agent_message_id: str,
) -> list[ClaimantExternalServiceAction]:
    actions: list[ClaimantExternalServiceAction] = []
    for item in repository.list_runtime_work_items(claim.claim_id, claim.customer_id):
        offer = item.external_offer
        if item.kind != 'external' or offer is None or offer.agent_message_id != agent_message_id:
            continue
        entry = service_registry_entry(offer.service_identity)
        consent = next(
            (
                record
                for record in reversed(claim.external_service_consents)
                if record.offer_ref == offer.offer_id
            ),
            None,
        )
        has_request = consent is not None and _offer_has_request(
            repository, claim, consent.consent_ref
        )
        status = ClaimantExternalServiceStatus.CONSENT_REQUIRED
        lifecycle_status = 'consent_required'
        can_request = True
        if consent is not None:
            if consent.status is ExternalServiceConsentStatus.DECLINED:
                status = ClaimantExternalServiceStatus.CONSENT_DECLINED
                can_request = False
            elif consent.status is ExternalServiceConsentStatus.WITHDRAWN:
                status = ClaimantExternalServiceStatus.CONSENT_WITHDRAWN
                can_request = False
            elif not entry.uses_external_task:
                status = ClaimantExternalServiceStatus.MANUAL_AVAILABLE
                lifecycle_status = 'authorised'
                can_request = False
            else:
                status = ClaimantExternalServiceStatus.PENDING_INPUT
                lifecycle_status = 'authorised'
                can_request = False
        routing = None
        failure_code = None
        if (
            consent is not None
            and consent.status is ExternalServiceConsentStatus.GRANTED
            and offer.service_identity == 'vehicle_damage_assessment_routing'
        ):
            from backend.services.external_services import claimant_assessor_action

            assessor_action = claimant_assessor_action(repository, claim)
            if (
                assessor_action is not None
                and assessor_action.offer_id == offer.offer_id
                and assessor_action.status
                in {
                    ClaimantExternalServiceStatus.QUEUED,
                    ClaimantExternalServiceStatus.ASSIGNED,
                    ClaimantExternalServiceStatus.RETRYABLE_FAILURE,
                    ClaimantExternalServiceStatus.TERMINAL_FAILURE,
                    ClaimantExternalServiceStatus.AWAITING_RECONCILIATION,
                }
            ):
                status = assessor_action.status
                lifecycle_status = assessor_action.lifecycle_status
                routing = assessor_action.routing
                failure_code = assessor_action.failure_code
        elif consent is not None and consent.status is ExternalServiceConsentStatus.GRANTED:
            request = next(
                (
                    candidate
                    for candidate in repository.list_external_task_requests_internal(claim.claim_id)
                    if candidate.authorisation.claimant_consent_ref == consent.consent_ref
                ),
                None,
            )
            task = next(
                (
                    candidate
                    for candidate in repository.list_external_tasks_internal(claim.claim_id)
                    if request is not None and candidate.task_id == request.task_id
                ),
                None,
            )
            if task is not None:
                lifecycle_status = task.status.value
                if task.status is ExternalTaskOperationStatus.ACCEPTED:
                    status = ClaimantExternalServiceStatus.QUEUED
                elif task.status is ExternalTaskOperationStatus.RETRYABLE_FAILURE:
                    status = ClaimantExternalServiceStatus.RETRYABLE_FAILURE
                elif task.status is ExternalTaskOperationStatus.TERMINAL_FAILURE:
                    status = ClaimantExternalServiceStatus.TERMINAL_FAILURE
                elif task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
                    status = ClaimantExternalServiceStatus.AWAITING_RECONCILIATION
        status_labels = {
            ClaimantExternalServiceStatus.CONSENT_REQUIRED: 'Permission needed',
            ClaimantExternalServiceStatus.CONSENT_DECLINED: 'Not requested',
            ClaimantExternalServiceStatus.CONSENT_WITHDRAWN: 'Permission withdrawn',
            ClaimantExternalServiceStatus.PENDING_INPUT: 'Permission recorded',
            ClaimantExternalServiceStatus.MANUAL_AVAILABLE: 'Ready to use',
            ClaimantExternalServiceStatus.QUEUED: 'Request accepted',
            ClaimantExternalServiceStatus.ASSIGNED: 'Service assigned',
            ClaimantExternalServiceStatus.RETRYABLE_FAILURE: 'Request did not complete',
            ClaimantExternalServiceStatus.TERMINAL_FAILURE: 'Northwind review needed',
            ClaimantExternalServiceStatus.AWAITING_RECONCILIATION: 'Outcome not confirmed',
            ClaimantExternalServiceStatus.READY_TO_REQUEST: 'Ready to request',
        }
        actions.append(
            ClaimantExternalServiceAction(
                offer_id=offer.offer_id,
                agent_message_id=offer.agent_message_id,
                service_identity=entry.service_identity,
                registry_version=offer.registry_version,
                lifecycle_status=lifecycle_status,
                catalogue_reference=entry.catalogue_reference,
                capability_provenance=entry.provenance.value,
                access_form=entry.access_form,
                status_label=status_labels[status],
                status_detail=(
                    'Review and confirm the exact information Northwind may share.'
                    if status is ClaimantExternalServiceStatus.CONSENT_REQUIRED
                    else 'Northwind will continue when the registered requirements are ready.'
                ),
                pending_owner='claimant' if can_request else 'Northwind',
                next_action=(
                    'Confirm or decline this offer.'
                    if can_request
                    else 'Continue the claim journey.'
                ),
                limitation=entry.limitation,
                service_name=entry.service_name,
                provider=entry.provider_name,
                purpose=entry.purpose,
                requested_action=offer.requested_action,
                shared_data_summary=offer.disclosure_manifest,
                disclosure_fields=offer.disclosure_fields,
                evidence_ids=offer.evidence_ids,
                disclosure_fingerprint=offer.disclosure_fingerprint,
                official_url=entry.official_url,
                official_phone=entry.official_phone,
                uses_external_task=entry.uses_external_task,
                status=status,
                consent_status=consent.status if consent is not None else None,
                routing=routing,
                failure_code=failure_code,
                can_request=can_request,
                can_withdraw=(
                    consent is not None
                    and consent.status is ExternalServiceConsentStatus.GRANTED
                    and entry.uses_external_task
                    and not has_request
                ),
            )
        )
    return actions


def decide_external_service_offer(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    offer_id: str,
    payload: ExternalServiceOfferDecisionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> tuple[ClaimantExternalServiceResponse, bool]:
    """Record one exact offer decision without trusting client-authored scope."""

    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/external-service-offers/{offer_id}/decision'
    fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'offer_id': offer_id,
            'decision': payload.decision,
            'revision': expected_revision,
        }
    )
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused for a different service decision.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The saved service decision could not be restored.',
                retryable=True,
            )
        return ClaimantExternalServiceResponse.model_validate(existing.response_payload), True

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
            message='The claim changed after this offer was displayed.',
            retryable=True,
            current_revision=claim.revision,
        )
    item = find_offer(repository, claim, offer_id)
    if item is None or item.external_offer is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The external-service offer was not found.',
        )
    offer = item.external_offer
    entry = service_registry_entry(offer.service_identity)
    if offer.registry_version != REGISTRY_VERSION:
        raise ApiError(
            status_code=409,
            code='EXTERNAL_SERVICE_SCOPE_CHANGED',
            message='This service offer has changed. Review the new disclosure before continuing.',
        )
    expected_scope = request_fingerprint(
        {
            'claim_id': claim.claim_id,
            'agent_message_id': offer.agent_message_id,
            'service_identity': offer.service_identity,
            'registry_version': offer.registry_version,
            'requested_action': offer.requested_action,
            'disclosure_fields': offer.disclosure_fields,
            'evidence_ids': offer.evidence_ids,
        }
    )
    if expected_scope != offer.disclosure_fingerprint:
        raise ApiError(
            status_code=409,
            code='EXTERNAL_SERVICE_SCOPE_CHANGED',
            message='The stored service disclosure is no longer valid.',
        )

    current = next(
        (
            record
            for record in reversed(claim.external_service_consents)
            if record.offer_ref == offer.offer_id
        ),
        None,
    )
    timestamp = now_utc()
    if payload.decision == 'withdraw':
        if current is None or current.status is not ExternalServiceConsentStatus.GRANTED:
            raise ApiError(
                status_code=409,
                code='INVALID_STATE_TRANSITION',
                message='Only active permission can be withdrawn.',
            )
        if _offer_has_request(repository, claim, current.consent_ref):
            raise ApiError(
                status_code=409,
                code='INVALID_STATE_TRANSITION',
                message=(
                    'This request has already been sent. Its registered cancellation path '
                    'must be used instead of withdrawing consent.'
                ),
            )
        consent = current.model_copy(
            update={'status': ExternalServiceConsentStatus.WITHDRAWN, 'withdrawn_at': timestamp}
        )
        records = [
            consent if record.consent_ref == current.consent_ref else record
            for record in claim.external_service_consents
        ]
        event_type = AuditEventType.CONSENT_WITHDRAWN
    else:
        if current is not None:
            raise ApiError(
                status_code=409,
                code='INVALID_STATE_TRANSITION',
                message='This service offer already has a recorded decision.',
            )
        status = (
            ExternalServiceConsentStatus.GRANTED
            if payload.decision == 'grant'
            else ExternalServiceConsentStatus.DECLINED
        )
        consent = ExternalServiceConsent(
            consent_ref=f'cns_{sha256(f"{offer_id}:{principal.subject}:{key}".encode()).hexdigest()[:20]}',
            service_identity=offer.service_identity,
            requested_action=offer.requested_action,
            permitted_fields=offer.disclosure_fields,
            registry_version=offer.registry_version,
            offer_ref=offer.offer_id,
            disclosure_manifest=offer.disclosure_manifest,
            disclosure_fingerprint=offer.disclosure_fingerprint,
            evidence_ids=offer.evidence_ids,
            status=status,
            granted_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
            granted_at=timestamp,
        )
        records = [*claim.external_service_consents, consent]
        event_type = (
            AuditEventType.CONSENT_GRANTED
            if status is ExternalServiceConsentStatus.GRANTED
            else AuditEventType.CONSENT_DECLINED
        )

    updated = claim.model_copy(
        update={
            'external_service_consents': records,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    actions = message_external_actions(repository, updated, offer.agent_message_id)
    action = next(action for action in actions if action.offer_id == offer.offer_id)
    response = ClaimantExternalServiceResponse(
        claim_id=claim_id,
        revision=updated.revision,
        action=action,
        customer_next_step=updated.customer_next_step,
        primary_action=project_claimant_primary_action(
            claim_id=claim_id,
            claim_revision=updated.revision,
            next_step=updated.customer_next_step,
            external_service_action=None,
        ),
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
        event_id=f'aud_{sha256(f"{event_type.value}:{consent.consent_ref}:{key}".encode()).hexdigest()[:24]}',
        event_type=event_type,
        outcome=(
            AuditOutcome.SUCCEEDED
            if consent.status is not ExternalServiceConsentStatus.DECLINED
            else AuditOutcome.REJECTED
        ),
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
        reason=f'Claimant {payload.decision} decision for {entry.service_name}.',
        source_refs=[offer.offer_id, offer.agent_message_id],
        consent_ref=consent.consent_ref,
        consent_state=consent.status.value,
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=timestamp,
    )
    branch_evaluation = build_applied_branch_evaluation(
        updated,
        repository=repository,
        recomputation_reason='external_service_offer_decision',
        trigger_source_refs=[offer.offer_id, consent.consent_ref],
    )
    try:
        repository.save_claim_mutation_with_audit(
            updated,
            expected_revision=claim.revision,
            idempotency=idempotency,
            audit_events=(audit,),
            branch_evaluation=branch_evaluation,
        )
    except RevisionConflict as error:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed while the service decision was recorded.',
            retryable=True,
            current_revision=error.current_revision,
        ) from error
    except IdempotencyConflict as error:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The idempotency key was reused for a different service decision.',
        ) from error
    return response, False


def continue_granted_service_offers(
    repository: PersistenceRepository,
    principal: Principal,
    claim: WorkingClaim,
    *,
    assessor_adapter: AssessorServiceAdapter | None = None,
    assessor_entry: ExternalServiceEntryDecision | None = None,
    capability_dispatcher: ExternalCapabilityDispatcher | None = None,
) -> None:
    """Continue authorised work when a later turn supplies its requirements."""

    for consent in reversed(claim.external_service_consents):
        if consent.offer_ref is None or consent.status is not ExternalServiceConsentStatus.GRANTED:
            continue
        item = find_offer(repository, claim, consent.offer_ref)
        if item is None or item.external_offer is None:
            continue
        offer = item.external_offer
        entry = service_registry_entry(offer.service_identity)
        if not entry.uses_external_task:
            continue
        if offer.service_identity == 'vehicle_damage_assessment_routing':
            if (
                assessor_adapter is None
                or assessor_entry is None
                or claim.assessor_routing is not None
            ):
                continue
            from backend.services.external_services import request_assessor_routing

            with suppress(ApiError):
                request_assessor_routing(
                    repository,
                    assessor_adapter,
                    assessor_entry,
                    principal,
                    claim.claim_id,
                    f'external-offer-dispatch:{consent.offer_ref}',
                    str(claim.revision),
                )
            return
        if _generic_offer_ready(claim, offer) and not _offer_has_request(
            repository, claim, consent.consent_ref
        ):
            if capability_dispatcher is not None:
                _dispatch_generic_offer(
                    repository,
                    claim,
                    consent,
                    offer,
                    capability_dispatcher,
                )
            return


_DISCLOSURE_LABELS = {
    'claim_id': 'Northwind claim reference',
    'external_claim_id': 'Claims-system reference when one exists',
    'authorisation_ref': 'Northwind authorisation reference',
    'claimant_consent_ref': 'This permission reference',
    'requested_action': 'Requested service action',
    'location.region': 'Incident region',
    'incident.location': 'Incident location',
    'incident.description': 'Incident description',
    'vehicle.drivable': 'Whether the vehicle is drivable',
    'vehicle.damage_description': 'Vehicle damage description',
    'property.address': 'Insured property address',
    'property.ongoing_risk': 'Current property risk',
    'loss.description': 'Loss description',
    'contents.items': 'Confirmed affected contents items',
}


def _claimant_disclosure_label(field: str) -> str:
    return _DISCLOSURE_LABELS.get(field, field.replace('.', ' ').replace('_', ' ').title())


def _source_value(claim: WorkingClaim, source: str) -> Any:
    if source == 'contents.items':
        values = [
            {
                'item_id': item.item_id,
                'description': item.description,
                'category': item.category,
                'quantity': item.quantity,
                'loss_type': item.loss_type.value,
            }
            for item in claim.contents_items
            if item.status.value == 'confirmed'
        ]
        return values or None
    field = claim.form.get(source)
    if field is None or field.status.value != 'confirmed':
        return None
    return field.value


def _generic_offer_ready(claim: WorkingClaim, offer: ExternalServiceOfferMetadata) -> bool:
    entry = service_registry_entry(offer.service_identity)
    return all(
        _source_value(claim, source) not in (None, '', [], {}) for source in entry.required_fields
    )


def _offer_has_request(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    consent_ref: str,
) -> bool:
    return any(
        request.authorisation.claimant_consent_ref == consent_ref
        for request in repository.list_external_task_requests_internal(claim.claim_id)
    )


def _dispatch_generic_offer(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    consent: ExternalServiceConsent,
    offer: ExternalServiceOfferMetadata,
    dispatcher: ExternalCapabilityDispatcher,
) -> None:
    """Persist one provider-shaped request through the canonical lifecycle."""

    entry = service_registry_entry(offer.service_identity)
    timestamp = now_utc()
    identity = sha256(f'{claim.claim_id}:{offer.offer_id}'.encode()).hexdigest()[:20]
    task_id = f'tsk_{identity}'
    request_id = f'erq_{identity}'
    operation_id = f'op_{identity}'
    authority_ref = f'dec_{identity}'
    if claim.active_session_id is None:
        return
    decision = AgentDecisionRecord(
        decision_id=authority_ref,
        claim_id=claim.claim_id,
        session_id=claim.active_session_id,
        trigger_message_id=offer.trigger_message_id,
        action=AgentAction.PROCEED,
        action_code='external.submit_request',
        reason_codes=['EXTERNAL_SERVICE_OFFER_AUTHORISED'],
        customer_reason=(
            'Runtime validated the registered service, disclosure and claimant consent.'
        ),
        customer_response=f'Northwind is sending the {entry.service_name.lower()} request.',
        state_changes=[],
        proposed_signals=[],
        required_tools=[{'tool': 'external_service.submit_request', 'operation': 'submit_request'}],
        next_action_requirements=[],
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='external_service_offer_runtime',
            validated_by='external_service_registry',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        form_changes={},
        resulting_revision=claim.revision,
        created_at=timestamp,
    )
    repository.save_agent_decision(decision, claim.customer_id)
    task = ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim.claim_id,
        service_identity=offer.service_identity,
        requested_action=offer.requested_action,
        integration_source=IntegrationSource.FIXTURE,
        status=ExternalTaskOperationStatus.PREPARED,
        created_at=timestamp,
        updated_at=timestamp,
    )
    repository.save_external_task(task, claim.customer_id)
    request = ExternalTaskRequest(
        request_id=request_id,
        task_id=task_id,
        claim_id=claim.claim_id,
        service_identity=offer.service_identity,
        requested_action=offer.requested_action,
        purpose=entry.purpose,
        disclosed_fields=offer.disclosure_fields,
        authorisation=ExternalTaskAuthorisation(
            northwind_authority_ref=authority_ref,
            claimant_consent_ref=consent.consent_ref,
            authorised_revision=claim.revision,
        ),
        prepared_at=timestamp,
    )
    repository.save_external_task_request(request, claim.customer_id)
    reserved = repository.reserve_external_dispatch(
        claim.claim_id, request_id, claim.customer_id, timestamp, operation_id
    )
    if reserved is None:
        return

    payload = {source: _source_value(claim, source) for source in entry.disclosure_fields}
    result = dispatcher.execute(
        offer.service_identity,
        'submit_request',
        {
            **payload,
            'claim_id': claim.claim_id,
            'claim_revision': claim.revision,
            'operation_id': operation_id,
            'idempotency_key': offer.offer_id,
            'consent_ref': consent.consent_ref,
            'northwind_authority_ref': authority_ref,
        },
        product_family=claim.incident_type or entry.product_families[0],
    )
    if result.status != 'accepted':
        repository.release_external_dispatch(claim.claim_id, request_id, claim.customer_id)
        return
    sent_at = max(now_utc(), task.updated_at + timedelta(microseconds=1))
    repository.save_external_task_request(
        reserved.model_copy(update={'sent_at': sent_at}),
        claim.customer_id,
    )
    repository.save_external_task(
        task.model_copy(
            update={
                'status': ExternalTaskOperationStatus.ACCEPTED,
                'delivery': ExternalTaskDelivery.SUBMITTED,
                'delivery_evidence': f'operation:{operation_id}',
                'provider_reference': str(result.payload['provider_reference']),
                'updated_at': sent_at,
            }
        ),
        claim.customer_id,
    )
