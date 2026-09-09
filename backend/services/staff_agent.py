import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.knowledge import (
    KnowledgeRetrievalUnavailable,
    KnowledgeRetriever,
    KnowledgeSearch,
)
from backend.domain.model_gateway import (
    STAFF_AGENT_PRIVACY_CLASS,
    STAFF_AGENT_PURPOSE,
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelRole,
)
from backend.domain.models import (
    AcceptHandoffRequest,
    ContractModel,
    CreateCoworkRequest,
    CreateStaffActionRequest,
    CreateStaffMessageRequest,
    CreateTransferRequest,
    DecideCollaborationRequest,
    RequeueClaimRequest,
    ResolveHandoffRequest,
    SignalDecisionRequest,
    UpdateStaffActionRequest,
    WorkingClaim,
)
from backend.domain.staff_agent import (
    CreateStaffAgentMessageRequest,
    CreateStaffAgentSessionRequest,
    ExecuteStaffAgentDraftRequest,
    StaffAgentDraftExecutionOutcome,
    StaffAgentDraftExecutionResponse,
    StaffAgentMessage,
    StaffAgentMessageRole,
    StaffAgentMessagesResponse,
    StaffAgentModelOutput,
    StaffAgentSession,
    StaffAgentSessionsResponse,
    StaffAgentTurnResponse,
)
from backend.domain.workbench_action_registry import WORKBENCH_ACTION_REGISTRY
from backend.prompts import STAFF_ASSISTANT_PROMPT_ID, load_staff_assistant_prompt
from backend.repositories.protocols import (
    IdempotencyConflict,
    PersistenceRepository,
    StaffAgentDraftSource,
)
from backend.services.knowledge_manifest import approved_version_for_product
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.ownership import (
    create_cowork_request,
    create_transfer_request,
    decide_collaboration_request,
    requeue_claim,
)
from backend.services.runtime_configuration import RuntimeConfigurationResolutionError
from backend.services.review_writeback import decide_review_signal
from backend.services.staff_actions import (
    accept_handoff,
    create_staff_action,
    resolve_handoff,
    send_staff_message,
    update_staff_action,
)
from backend.services.support import now_utc, require_idempotency_key


@dataclass(frozen=True, slots=True)
class StaffAgentContext:
    question: str
    claims: tuple[Mapping[str, Any], ...]
    conversation: tuple[Mapping[str, Any], ...]
    knowledge: tuple[Mapping[str, Any], ...]
    knowledge_status: str
    model_profile_id: str = 'qwen-local'
    references: tuple[Mapping[str, Any], ...] = ()
    review_signals: tuple[Mapping[str, Any], ...] = ()
    handoffs: tuple[Mapping[str, Any], ...] = ()
    staff_actions: tuple[Mapping[str, Any], ...] = ()
    customer_updates: tuple[Mapping[str, Any], ...] = ()
    external_services: tuple[Mapping[str, Any], ...] = ()
    context_limitations: tuple[str, ...] = ()
    registered_actions: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class StaffAgentProviderResult:
    output: StaffAgentModelOutput
    provider_model: str | None = None
    provider_request_id: str | None = None


class StaffAgentTurnProvider(Protocol):
    def respond(self, context: StaffAgentContext) -> StaffAgentProviderResult:
        raise NotImplementedError


class GatewayStaffAgent:
    def __init__(
        self,
        gateway: ModelGateway,
        operations: ModelOperationsRecorder | None = None,
    ) -> None:
        self._gateway = gateway
        self._instruction = load_staff_assistant_prompt()
        self._operations = operations

    def respond(self, context: StaffAgentContext) -> StaffAgentProviderResult:
        request = ModelRequest(
            model_profile_id=context.model_profile_id,
            purpose=STAFF_AGENT_PURPOSE,
            privacy_class=STAFF_AGENT_PRIVACY_CLASS,
            prompt_version=STAFF_ASSISTANT_PROMPT_ID,
            required_capabilities=ModelCapabilities(structured_output=True),
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content=self._instruction),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            'question': context.question,
                            'explicit_claim_scope': list(context.claims),
                            'session_history': list(context.conversation),
                            'knowledge_status': context.knowledge_status,
                            'knowledge_citations': list(context.knowledge),
                            'references': list(context.references),
                            'review_signals': list(context.review_signals),
                            'handoffs': list(context.handoffs),
                            'staff_actions': list(context.staff_actions),
                            'customer_updates': list(context.customer_updates),
                            'external_services': list(context.external_services),
                            'context_limitations': list(context.context_limitations),
                            'registered_actions': list(context.registered_actions),
                        },
                        separators=(',', ':'),
                    ),
                ),
            ],
            response_schema=StaffAgentModelOutput.model_json_schema(),
        )
        started_at = perf_counter()
        response = None
        try:
            response = self._gateway.complete(request)
            if response.completion_status is ModelCompletionStatus.INCOMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.INCOMPLETE_RESPONSE)
            if response.completion_status is ModelCompletionStatus.REFUSED:
                raise ModelGatewayError(ModelGatewayErrorCode.REFUSED_RESPONSE)
            if (
                response.completion_status is not ModelCompletionStatus.COMPLETE
                or response.structured_output is None
            ):
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            try:
                output = StaffAgentModelOutput.model_validate(response.structured_output)
            except ValueError:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
            result = StaffAgentProviderResult(
                output=output,
                provider_model=response.provider_model,
                provider_request_id=response.provider_request_id,
            )
        except ModelGatewayError as error:
            if self._operations is not None:
                self._operations.failed(
                    request.purpose,
                    error,
                    (perf_counter() - started_at) * 1000,
                    response,
                )
            raise
        if self._operations is not None:
            self._operations.succeeded(
                request.purpose,
                response,
                (perf_counter() - started_at) * 1000,
            )
        return result


class ProfileSelectingStaffAgent:
    """Resolve the session-bound published profile before each staff turn."""

    def __init__(
        self,
        gateway_for_profile: Callable[[str], ModelGateway],
        operations: ModelOperationsRecorder | None = None,
    ) -> None:
        self._gateway_for_profile = gateway_for_profile
        self._operations = operations

    def respond(self, context: StaffAgentContext) -> StaffAgentProviderResult:
        gateway = self._gateway_for_profile(context.model_profile_id)
        return GatewayStaffAgent(gateway, self._operations).respond(context)


_KNOWLEDGE_CONFIGURATION_LIMITATION = (
    'The active runtime release does not select an approved knowledge version.'
)
_KNOWLEDGE_UNAVAILABLE_LIMITATION = 'The knowledge service is temporarily unavailable.'
_KNOWLEDGE_TIMEOUT_LIMITATION = 'The knowledge service did not respond within the request budget.'


def _knowledge_retrieval_timed_out(code: str) -> bool:
    return code.strip().casefold() in {'timeout', 'provider_timeout', 'request_timeout'}


def _require_staff(principal: Principal) -> None:
    if principal.actor_type != 'staff':
        raise ApiError(status_code=403, code='ACCESS_DENIED', message='Staff access is required.')


def _session(
    repository: PersistenceRepository, principal: Principal, session_id: str
) -> StaffAgentSession:
    session = repository.get_staff_agent_session(session_id, principal.subject)
    if session is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The Staff Agent session was not found.',
        )
    return session


def create_staff_agent_session(
    repository: PersistenceRepository,
    principal: Principal,
    payload: CreateStaffAgentSessionRequest,
    model_profile_selector: Callable[[str | None], str] | None = None,
) -> StaffAgentSession:
    _require_staff(principal)
    timestamp = now_utc()
    selected_profile = (
        model_profile_selector(payload.model_profile_id)
        if model_profile_selector is not None
        else (payload.model_profile_id or 'qwen-local')
    )
    session = StaffAgentSession(
        session_id=new_id('sas'),
        staff_id=principal.subject,
        title=payload.title,
        model_profile_id=selected_profile,
        created_at=timestamp,
        updated_at=timestamp,
    )
    repository.save_staff_agent_session(session)
    return session


def list_staff_agent_sessions(
    repository: PersistenceRepository, principal: Principal
) -> StaffAgentSessionsResponse:
    _require_staff(principal)
    sessions = repository.list_staff_agent_sessions(principal.subject)
    sessions.sort(key=lambda item: (item.updated_at, item.session_id), reverse=True)
    return StaffAgentSessionsResponse(items=sessions)


def list_staff_agent_messages(
    repository: PersistenceRepository, principal: Principal, session_id: str
) -> StaffAgentMessagesResponse:
    _require_staff(principal)
    _session(repository, principal, session_id)
    messages = repository.list_staff_agent_messages(session_id, principal.subject)
    messages.sort(
        key=lambda item: (
            item.created_at,
            0 if item.role is StaffAgentMessageRole.STAFF else 1,
            item.message_id,
        )
    )
    return StaffAgentMessagesResponse(items=messages)


def _claim_context(repository: PersistenceRepository, claim: WorkingClaim) -> dict[str, Any]:
    messages = []
    for session in repository.list_sessions_for_claim(claim.claim_id, claim.customer_id):
        messages.extend(
            repository.list_messages(claim.claim_id, session.session_id, claim.customer_id)
        )
    messages.sort(key=lambda item: (item.created_at, item.message_id))
    retrievals = repository.list_retrieval_records(claim.claim_id, claim.customer_id)
    review_signals = repository.list_review_signals(claim.claim_id, claim.customer_id)
    handoffs = repository.list_handoffs(claim.claim_id, claim.customer_id)
    staff_actions = repository.list_staff_actions(claim.claim_id)
    customer_updates = repository.list_customer_updates(claim.claim_id)
    limitations: list[str] = []
    try:
        tasks = repository.list_external_tasks_internal(claim.claim_id)
        requests = repository.list_external_task_requests_internal(claim.claim_id)
        requests_by_task = {item.task_id: item for item in requests}
        external_services = [
            {
                'task': item.model_dump(mode='json'),
                'request': (
                    requests_by_task[item.task_id].model_dump(mode='json')
                    if item.task_id in requests_by_task
                    else None
                ),
            }
            for item in tasks
        ]
    except RuntimeError:
        external_services = []
        limitations.append('External-service records are unavailable for this Claim.')
    return {
        'claimant': {'customer_id': claim.customer_id},
        'claim_id': claim.claim_id,
        'revision': claim.revision,
        'incident_type': claim.incident_type,
        'claim_state': claim.claim_state.model_dump(mode='json'),
        'form': {code: field.model_dump(mode='json') for code, field in claim.form.items()},
        'evidence': [
            item.model_dump(mode='json')
            for item in repository.list_evidence(claim.claim_id, claim.customer_id)
        ],
        'references': [item.model_dump(mode='json') for item in retrievals],
        'review_signals': [item.model_dump(mode='json') for item in review_signals],
        'handoffs': [item.model_dump(mode='json') for item in handoffs],
        'staff_actions': [item.model_dump(mode='json') for item in staff_actions],
        'customer_updates': [item.model_dump(mode='json') for item in customer_updates],
        'external_services': external_services,
        'context_limitations': limitations,
        'recent_messages': [item.model_dump(mode='json') for item in messages[-20:]],
        'customer_next_step': claim.customer_next_step.model_dump(mode='json'),
    }


def _knowledge_context(
    retriever: KnowledgeRetriever,
    question: str,
    claims: Sequence[WorkingClaim],
    knowledge_version_for: Callable[[str], str | None] | None = None,
) -> tuple[tuple[Mapping[str, Any], ...], str, tuple[str, ...]]:
    products: list[str | None] = list(
        sorted({claim.incident_type for claim in claims if claim.incident_type})
    )
    if not products:
        products = [None]
    citations: dict[str, Mapping[str, Any]] = {}
    try:
        for product in products:
            version = (
                knowledge_version_for(product)
                if knowledge_version_for is not None and product is not None
                else approved_version_for_product(product)
                if product is not None
                else None
            )
            if version is None and product is not None:
                return (), 'unavailable', (_KNOWLEDGE_CONFIGURATION_LIMITATION,)
            for chunk in retriever.search(
                KnowledgeSearch(
                    text=question,
                    jurisdiction='NZ',
                    visibility='customer_and_staff',
                    authority='northwind_synthetic_demo',
                    version=version,
                    insurer='Northwind Insurance',
                    product=product,
                    effective_at=datetime.now(UTC),
                    limit=3,
                )
            ):
                citations[chunk.chunk_id] = {
                    'chunk_id': chunk.chunk_id,
                    'document_id': chunk.document_id,
                    'title': chunk.title,
                    'section_path': chunk.section_path,
                    'source_uri': chunk.source_uri,
                    'version': chunk.version,
                    'checksum': chunk.checksum,
                    'text': chunk.text,
                }
    except KnowledgeRetrievalUnavailable as error:
        if _knowledge_retrieval_timed_out(error.code):
            return (), 'timeout', (_KNOWLEDGE_TIMEOUT_LIMITATION,)
        return (), 'unavailable', (_KNOWLEDGE_UNAVAILABLE_LIMITATION,)
    except RuntimeConfigurationResolutionError:
        return (), 'unavailable', (_KNOWLEDGE_CONFIGURATION_LIMITATION,)
    return (
        tuple(citations.values()),
        'evidence_found' if citations else 'no_evidence',
        (),
    )


def submit_staff_agent_message(
    repository: PersistenceRepository,
    retriever: KnowledgeRetriever,
    provider: StaffAgentTurnProvider | None,
    principal: Principal,
    session_id: str,
    payload: CreateStaffAgentMessageRequest,
    *,
    knowledge_version_for: Callable[[str], str | None] | None = None,
) -> StaffAgentTurnResponse:
    _require_staff(principal)
    session = _session(repository, principal, session_id)
    existing = repository.find_staff_agent_message_by_client_id(
        session_id, principal.subject, payload.client_message_id
    )
    if existing is not None:
        if existing.content != payload.content or existing.claim_ids != payload.claim_ids:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The Staff Agent message identity was reused with different content.',
            )
        assistant = next(
            (
                item
                for item in repository.list_staff_agent_messages(session_id, principal.subject)
                if item.in_reply_to == existing.message_id
            ),
            None,
        )
        if assistant is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The saved Staff Agent response could not be restored.',
                retryable=True,
            )
        return StaffAgentTurnResponse(
            session=session, staff_message=existing, assistant_message=assistant
        )
    if provider is None:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='The Staff Agent model profile is not configured.',
            retryable=True,
        )

    claim_ids = list(dict.fromkeys(payload.claim_ids))
    if claim_ids != payload.claim_ids:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='Each Claim can be attached only once.',
        )
    claims: list[WorkingClaim] = []
    for claim_id in claim_ids:
        claim = repository.get_claim_internal(claim_id)
        if claim is None:
            raise ApiError(
                status_code=404,
                code='RESOURCE_NOT_FOUND',
                message='An explicitly selected Claim was not found.',
            )
        claims.append(claim)

    history = repository.list_staff_agent_messages(session_id, principal.subject)[-12:]
    knowledge, knowledge_status, knowledge_limitations = _knowledge_context(
        retriever,
        payload.content,
        claims,
        knowledge_version_for,
    )
    claim_contexts = tuple(_claim_context(repository, claim) for claim in claims)
    context_limitations = tuple(
        knowledge_limitations
        + tuple(
            limitation
            for context in claim_contexts
            for limitation in context.get('context_limitations', [])
        )
    )
    agent_context = StaffAgentContext(
        question=payload.content,
        model_profile_id=session.model_profile_id,
        claims=claim_contexts,
        conversation=tuple(
            {
                'role': item.role.value,
                'content': item.content,
                'claim_ids': item.claim_ids,
            }
            for item in history
        ),
        knowledge=knowledge,
        knowledge_status=knowledge_status,
        references=tuple(item for context in claim_contexts for item in context['references']),
        review_signals=tuple(
            item for context in claim_contexts for item in context['review_signals']
        ),
        handoffs=tuple(item for context in claim_contexts for item in context['handoffs']),
        staff_actions=tuple(
            item for context in claim_contexts for item in context['staff_actions']
        ),
        customer_updates=tuple(
            item for context in claim_contexts for item in context['customer_updates']
        ),
        external_services=tuple(
            item for context in claim_contexts for item in context['external_services']
        ),
        context_limitations=context_limitations,
        registered_actions=tuple(
            {
                'action_code': definition.action_code,
                'target_type': definition.target_type.value,
                'label': definition.label,
                'purpose': definition.purpose,
                'confirmation_level': definition.confirmation_level.value,
                'inputs': [
                    {
                        'field_code': item.field_code,
                        'required': item.required,
                        'choices': [choice[0] for choice in item.choices],
                    }
                    for item in definition.inputs
                ],
            }
            for definition in WORKBENCH_ACTION_REGISTRY.values()
        ),
    )
    result = provider.respond(agent_context)
    if any(
        draft.claim_id is not None and draft.claim_id not in claim_ids
        for draft in result.output.drafts
    ):
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)

    timestamp = now_utc()
    persisted_drafts = [
        draft.model_copy(update={'draft_id': draft.draft_id or new_id('sdr')})
        for draft in result.output.drafts
    ]
    staff_message = StaffAgentMessage(
        message_id=new_id('sam'),
        session_id=session_id,
        staff_id=principal.subject,
        role=StaffAgentMessageRole.STAFF,
        content=payload.content,
        claim_ids=claim_ids,
        client_message_id=payload.client_message_id,
        created_at=timestamp,
    )
    assistant_message = StaffAgentMessage(
        message_id=new_id('sam'),
        session_id=session_id,
        staff_id=principal.subject,
        role=StaffAgentMessageRole.ASSISTANT,
        content=result.output.answer,
        claim_ids=claim_ids,
        drafts=persisted_drafts,
        source_refs=[
            *(f'claim:{claim.claim_id}:revision:{claim.revision}' for claim in claims),
            *(f'knowledge:{item["chunk_id"]}' for item in knowledge),
            *(f'retrieval:{item["retrieval_id"]}' for item in agent_context.references),
            *(f'signal:{item["signal_id"]}' for item in agent_context.review_signals),
            *(f'handoff:{item["handoff_id"]}' for item in agent_context.handoffs),
            *(f'action:{item["action_id"]}' for item in agent_context.staff_actions),
            *(f'customer-update:{item["update_id"]}' for item in agent_context.customer_updates),
            *(
                f'external-task:{item["task"]["task_id"]}'
                for item in agent_context.external_services
            ),
        ],
        in_reply_to=staff_message.message_id,
        provider_model=result.provider_model,
        provider_request_id=result.provider_request_id,
        created_at=timestamp,
    )
    title = session.title
    if title == 'New Staff Agent session':
        title = payload.content.strip()[:80]
    updated_session = session.model_copy(update={'title': title, 'updated_at': timestamp})
    try:
        repository.save_staff_agent_turn(updated_session, staff_message, assistant_message)
    except IdempotencyConflict as conflict:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The Staff Agent turn conflicted with an existing message.',
        ) from conflict
    return StaffAgentTurnResponse(
        session=updated_session,
        staff_message=staff_message,
        assistant_message=assistant_message,
    )


def execute_staff_agent_draft(
    repository: PersistenceRepository,
    principal: Principal,
    session_id: str,
    message_id: str,
    draft_id: str,
    payload: ExecuteStaffAgentDraftRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> StaffAgentDraftExecutionResponse:
    """Promote one saved Staff Agent draft through a registered Workbench action.

    The Agent never receives mutation authority. This adapter only selects an existing
    revision-checked Workbench route after explicit staff confirmation; those routes own
    permission, idempotency, audit and Claim State persistence.
    """

    _require_staff(principal)
    _session(repository, principal, session_id)
    message = next(
        (
            item
            for item in repository.list_staff_agent_messages(session_id, principal.subject)
            if item.message_id == message_id
        ),
        None,
    )
    if message is None or message.role is not StaffAgentMessageRole.ASSISTANT:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The Staff Agent draft message was not found.',
        )
    draft = next((item for item in message.drafts if item.draft_id == draft_id), None)
    if draft is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The Staff Agent draft was not found.',
        )
    if not payload.confirmed:
        raise ApiError(
            status_code=409,
            code='CONFIRMATION_REQUIRED',
            message='Staff confirmation is required before executing this draft.',
        )
    if draft.action_code is None:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='This draft is informational and has no registered business action.',
        )
    claim_id = draft.claim_id
    if claim_id is None or claim_id not in message.claim_ids:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='An executable draft must name one Claim in the session scope.',
        )
    target_ref = draft.target_ref or claim_id
    action_code = draft.action_code
    request_payload = payload.payload or draft.payload
    key = require_idempotency_key(idempotency_key)
    source = StaffAgentDraftSource(
        session_id=session_id,
        message_id=message_id,
        draft_id=draft_id,
    )

    result: ContractModel
    try:
        if action_code == 'human.accept_handoff':
            result = accept_handoff(
                repository,
                principal,
                claim_id,
                target_ref,
                AcceptHandoffRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'conversation.send_claimant_message':
            claim = repository.get_claim_internal(claim_id)
            if claim is None or claim.active_session_id != target_ref:
                raise ApiError(
                    status_code=422,
                    code='VALIDATION_ERROR',
                    message='The draft target is not the Claim active claimant session.',
                )
            result = send_staff_message(
                repository,
                principal,
                claim_id,
                CreateStaffMessageRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'human.resolve_handoff':
            result = resolve_handoff(
                repository,
                principal,
                claim_id,
                target_ref,
                ResolveHandoffRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'signal.record_decision':
            result = decide_review_signal(
                repository,
                principal,
                claim_id,
                target_ref,
                SignalDecisionRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'work_item.create':
            result = create_staff_action(
                repository,
                principal,
                claim_id,
                CreateStaffActionRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'work_item.update':
            result = update_staff_action(
                repository,
                principal,
                claim_id,
                target_ref,
                UpdateStaffActionRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code in {'ownership.request_cowork', 'ownership.invite_cowork'}:
            result = create_cowork_request(
                repository,
                principal,
                claim_id,
                CreateCoworkRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'ownership.request_transfer':
            result = create_transfer_request(
                repository,
                principal,
                claim_id,
                CreateTransferRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code in {'ownership.decide_cowork', 'ownership.decide_transfer'}:
            result = decide_collaboration_request(
                repository,
                principal,
                claim_id,
                target_ref,
                DecideCollaborationRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        elif action_code == 'ownership.requeue':
            result = requeue_claim(
                repository,
                principal,
                claim_id,
                RequeueClaimRequest.model_validate(request_payload),
                key,
                if_match,
                source=source,
            )
        else:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='The draft action is not registered for Staff Workbench execution.',
            )
    except ValueError as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The draft payload does not match the registered action contract.',
        ) from error

    return StaffAgentDraftExecutionResponse(
        session_id=session_id,
        message_id=message_id,
        draft_id=draft_id,
        claim_id=claim_id,
        action_code=action_code,
        target_ref=target_ref,
        outcome=StaffAgentDraftExecutionOutcome.EXECUTED,
        result=result.model_dump(mode='json'),
    )
