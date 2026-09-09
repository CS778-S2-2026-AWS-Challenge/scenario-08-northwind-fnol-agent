import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from backend.domain.agent_tool_registry import tool_contract
from backend.domain.ids import new_id
from backend.domain.intake import infer_controlled_product_family
from backend.domain.knowledge import (
    KnowledgeRetrievalUnavailable,
    KnowledgeRetriever,
    KnowledgeSearch,
)
from backend.domain.model_gateway import (
    CLAIMANT_AGENT_PRIVACY_CLASS,
    CLAIMANT_AGENT_PURPOSE,
    ModelAgentProposal,
    ModelBranchContext,
    ModelCapabilities,
    ModelClaimContext,
    ModelClaimStateContext,
    ModelCompletionStatus,
    ModelContentsItemContext,
    ModelFieldSelectionContext,
    ModelFormFieldContext,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelKnowledgeCitation,
    ModelMessage,
    ModelProposedFormChange,
    ModelProvenanceMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRuntimeProposal,
    ModelTool,
    ModelTurnContext,
)
from backend.domain.models import (
    AgentAction,
    AgentProposalSource,
    FormSource,
    FormStatus,
    ModelDecisionProvenance,
    NeededFor,
    ProposedContentsItem,
    ProposedFormChange,
    RuntimeInvocationTrace,
    RuntimeTraceRecord,
)
from backend.prompts import MOTOR_CLAIMANT_PROMPT_ID, load_motor_claimant_prompt
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.services.agent import AgentProposal, AgentTurnContext, AgentTurnProvider
from backend.services.agent_tools import read_claim_for_runtime
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
    RuntimeConfigurationSnapshot,
)

_PROPOSAL_ADAPTER = TypeAdapter(ModelAgentProposal)
_RUNTIME_PROPOSAL_ADAPTER = TypeAdapter(ModelRuntimeProposal)
_SYSTEM_INSTRUCTION = load_motor_claimant_prompt()
_CONTEXT_TOOL_NAMES = frozenset({'knowledge_search', 'policy_history', 'claim_history'})

_MODEL_CONTEXT_FIELD_CODES = frozenset(
    {
        'claim.product_family',
        'incident.type',
        'incident.occurred_at',
        'incident.description',
        'incident.injury_or_danger',
        'incident.cause',
        'loss.description',
        'vehicle.damage_description',
        'vehicle.drivable',
        'property.affected_areas',
        'property.ongoing_risk',
        'property.habitable',
    }
)


def _knowledge_product(incident_type: str | None) -> str | None:
    """Resolve the canonical knowledge product scope for a Claim Context type.

    Args:
        incident_type: Claim Context incident/product family.

    Returns:
        The provider-neutral knowledge product scope, or ``None`` until the Claim Context
        identifies a supported product family.
    """
    return {
        'motor': 'motor',
        'home': 'home',
        # ``property`` is retained as a compatibility alias for older fixtures.
        'property': 'home',
        'contents': 'contents',
    }.get(incident_type or '')


def _model_turn_context(context: AgentTurnContext) -> ModelTurnContext:
    claim = context.claim
    branch = context.branch_evaluation
    model_field_codes = (
        {
            item.field_code
            for item in branch.field_selection
            if item.selection_state.value not in {'inactive', 'system_owned'}
        }
        if branch is not None
        else _MODEL_CONTEXT_FIELD_CODES
    )
    return ModelTurnContext(
        claim=ModelClaimContext(
            channel=claim.channel,
            locale=claim.locale,
            incident_type=claim.incident_type,
            claim_state=ModelClaimStateContext(
                evidence=claim.claim_state.evidence,
                customer_support=claim.claim_state.customer_support,
                urgency=claim.claim_state.urgency,
                workflow_state=claim.claim_state.workflow_state,
                next_action=claim.claim_state.next_action,
            ),
            form={
                field_code: ModelFormFieldContext(
                    value=field.value,
                    source=field.source,
                    status=field.status,
                    needed_for=field.needed_for,
                    confidence=field.confidence,
                    precision=field.precision,
                    source_refs=field.source_refs,
                )
                for field_code, field in claim.form.items()
                if field_code in model_field_codes and field.needed_for is NeededFor.CURRENT_ACTION
            },
            contents_items=[
                ModelContentsItemContext(
                    item_id=item.item_id,
                    description=item.description,
                    category=item.category,
                    quantity=item.quantity,
                    loss_type=item.loss_type,
                    ownership=item.ownership,
                    estimated_value=item.estimated_value,
                    source=item.source,
                    source_refs=item.source_refs,
                    status=item.status,
                    resolution_state=item.resolution_state,
                )
                for item in claim.contents_items
            ],
            known_field_codes=sorted(
                field_code
                for field_code, field in claim.form.items()
                if (branch is None or field_code in model_field_codes)
                and field.needed_for is NeededFor.CURRENT_ACTION
            ),
            evidence_summary=claim.evidence_summary,
            customer_next_step=claim.customer_next_step,
        ),
        message_text=context.message_text,
        evidence_reference_count=len(context.evidence_refs),
        professional_review_required=context.professional_review_required,
        branch=(
            ModelBranchContext(
                field_registry_version=branch.field_registry_version,
                branch_rules_version=branch.branch_rules_version,
                selected_family=branch.selected_family,
                unresolved_family_conflict=branch.unresolved_family_conflict,
                active_branches=branch.active_branches,
                candidate_branches=branch.candidate_branches,
                allowed_field_codes=sorted(
                    item.field_code
                    for item in branch.field_selection
                    if item.selection_state.value not in {'inactive', 'system_owned'}
                ),
                field_selection=[
                    ModelFieldSelectionContext(
                        field_code=item.field_code,
                        selection_state=item.selection_state,
                        value_state=item.value_state,
                    )
                    for item in branch.field_selection
                    if item.selection_state.value not in {'inactive', 'system_owned'}
                ],
                work_item_intents=branch.work_item_intents,
                interruption_result=branch.interruption_result,
                permitted_actions=branch.permitted_actions,
                permitted_tools=branch.permitted_tools,
                satisfied_requirements=branch.requirements.satisfied,
                missing_required_now=branch.requirements.missing_required_now,
                pending_later=branch.requirements.pending_later,
                next_required_item=branch.requirements.next_required_item,
                ready=branch.requirements.ready,
            )
            if branch is not None
            else None
        ),
        knowledge_status=context.knowledge_status,
        knowledge_citations=[
            ModelKnowledgeCitation(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                title=chunk.title,
                section_path=chunk.section_path,
                source_uri=chunk.source_uri,
                version=chunk.version,
                checksum=chunk.checksum,
                text=chunk.text,
            )
            for chunk in context.knowledge_results
        ],
        knowledge_limitations=list(context.knowledge_limitations),
        tool_results=list(context.tool_results),
        provenance_messages=[
            ModelProvenanceMessage(message_id=message.message_id, content=message.content)
            for message in context.provenance_messages
        ],
    )


def _agent_proposal(
    proposal: ModelAgentProposal,
    *,
    message_text: str | None,
    provider_model: str | None,
    provider_request_id: str | None,
    prompt_id: str,
    action_code: str | None = None,
    runtime_action_code: str | None = None,
) -> AgentProposal:
    normalized_message = ' '.join((message_text or '').split()).casefold()

    def claimant_supports(change: ModelProposedFormChange) -> bool:
        if not change.reported_text:
            return False
        quote = ' '.join(change.reported_text.split()).casefold()
        if not quote or quote not in normalized_message:
            return False
        value: Any = change.value
        if isinstance(value, str):
            normalised_value = ' '.join(value.split()).casefold()
            if normalised_value in quote:
                return True
            return (
                change.field_code == 'claim.product_family'
                and infer_controlled_product_family(change.reported_text) == normalised_value
            )
        if isinstance(value, list):
            return all(
                isinstance(item, str) and ' '.join(item.split()).casefold() in quote
                for item in value
            )
        if not isinstance(value, bool):
            return False
        negative = bool(
            re.search(r"\b(?:no|none|nobody|not|never|cannot|can't|isn't|wasn't|without)\b", quote)
        )
        markers = {
            'incident.injury_or_danger': r'\b(?:injur(?:y|ed)|hurt|danger|unsafe|emergency)\b',
            'parties.other_parties': r'\b(?:another|other|second|person|people|vehicle|party)\b',
            'vehicle.drivable': r'\b(?:driv(?:e|en|able)|roadworthy|safe|unsafe)\b',
            'property.ongoing_risk': r'\b(?:risk|leak|fire|flood|exposed|unsafe|danger)\b',
            'property.habitable': r'\b(?:habitable|live|lived|safe|unsafe|uninhabitable)\b',
        }
        marker = markers.get(change.field_code)
        return marker is not None and re.search(marker, quote) is not None and value is not negative

    def source_for(change: ModelProposedFormChange) -> FormSource:
        if claimant_supports(change):
            return FormSource.CLAIMANT
        return FormSource.INFERENCE

    def form_change(change: ModelProposedFormChange) -> ProposedFormChange:
        source = source_for(change)
        return ProposedFormChange(
            field_code=change.field_code,
            value=change.value,
            source=source,
            status=(FormStatus.CONFIRMED if source is FormSource.CLAIMANT else FormStatus.PROPOSED),
            needed_for=change.needed_for,
            confidence=change.confidence,
            precision=change.precision,
            relation=change.relation,
            reported_text=change.reported_text,
        )

    return AgentProposal(
        action=proposal.action,
        reason_codes=proposal.reason_codes,
        customer_reason=proposal.customer_reason,
        customer_response=proposal.customer_response,
        customer_next_step=proposal.customer_next_step,
        form_changes=[form_change(change) for change in proposal.form_changes],
        contents_item_changes=[
            ProposedContentsItem(
                item_id=item.item_id,
                description=item.description,
                category=item.category,
                quantity=item.quantity,
                loss_type=item.loss_type,
                ownership=item.ownership,
                estimated_value=item.estimated_value,
                confidence=item.confidence,
                relation=item.relation,
                reported_text=item.reported_text,
            )
            for item in proposal.contents_item_changes
        ],
        state_changes=proposal.state_changes,
        proposed_signals=[],
        required_tools=proposal.required_tools,
        next_action_requirements=proposal.next_action_requirements,
        handoff_priority=proposal.handoff_priority,
        controlled_rule_authorised=False,
        proposal_source=AgentProposalSource.MODEL_GATEWAY,
        model_provenance=ModelDecisionProvenance(
            provider_model=provider_model,
            provider_request_id=provider_request_id,
            prompt_id=prompt_id,
        ),
        action_code=action_code,
    )


class GatewayAgent:
    def __init__(
        self,
        gateway: ModelGateway,
        instruction_provider: Callable[[], str | None] | None = None,
        operations: ModelOperationsRecorder | None = None,
    ) -> None:
        self._gateway = gateway
        self._instruction_provider = instruction_provider
        self._operations = operations

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        instruction = (
            context.runtime_policy.instruction.system_prompt
            if context.runtime_policy is not None
            else (self._instruction_provider() if self._instruction_provider else None)
            or _SYSTEM_INSTRUCTION
        )
        instruction = (
            f'{instruction}\n\n'
            'Runtime contract: first call the read-only claim.read tool with an empty object. '
            'After its result, return JSON with action_code="conversation.answer", '
            'runtime_action_code="runtime.continue", reason_codes, customer_reason, '
            'customer_response, and customer_next_step. Do not emit ASK, CLARIFY, CONFIRM, '
            'PROCEED, UPDATE, HANDOFF, URGENT_HANDOFF, or CREATE_CLAIM.'
        )
        prompt_version = (
            context.runtime_policy.instruction.prompt_version
            if context.runtime_policy is not None
            else MOTOR_CLAIMANT_PROMPT_ID
        )
        messages = [
            ModelMessage(role=ModelRole.SYSTEM, content=instruction),
            ModelMessage(
                role=ModelRole.USER,
                content=json.dumps(
                    _model_turn_context(context).model_dump(mode='json'),
                    separators=(',', ':'),
                ),
            ),
        ]
        claim_read = tool_contract('claim.read')
        tool = ModelTool(
            name=claim_read.name,
            description=claim_read.description,
            input_schema=claim_read.input_schema,
        )
        request = ModelRequest(
            model_profile_id=context.model_profile_id,
            purpose=CLAIMANT_AGENT_PURPOSE,
            prompt_version=prompt_version,
            privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
            required_capabilities=ModelCapabilities(
                structured_output=True,
                tools=bool(self._gateway.capabilities.tools),
            ),
            messages=messages,
            # The staged tool request intentionally omits the final schema. The
            # compatibility path retains its historical schema only when the
            # gateway does not declare tools; configured claimant profiles must
            # declare tools and therefore use the target staged contract.
            response_schema=(
                None if self._gateway.capabilities.tools else _PROPOSAL_ADAPTER.json_schema()
            ),
            tools=[tool] if self._gateway.capabilities.tools else [],
        )
        started_at = perf_counter()
        response: ModelResponse | None = None
        invocations: list[RuntimeInvocationTrace] = []
        tool_call_id: str | None = None
        tool_arguments: dict[str, object] = {}
        try:
            complete_for_snapshot = getattr(self._gateway, 'complete_for_snapshot', None)
            if context.runtime_configuration_snapshot is not None and callable(
                complete_for_snapshot
            ):
                snapshot_completion = cast(
                    Callable[[ModelRequest, RuntimeConfigurationSnapshot], ModelResponse],
                    complete_for_snapshot,
                )
                response = snapshot_completion(request, context.runtime_configuration_snapshot)
            else:
                response = self._gateway.complete(request)
            invocations.append(
                _runtime_invocation_trace(
                    1,
                    response,
                    (perf_counter() - started_at) * 1000,
                )
            )

            # A model-capable Runtime turn starts with a real, read-only tool request.
            # The current Claim object was loaded by the authenticated message boundary;
            # the tool therefore reads authoritative state rather than a fixture payload.
            if self._gateway.capabilities.tools and not response.tool_calls:
                raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
            if response.tool_calls:
                if len(response.tool_calls) != 1:
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
                tool_call = response.tool_calls[0]
                if tool_call.name != claim_read.name:
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                tool_call_id = tool_call.call_id
                tool_arguments = dict(tool_call.arguments)
                try:
                    tool_result = read_claim_for_runtime(context.claim, tool_call.arguments)
                except (TypeError, ValueError) as error:
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from error
                continuation_messages = [
                    *messages,
                    ModelMessage(
                        role=ModelRole.ASSISTANT,
                        content=response.text,
                        tool_calls=response.tool_calls,
                    ),
                    ModelMessage(
                        role=ModelRole.TOOL,
                        name=claim_read.name,
                        tool_call_id=tool_call.call_id,
                        content=json.dumps(tool_result, separators=(',', ':')),
                    ),
                ]
                continuation = ModelRequest(
                    model_profile_id=context.model_profile_id,
                    purpose=CLAIMANT_AGENT_PURPOSE,
                    prompt_version=prompt_version,
                    privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
                    required_capabilities=ModelCapabilities(
                        structured_output=True,
                        tools=True,
                    ),
                    messages=continuation_messages,
                    response_schema=_RUNTIME_PROPOSAL_ADAPTER.json_schema(),
                )
                if context.runtime_configuration_snapshot is not None and callable(
                    complete_for_snapshot
                ):
                    response = snapshot_completion(
                        continuation,
                        context.runtime_configuration_snapshot,
                    )
                else:
                    response = self._gateway.complete(continuation)
                invocations.append(
                    _runtime_invocation_trace(
                        2,
                        response,
                        (perf_counter() - started_at) * 1000,
                    )
                )
            if response.completion_status is ModelCompletionStatus.INCOMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.INCOMPLETE_RESPONSE)
            if response.completion_status is ModelCompletionStatus.REFUSED:
                raise ModelGatewayError(ModelGatewayErrorCode.REFUSED_RESPONSE)
            if response.completion_status is not ModelCompletionStatus.COMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            if response.structured_output is None:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            if self._gateway.capabilities.tools:
                try:
                    runtime_proposal = _RUNTIME_PROPOSAL_ADAPTER.validate_python(
                        response.structured_output
                    )
                except ValidationError:
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
                if runtime_proposal.action_code != 'conversation.answer':
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY) from None
                if runtime_proposal.runtime_action_code != 'runtime.continue':
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                result = AgentProposal(
                    action=AgentAction.UPDATE,
                    action_code=runtime_proposal.action_code,
                    reason_codes=runtime_proposal.reason_codes,
                    customer_reason=runtime_proposal.customer_reason,
                    customer_response=runtime_proposal.customer_response,
                    customer_next_step=runtime_proposal.customer_next_step,
                    form_changes=[],
                    state_changes=[],
                    proposed_signals=[],
                    required_tools=[],
                    next_action_requirements=[],
                    proposal_source=AgentProposalSource.MODEL_GATEWAY,
                    model_provenance=ModelDecisionProvenance(
                        provider_model=response.provider_model,
                        provider_request_id=response.provider_request_id,
                        prompt_id=prompt_version,
                    ),
                    runtime_trace=RuntimeTraceRecord(
                        trace_id=new_id('trc'),
                        claim_id=context.claim.claim_id,
                        session_id=context.session_id,
                        model_profile_id=context.model_profile_id,
                        trigger_message_id=context.trigger_message_id,
                        invocations=invocations,
                        tool_call_id=tool_call_id or 'unknown',
                        tool_name=claim_read.name,
                        tool_arguments=tool_arguments,
                        tool_result_status='succeeded',
                        action_code=runtime_proposal.action_code,
                        runtime_action_code=runtime_proposal.runtime_action_code,
                        reason_codes=runtime_proposal.reason_codes,
                        status='succeeded',
                        created_at=datetime.now(UTC),
                        finished_at=datetime.now(UTC),
                    ),
                )
            else:
                try:
                    proposal = _PROPOSAL_ADAPTER.validate_python(response.structured_output)
                except ValidationError:
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
                result = _agent_proposal(
                    proposal,
                    message_text=context.message_text,
                    provider_model=response.provider_model,
                    provider_request_id=response.provider_request_id,
                    prompt_id=prompt_version,
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


def _runtime_invocation_trace(
    ordinal: int,
    response: ModelResponse,
    latency_ms: float,
) -> RuntimeInvocationTrace:
    usage = response.usage
    return RuntimeInvocationTrace(
        ordinal=ordinal,
        provider_model=response.provider_model,
        provider_request_id=response.provider_request_id,
        finish_reason=response.finish_reason,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        total_tokens=usage.total_tokens if usage is not None else None,
        latency_ms=latency_ms,
    )


class KnowledgeGroundedAgent:
    """Execute one model-requested, application-scoped knowledge lookup."""

    def __init__(
        self,
        provider: AgentTurnProvider,
        retriever: KnowledgeRetriever,
        knowledge_catalog: KnowledgeAdminRepository | None = None,
        runtime_configuration_resolver: RuntimeConfigurationResolver | None = None,
    ) -> None:
        self._provider = provider
        self._retriever = retriever
        self._knowledge_catalog = knowledge_catalog
        self._runtime_configuration_resolver = runtime_configuration_resolver

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        proposal = self._provider.propose_turn(context)
        context_requests = [
            item for item in proposal.required_tools if item.get('tool') in _CONTEXT_TOOL_NAMES
        ]
        if context.tool_results and context_requests:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if len(context_requests) > 1:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        request = next(
            (
                item
                for item in proposal.required_tools
                if item.get('tool') == 'knowledge_search' and item.get('operation') == 'search'
            ),
            None,
        )
        if request is None:
            return proposal
        if context.runtime_policy is not None and (
            'knowledge_search' not in context.runtime_policy.tool_policy.allowed_tool_names
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if context.tool_results or context.knowledge_status != 'not_requested':
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        if (
            context.runtime_policy is not None
            and not context.runtime_policy.features.knowledge_retrieval
        ):
            tool_result: dict[str, object] = {
                'tool': 'knowledge_search',
                'status': 'unavailable',
                'source_refs': [],
                'limitations': ['Knowledge retrieval is disabled by published configuration.'],
            }
            final = self._provider.propose_turn(
                replace(
                    context,
                    knowledge_status='unavailable',
                    knowledge_limitations=(
                        'Knowledge retrieval is disabled by published configuration.',
                    ),
                    tool_results=(tool_result,),
                )
            )
            return replace(final, tool_results=[tool_result])
        product = _knowledge_product(context.claim.incident_type)
        if product is None:
            tool_result = {
                'tool': 'knowledge_search',
                'status': 'no_evidence',
                'source_refs': [],
                'limitations': ['A confirmed product family is required for scoped search.'],
            }
            final = self._provider.propose_turn(
                replace(context, knowledge_status='no_evidence', tool_results=(tool_result,))
            )
            return replace(final, tool_results=[tool_result])
        resolution_error = False
        if (
            context.runtime_configuration_snapshot is not None
            and context.runtime_configuration_snapshot.release_set_id is not None
        ):
            try:
                published = context.runtime_configuration_snapshot.knowledge_for_product(product)
            except RuntimeConfigurationResolutionError:
                published = None
                resolution_error = True
        elif self._runtime_configuration_resolver is not None:
            try:
                published = self._runtime_configuration_resolver.resolve_knowledge(product)
            except RuntimeConfigurationResolutionError:
                published = None
                resolution_error = True
        else:
            published = (
                self._knowledge_catalog.published_for_product(product)
                if self._knowledge_catalog is not None
                else None
            )
        knowledge_version = published.version if published is not None else 'MVP-2026.1'
        status = 'unavailable' if resolution_error else 'evidence_found'
        limitations: tuple[str, ...] = (
            ('The active runtime release does not select an approved knowledge version.',)
            if resolution_error
            else ()
        )
        if resolution_error:
            tool_result = {
                'tool': 'knowledge_search',
                'status': status,
                'source_refs': [],
                'limitations': list(limitations),
            }
            final = self._provider.propose_turn(
                replace(
                    context,
                    knowledge_results=(),
                    knowledge_status=status,
                    knowledge_limitations=limitations,
                    tool_results=(tool_result,),
                )
            )
            return replace(final, tool_results=[tool_result])
        query = request.get('query')
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        try:
            chunks = tuple(
                self._retriever.search(
                    KnowledgeSearch(
                        text=query.strip(),
                        jurisdiction='NZ',
                        visibility='customer_and_staff',
                        authority='northwind_synthetic_demo',
                        version=knowledge_version,
                        insurer='Northwind Insurance',
                        product=product,
                        effective_at=datetime.now(UTC),
                        limit=3,
                    )
                )
            )
        except KnowledgeRetrievalUnavailable:
            chunks = ()
            status = 'unavailable'
            limitations = ('Approved knowledge retrieval is temporarily unavailable.',)
        else:
            if not chunks:
                status = 'no_evidence'
                limitations = (
                    'No applicable approved knowledge was found for the supplied scope and date.',
                )
        tool_result = {
            'tool': 'knowledge_search',
            'status': status,
            'source_refs': [chunk.chunk_id for chunk in chunks],
            'limitations': list(limitations),
        }
        final = self._provider.propose_turn(
            replace(
                context,
                knowledge_results=chunks,
                knowledge_status=status,
                knowledge_limitations=limitations,
                tool_results=(tool_result,),
            )
        )
        if any(item.get('tool') in _CONTEXT_TOOL_NAMES for item in final.required_tools):
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        return replace(final, tool_results=[tool_result])
