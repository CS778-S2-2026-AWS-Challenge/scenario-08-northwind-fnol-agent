import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from typing import cast

from pydantic import TypeAdapter, ValidationError

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
    ModelFieldSelectionContext,
    ModelFormFieldContext,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelKnowledgeCitation,
    ModelMessage,
    ModelProvenanceMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTurnContext,
)
from backend.domain.models import (
    AgentProposalSource,
    FactResolutionState,
    FormSource,
    FormStatus,
    ModelDecisionProvenance,
    NeededFor,
    ProposedFormChange,
)
from backend.prompts import MOTOR_CLAIMANT_PROMPT_ID, load_motor_claimant_prompt
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.services.agent import AgentProposal, AgentTurnContext, AgentTurnProvider
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
    RuntimeConfigurationSnapshot,
)

_PROPOSAL_ADAPTER = TypeAdapter(ModelAgentProposal)
_SYSTEM_INSTRUCTION = load_motor_claimant_prompt()

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
                    resolution_state=(
                        field.resolution_state.value if field.resolution_state is not None else None
                    ),
                    precision=field.precision,
                    source_refs=(
                        field.source_refs
                        if field.resolution_state is FactResolutionState.CLARIFICATION_REQUIRED
                        else []
                    ),
                )
                for field_code, field in claim.form.items()
                if field_code in _MODEL_CONTEXT_FIELD_CODES
                and field.needed_for is NeededFor.CURRENT_ACTION
            },
            known_field_codes=sorted(
                field_code
                for field_code, field in claim.form.items()
                if field.needed_for is NeededFor.CURRENT_ACTION
            ),
            evidence_summary=claim.evidence_summary,
            customer_next_step=claim.customer_next_step,
        ),
        message_text=context.message_text,
        evidence_reference_count=len(context.evidence_refs),
        professional_review_required=context.professional_review_required,
        provenance_messages=[
            ModelProvenanceMessage(
                message_id=message.message_id,
                content=str(message.content.get('text', '')),
            )
            for message in context.provenance_messages
            if isinstance(message.content.get('text'), str)
        ],
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
    )


def _agent_proposal(
    proposal: ModelAgentProposal,
    *,
    provider_model: str | None,
    provider_request_id: str | None,
    prompt_id: str,
) -> AgentProposal:
    return AgentProposal(
        action=proposal.action,
        reason_codes=proposal.reason_codes,
        customer_reason=proposal.customer_reason,
        customer_response=proposal.customer_response,
        customer_next_step=proposal.customer_next_step,
        form_changes=[
            ProposedFormChange(
                field_code=change.field_code,
                value=change.value,
                source=FormSource.INFERENCE,
                status=FormStatus.PROPOSED,
                needed_for=change.needed_for,
                confidence=change.confidence,
            )
            for change in proposal.form_changes
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
        prompt_version = (
            context.runtime_policy.instruction.prompt_version
            if context.runtime_policy is not None
            else MOTOR_CLAIMANT_PROMPT_ID
        )
        request = ModelRequest(
            purpose=CLAIMANT_AGENT_PURPOSE,
            prompt_version=prompt_version,
            privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
            required_capabilities=ModelCapabilities(structured_output=True),
            messages=[
                ModelMessage(
                    role=ModelRole.SYSTEM,
                    content=instruction,
                ),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        _model_turn_context(context).model_dump(mode='json'),
                        separators=(',', ':'),
                    ),
                ),
            ],
            response_schema=_PROPOSAL_ADAPTER.json_schema(),
        )
        started_at = perf_counter()
        response: ModelResponse | None = None
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
            if response.completion_status is ModelCompletionStatus.INCOMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.INCOMPLETE_RESPONSE)
            if response.completion_status is ModelCompletionStatus.REFUSED:
                raise ModelGatewayError(ModelGatewayErrorCode.REFUSED_RESPONSE)
            if response.completion_status is not ModelCompletionStatus.COMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            if response.structured_output is None:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            try:
                proposal = _PROPOSAL_ADAPTER.validate_python(response.structured_output)
            except ValidationError:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
            if response.tool_calls or proposal.required_tools:
                raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
            result = _agent_proposal(
                proposal,
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


class KnowledgeGroundedAgent:
    """Retrieve scoped approved knowledge before delegating a model turn."""

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
        if not context.message_text or not context.message_text.strip():
            return self._provider.propose_turn(context)
        if (
            context.runtime_policy is not None
            and not context.runtime_policy.features.knowledge_retrieval
        ):
            return self._provider.propose_turn(
                replace(
                    context,
                    knowledge_results=(),
                    knowledge_status='disabled',
                    knowledge_limitations=(
                        'Knowledge retrieval is disabled by the active published feature setting.',
                    ),
                )
            )
        product = _knowledge_product(context.claim.incident_type)
        if product is None:
            return self._provider.propose_turn(context)
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
            return self._provider.propose_turn(
                replace(
                    context,
                    knowledge_results=(),
                    knowledge_status=status,
                    knowledge_limitations=limitations,
                )
            )
        try:
            chunks = tuple(
                self._retriever.search(
                    KnowledgeSearch(
                        text=context.message_text,
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
        return self._provider.propose_turn(
            replace(
                context,
                knowledge_results=chunks,
                knowledge_status=status,
                knowledge_limitations=limitations,
            )
        )
