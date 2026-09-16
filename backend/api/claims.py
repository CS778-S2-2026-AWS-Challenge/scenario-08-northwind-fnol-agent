import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.adapters.claims_service import AssessorServiceAdapter, ClaimsServiceAdapter
from backend.adapters.evidence_storage import EvidenceStorage
from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.core.auth import Principal, require_claimant
from backend.core.errors import ApiError
from backend.domain.external_service_registry import capability_catalogue
from backend.domain.models import (
    ClaimantClaim,
    ClaimantExternalServiceResponse,
    ClaimantSession,
    ClaimCreationResponse,
    ClaimListResponse,
    CreateClaimRequest,
    CreateClaimResponse,
    CreateMessageRequest,
    ExternalCapabilityProjection,
    ExternalServiceOfferDecisionRequest,
    FormConfirmationRequest,
    FormConfirmationResponse,
    FormPatchRequest,
    FormPatchResponse,
    GrantAssessorConsentRequest,
    MessageListResponse,
    MessageTurnResponse,
    PauseSessionResponse,
    StartSessionRequest,
    WorkflowState,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent import AgentTurnProvider
from backend.services.agent_action_execution import ClaimantRuntimeActionDispatcher
from backend.services.claim_creation import create_claim_from_confirmed_report
from backend.services.claimant_action_projection import project_claimant_primary_action
from backend.services.claimant_events import claimant_change_after, claimant_event_revision
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
logger = logging.getLogger(__name__)


def _sse_event(event: str, data: dict[str, object], event_id: str | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f'id: {event_id}')
    lines.extend(
        (
            f'event: {event}',
            f'data: {json.dumps(data, separators=(",", ":"))}',
            '',
            '',
        )
    )
    return '\n'.join(lines)


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
    principal: Principal = Depends(require_claimant),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> MessageTurnResponse:
    if payload.model_profile_id is not None:
        payload = payload.model_copy(
            update={'model_profile_id': select_model_profile(request, payload.model_profile_id)}
        )
    return submit_message(
        repository=repository_for(request),
        agent=agent_for(request),
        policy_history_adapter=policy_history_adapter_for(request),
        principal=principal,
        claim_id=claim_id,
        session_id=session_id,
        payload=payload,
        idempotency_key=idempotency_key,
        if_match=if_match,
        runtime_agent_policy_resolver=runtime_agent_policy_for(request),
        action_dispatcher=action_dispatcher_for(request),
        evidence_storage=evidence_storage_for(request),
        assessor_adapter=assessor_adapter_for(request),
        assessor_entry=_assessor_entry_for(request),
        external_capability_dispatcher=external_capability_dispatcher_for(request),
    )


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
) -> StreamingResponse:
    repository = repository_for(request)
    current_revision = claimant_event_revision(repository, principal, claim_id, session_id)
    if after_revision > current_revision:
        claimant_change_after(repository, principal, claim_id, session_id, after_revision)

    async def stream() -> AsyncIterator[str]:
        cursor = after_revision
        heartbeat_at = asyncio.get_running_loop().time()
        yield 'retry: 1500\n: connected\n\n'
        while not await request.is_disconnected():
            change = claimant_change_after(
                repository,
                principal,
                claim_id,
                session_id,
                cursor,
            )
            if change is not None:
                cursor = change.claim_revision
                yield _sse_event(
                    'claim.updated',
                    change.model_dump(mode='json'),
                    change.event_id,
                )
            now = asyncio.get_running_loop().time()
            if now - heartbeat_at >= 15:
                yield ': keep-alive\n\n'
                heartbeat_at = now
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'X-Accel-Buffering': 'no',
        },
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
