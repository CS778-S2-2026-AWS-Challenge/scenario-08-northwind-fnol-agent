import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, TypeVar, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.adapters.claims_service import AssessorServiceAdapter, ClaimsServiceAdapter
from backend.adapters.evidence_storage import EvidenceStorage
from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.api.account_data import claim_router as claim_account_data_router
from backend.api.assets import claim_router as claim_assets_router
from backend.api.realtime import realtime_stream
from backend.core.auth import Principal, require_claimant
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.external_service_registry import capability_catalogue
from backend.domain.model_gateway import ModelGatewayError
from backend.domain.models import (
    ClaimantClaim,
    ClaimantExternalServiceResponse,
    ClaimantSession,
    ClaimCreationResponse,
    ClaimListResponse,
    ContentsItemEvidenceAssociationListResponse,
    ContentsItemEvidenceAssociationMutationResponse,
    CreateClaimRequest,
    CreateClaimResponse,
    CreateContentsItemEvidenceAssociationRequest,
    CreateMessageRequest,
    CreateMotorOtherDriverRequest,
    ExternalCapabilityProjection,
    ExternalServiceOfferDecisionRequest,
    FormConfirmationRequest,
    FormConfirmationResponse,
    FormPatchRequest,
    FormPatchResponse,
    GrantAssessorConsentRequest,
    MessageListResponse,
    MessageTurnResponse,
    MotorOtherDriverMutationResponse,
    MotorOtherDriverProjection,
    PauseSessionResponse,
    StartSessionRequest,
    WorkflowState,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent import AgentTurnProvider
from backend.services.agent_action_execution import ClaimantRuntimeActionDispatcher
from backend.services.agent_turn_progress import AgentTurnProgressReporter
from backend.services.claim_creation import create_claim_from_confirmed_report
from backend.services.claim_data import (
    create_contents_item_evidence_association,
    create_motor_other_driver,
    get_motor_other_driver,
    list_contents_item_evidence_associations,
)
from backend.services.claimant_action_projection import project_claimant_primary_action
from backend.services.claimant_events import claimant_event_revision
from backend.services.claims import (
    confirm_form_fields,
    get_claim,
    get_session,
    list_claims,
    pause_session,
    promote_anonymous_claim,
    start_claim,
    update_form,
)
from backend.services.conversation_compaction import (
    compact_conversation_after_response_if_enabled,
)
from backend.services.external_capability_dispatcher import ExternalCapabilityDispatcher
from backend.services.external_service_entry import ExternalServiceEntryDecision
from backend.services.external_service_offers import (
    continue_granted_service_offers,
    decide_external_service_offer,
    message_external_actions,
)
from backend.services.external_services import grant_assessor_consent, request_assessor_routing
from backend.services.message_history import list_claim_messages
from backend.services.messages import submit_message
from backend.services.model_profiles import select_model_profile
from backend.services.resume import start_session_with_recovery
from backend.services.runtime_agent_policy import RuntimeAgentPolicyResolver

router = APIRouter(prefix='/api/v1/claims', tags=['claimant'])
router.include_router(claim_assets_router)
router.include_router(claim_account_data_router)
logger = logging.getLogger(__name__)


class RevisionedClaimDataMutation(Protocol):
    revision: int


ClaimDataMutationT = TypeVar('ClaimDataMutationT', bound=RevisionedClaimDataMutation)


def _execute_logged_claim_data_mutation(
    *,
    operation: str,
    request: Request,
    claim_id: str,
    item_id: str | None = None,
    mutate: Callable[[], ClaimDataMutationT],
) -> ClaimDataMutationT:
    context = {
        'request_id': str(getattr(request.state, 'request_id', 'unavailable')),
        'claim_id': claim_id,
    }
    if item_id is not None:
        context['item_id'] = item_id
    try:
        result = mutate()
    except ApiError as error:
        logger.info(
            operation,
            extra={**context, 'outcome': 'rejected', 'error_code': error.code},
        )
        raise
    except Exception:
        logger.exception(
            operation,
            extra={**context, 'outcome': 'failed', 'error_code': 'INTERNAL_ERROR'},
        )
        raise
    logger.info(
        operation,
        extra={
            **context,
            'outcome': 'succeeded',
            'claim_revision': result.revision,
        },
    )
    return result


def repository_for(request: Request) -> PersistenceRepository:
    return cast(PersistenceRepository, request.app.state.claim_repository)


def agent_for(request: Request) -> AgentTurnProvider:
    return cast(AgentTurnProvider, request.app.state.agent_turn_provider)


def runtime_agent_policy_for(request: Request) -> RuntimeAgentPolicyResolver:
    return cast(RuntimeAgentPolicyResolver, request.app.state.runtime_agent_policy_resolver)


def action_dispatcher_for(request: Request) -> ClaimantRuntimeActionDispatcher:
    return cast(
        ClaimantRuntimeActionDispatcher,
        request.app.state.claimant_runtime_action_dispatcher,
    )


def claims_adapter_for(request: Request) -> ClaimsServiceAdapter:
    return cast(ClaimsServiceAdapter, request.app.state.claims_service_adapter)


def assessor_adapter_for(request: Request) -> AssessorServiceAdapter:
    return cast(AssessorServiceAdapter, request.app.state.assessor_service_adapter)


def _assessor_entry_for(request: Request) -> ExternalServiceEntryDecision:
    return cast(ExternalServiceEntryDecision, request.app.state.assessor_service_entry)


def external_capability_dispatcher_for(request: Request) -> ExternalCapabilityDispatcher:
    return cast(
        ExternalCapabilityDispatcher,
        request.app.state.external_capability_dispatcher,
    )


def policy_history_adapter_for(request: Request) -> PolicyHistoryAdapter:
    return cast(PolicyHistoryAdapter, request.app.state.policy_history_adapter)


def evidence_storage_for(request: Request) -> EvidenceStorage:
    return cast(EvidenceStorage, request.app.state.evidence_storage)


@router.post('', response_model=CreateClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(
    request: Request,
    payload: CreateClaimRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> CreateClaimResponse:
    if payload.model_profile_id is not None:
        payload = payload.model_copy(
            update={'model_profile_id': select_model_profile(request, payload.model_profile_id)}
        )
    elif request.app.state.settings.agent_runtime_profile.value == 'model_gateway':
        payload = payload.model_copy(
            update={'model_profile_id': select_model_profile(request, None)}
        )
    return start_claim(repository_for(request), principal, payload, idempotency_key)


@router.get('', response_model=ClaimListResponse)
def read_claims(
    request: Request,
    principal: Principal = Depends(require_claimant),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    workflow_state: WorkflowState | None = Query(default=None),
    updated_after: datetime | None = Query(default=None),
) -> ClaimListResponse:
    return list_claims(
        repository_for(request),
        principal,
        limit=limit,
        cursor=cursor,
        workflow_state=workflow_state,
        updated_after=updated_after,
    )


@router.get('/{claim_id}', response_model=ClaimantClaim)
def read_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> ClaimantClaim:
    return get_claim(repository_for(request), principal, claim_id)


@router.post(
    '/{claim_id}/motor-other-driver',
    response_model=MotorOtherDriverMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_claim_motor_other_driver(
    claim_id: str,
    payload: CreateMotorOtherDriverRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> MotorOtherDriverMutationResponse:
    return _execute_logged_claim_data_mutation(
        operation='claim_data.motor_other_driver.create',
        request=request,
        claim_id=claim_id,
        mutate=lambda: create_motor_other_driver(
            repository_for(request),
            principal,
            claim_id,
            payload,
            idempotency_key,
            if_match,
        ),
    )


@router.get('/{claim_id}/motor-other-driver', response_model=MotorOtherDriverProjection)
def read_claim_motor_other_driver(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> MotorOtherDriverProjection:
    return get_motor_other_driver(repository_for(request), principal, claim_id)


@router.post(
    '/{claim_id}/contents-items/{item_id}/evidence-associations',
    response_model=ContentsItemEvidenceAssociationMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_claim_contents_item_evidence_association(
    claim_id: str,
    item_id: str,
    payload: CreateContentsItemEvidenceAssociationRequest,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ContentsItemEvidenceAssociationMutationResponse:
    return _execute_logged_claim_data_mutation(
        operation='claim_data.contents_item_evidence.create',
        request=request,
        claim_id=claim_id,
        item_id=item_id,
        mutate=lambda: create_contents_item_evidence_association(
            repository_for(request),
            principal,
            claim_id,
            item_id,
            payload,
            idempotency_key,
            if_match,
        ),
    )


@router.get(
    '/{claim_id}/contents-items/{item_id}/evidence-associations',
    response_model=ContentsItemEvidenceAssociationListResponse,
)
def read_claim_contents_item_evidence_associations(
    claim_id: str,
    item_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> ContentsItemEvidenceAssociationListResponse:
    return list_contents_item_evidence_associations(
        repository_for(request),
        principal,
        claim_id,
        item_id,
        limit=limit,
        cursor=cursor,
    )


@router.get('/{claim_id}/external-capabilities', response_model=list[ExternalCapabilityProjection])
def read_external_capabilities(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> list[ExternalCapabilityProjection]:
    """Return the claimant-safe capability catalogue for one authorised Claim."""

    claim = get_claim(repository_for(request), principal, claim_id)
    return list(capability_catalogue(claim.incident_type))


@router.post('/{claim_id}/promote', response_model=ClaimantClaim)
def promote_claim(
    claim_id: str,
    request: Request,
    anonymous_session: str | None = Header(default=None, alias='X-Northwind-Anonymous-Session'),
    principal: Principal = Depends(require_claimant),
) -> ClaimantClaim:
    if principal.auth_source == 'anonymous:browser_session':
        raise ApiError(
            status_code=401,
            code='AUTHENTICATION_REQUIRED',
            message='An authenticated claimant session is required.',
        )
    return promote_anonymous_claim(
        repository_for(request), principal, claim_id, anonymous_session or ''
    )


@router.post(
    '/{claim_id}/creation',
    response_model=ClaimCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_external_claim(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimCreationResponse:
    return create_claim_from_confirmed_report(
        repository_for(request),
        claims_adapter_for(request),
        action_dispatcher_for(request),
        principal,
        claim_id,
        idempotency_key,
        if_match,
    )


@router.post(
    '/{claim_id}/assessor-routing/consent',
    response_model=ClaimantExternalServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_assessor_consent(
    claim_id: str,
    payload: GrantAssessorConsentRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimantExternalServiceResponse:
    result, replayed = grant_assessor_consent(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
        if_match,
    )
    response.status_code = status.HTTP_200_OK if replayed else status.HTTP_201_CREATED
    return result


@router.post(
    '/{claim_id}/assessor-routing',
    response_model=ClaimantExternalServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_assessor_routing(
    claim_id: str,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimantExternalServiceResponse:
    result, replayed = request_assessor_routing(
        repository_for(request),
        assessor_adapter_for(request),
        _assessor_entry_for(request),
        principal,
        claim_id,
        idempotency_key,
        if_match,
    )
    response.status_code = status.HTTP_200_OK if replayed else status.HTTP_201_CREATED
    return result


@router.post(
    '/{claim_id}/external-service-offers/{offer_id}/decision',
    response_model=ClaimantExternalServiceResponse,
)
def decide_external_offer(
    claim_id: str,
    offer_id: str,
    payload: ExternalServiceOfferDecisionRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimantExternalServiceResponse:
    result, replayed = decide_external_service_offer(
        repository_for(request),
        principal,
        claim_id,
        offer_id,
        payload,
        idempotency_key,
        if_match,
    )
    current = repository_for(request).get_claim(claim_id, principal.subject)
    if current is not None:
        if not replayed and payload.decision == 'grant':
            continue_granted_service_offers(
                repository_for(request),
                principal,
                current,
                assessor_adapter=assessor_adapter_for(request),
                assessor_entry=_assessor_entry_for(request),
                capability_dispatcher=external_capability_dispatcher_for(request),
            )
            current = repository_for(request).get_claim(claim_id, principal.subject) or current
        actions = message_external_actions(
            repository_for(request), current, result.action.agent_message_id or ''
        )
        action = next(
            (candidate for candidate in actions if candidate.offer_id == offer_id),
            result.action,
        )
        result = result.model_copy(
            update={
                'revision': current.revision,
                'action': action,
                'customer_next_step': current.customer_next_step,
                'primary_action': project_claimant_primary_action(
                    claim_id=claim_id,
                    claim_revision=current.revision,
                    next_step=current.customer_next_step,
                    external_service_action=None,
                ),
            }
        )
    response.status_code = status.HTTP_200_OK if replayed else status.HTTP_201_CREATED
    return result


@router.post(
    '/{claim_id}/sessions',
    response_model=ClaimantSession,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    claim_id: str,
    request: Request,
    payload: StartSessionRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> ClaimantSession:
    # A resume request must let the service derive the profile from the
    # persisted session. Only new sessions, or explicit selections, go
    # through the catalog default/validation path.
    if payload.model_profile_id is not None or payload.intent == 'new':
        payload = payload.model_copy(
            update={'model_profile_id': select_model_profile(request, payload.model_profile_id)}
        )
    return start_session_with_recovery(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
    )


@router.post(
    '/{claim_id}/sessions/{session_id}/pause',
    response_model=PauseSessionResponse,
)
def pause_claim_session(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(
        default=None,
        alias='Idempotency-Key',
    ),
    if_match: str | None = Header(
        default=None,
        alias='If-Match',
    ),
) -> PauseSessionResponse:
    request_id = str(
        getattr(
            request.state,
            'request_id',
            'unavailable',
        )
    )

    try:
        result = pause_session(
            repository_for(request),
            principal,
            claim_id,
            session_id,
            idempotency_key,
            if_match,
        )
    except ApiError as error:
        logger.info(
            'claim_session.pause',
            extra={
                'request_id': request_id,
                'claim_id': claim_id,
                'session_id': session_id,
                'outcome': 'rejected',
                'error_code': error.code,
            },
        )
        raise
    except Exception:
        logger.exception(
            'claim_session.pause',
            extra={
                'request_id': request_id,
                'claim_id': claim_id,
                'session_id': session_id,
                'outcome': 'failed',
            },
        )
        raise

    logger.info(
        'claim_session.pause',
        extra={
            'request_id': request_id,
            'claim_id': claim_id,
            'session_id': session_id,
            'outcome': 'paused',
            'claim_revision': result.claim.revision,
        },
    )

    return result


@router.get('/{claim_id}/sessions/{session_id}', response_model=ClaimantSession)
def read_session(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
) -> ClaimantSession:
    return get_session(repository_for(request), principal, claim_id, session_id)


@router.post(
    '/{claim_id}/sessions/{session_id}/messages',
    response_model=MessageTurnResponse,
)
def create_message(
    claim_id: str,
    session_id: str,
    request: Request,
    payload: CreateMessageRequest,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> MessageTurnResponse:
    reporter = AgentTurnProgressReporter(
        repository_for(request),
        claim_id=claim_id,
        customer_id=principal.subject,
        session_id=session_id,
        turn_id=payload.client_message_id,
    )
    runtime_policy_resolver = runtime_agent_policy_for(request)
    if payload.model_profile_id is not None:
        payload = payload.model_copy(
            update={'model_profile_id': select_model_profile(request, payload.model_profile_id)}
        )
    try:
        result = submit_message(
            repository=repository_for(request),
            agent=agent_for(request),
            policy_history_adapter=policy_history_adapter_for(request),
            principal=principal,
            claim_id=claim_id,
            session_id=session_id,
            payload=payload,
            idempotency_key=idempotency_key,
            if_match=if_match,
            runtime_agent_policy_resolver=runtime_policy_resolver,
            action_dispatcher=action_dispatcher_for(request),
            evidence_storage=evidence_storage_for(request),
            assessor_adapter=assessor_adapter_for(request),
            assessor_entry=_assessor_entry_for(request),
            external_capability_dispatcher=external_capability_dispatcher_for(request),
            progress_reporter=reporter,
        )
    except ApiError as error:
        reporter.failed(retryable=error.retryable)
        raise
    except ModelGatewayError as error:
        reporter.failed(retryable=error.retryable)
        raise
    except Exception:
        reporter.failed(retryable=True)
        raise
    reporter.completed()
    background_tasks.add_task(
        compact_conversation_after_response_if_enabled,
        repository_for(request),
        runtime_policy_resolver,
        principal.subject,
        claim_id,
        session_id,
    )
    return result


@router.get(
    '/{claim_id}/sessions/{session_id}/messages',
    response_model=MessageListResponse,
)
def read_messages(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    before: datetime | None = Query(default=None),
    after: datetime | None = Query(default=None),
) -> MessageListResponse:
    return list_claim_messages(
        repository_for(request),
        principal,
        claim_id,
        session_id,
        limit=limit,
        cursor=cursor,
        before=before,
        after=after,
    )


@router.get(
    '/{claim_id}/sessions/{session_id}/events',
    response_class=StreamingResponse,
    responses={200: {'content': {'text/event-stream': {}}}},
)
def read_claim_events(
    claim_id: str,
    session_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant),
    after_revision: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias='Last-Event-ID'),
) -> StreamingResponse:
    repository = repository_for(request)
    current_revision = claimant_event_revision(repository, principal, claim_id, session_id)
    if after_revision > current_revision:
        raise ApiError(
            status_code=409,
            code='INVALID_EVENT_CURSOR',
            message='The live-update revision is newer than the current claim.',
            retryable=True,
            current_revision=current_revision,
        )
    legacy_cursor_revision = after_revision
    realtime_cursor = cursor
    if last_event_id is not None:
        try:
            legacy_cursor_revision = int(last_event_id)
        except ValueError:
            realtime_cursor = last_event_id
        if legacy_cursor_revision < 0:
            raise ApiError(
                status_code=409,
                code='INVALID_EVENT_CURSOR',
                message='The legacy Claim event revision is invalid.',
                retryable=True,
                details=[
                    ErrorDetail(
                        field='Last-Event-ID',
                        reason='Expected a non-negative revision.',
                    )
                ],
            )
    if legacy_cursor_revision > current_revision:
        raise ApiError(
            status_code=409,
            code='INVALID_EVENT_CURSOR',
            message='The live-update revision is newer than the current claim.',
            retryable=True,
            current_revision=current_revision,
        )
    return realtime_stream(
        request,
        principal,
        cursor=realtime_cursor,
        claim_id=claim_id,
        legacy_session_id=session_id,
        legacy_after_revision=legacy_cursor_revision,
        legacy_current_revision=current_revision,
    )


@router.patch('/{claim_id}/form', response_model=FormPatchResponse)
def patch_form(
    claim_id: str,
    request: Request,
    payload: FormPatchRequest,
    principal: Principal = Depends(require_claimant),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> FormPatchResponse:
    return update_form(repository_for(request), principal, claim_id, payload, if_match)


@router.post('/{claim_id}/form/confirmations', response_model=FormConfirmationResponse)
def confirm_form(
    claim_id: str,
    request: Request,
    payload: FormConfirmationRequest,
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> FormConfirmationResponse:
    return confirm_form_fields(
        repository_for(request),
        principal,
        claim_id,
        payload,
        idempotency_key,
        if_match,
    )
