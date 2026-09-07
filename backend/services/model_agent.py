import json
from dataclasses import replace
from datetime import UTC, datetime

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
    ModelRequest,
    ModelRole,
    ModelTurnContext,
)
from backend.domain.models import (
    AgentProposalSource,
    FormSource,
    FormStatus,
    ModelDecisionProvenance,
    NeededFor,
    ProposedFormChange,
)
from backend.prompts import MOTOR_CLAIMANT_PROMPT_ID, load_motor_claimant_prompt
from backend.services.agent import AgentProposal, AgentTurnContext, AgentTurnProvider

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
            prompt_id=MOTOR_CLAIMANT_PROMPT_ID,
        ),
    )


class GatewayAgent:
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        request = ModelRequest(
            purpose=CLAIMANT_AGENT_PURPOSE,
            prompt_version=MOTOR_CLAIMANT_PROMPT_ID,
            privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
            required_capabilities=ModelCapabilities(structured_output=True),
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content=_SYSTEM_INSTRUCTION),
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
        return _agent_proposal(
            proposal,
            provider_model=response.provider_model,
            provider_request_id=response.provider_request_id,
        )


class KnowledgeGroundedAgent:
    """Retrieve scoped approved knowledge before delegating a model turn."""

    def __init__(self, provider: AgentTurnProvider, retriever: KnowledgeRetriever) -> None:
        self._provider = provider
        self._retriever = retriever

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        if not context.message_text or not context.message_text.strip():
            return self._provider.propose_turn(context)
        product = _knowledge_product(context.claim.incident_type)
        if product is None:
            return self._provider.propose_turn(context)
        status = 'evidence_found'
        limitations: tuple[str, ...] = ()
        try:
            chunks = tuple(
                self._retriever.search(
                    KnowledgeSearch(
                        text=context.message_text,
                        jurisdiction='NZ',
                        visibility='customer_and_staff',
                        authority='northwind_synthetic_demo',
                        version='MVP-2026.1',
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
