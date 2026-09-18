import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from backend.domain.agent_action_registry import action_contract
from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    ModelRequestBudget,
    PlannedModelTurn,
    TurnTask,
)
from backend.domain.agent_tool_registry import tool_contract
from backend.domain.agent_v7 import (
    V7AnswerProposal,
    V7ClaimCreationProposal,
    V7EvidenceActionProposal,
    V7ExternalOfferProposal,
    V7IntakeProposal,
    V7SourcedSummaryProposal,
)
from backend.domain.branch_registry import build_default_registry
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
    ModelAttachedEvidenceContext,
    ModelBranchContext,
    ModelCapabilities,
    ModelClaimContext,
    ModelClaimStateContext,
    ModelCompletionStatus,
    ModelContentsItemContext,
    ModelEvidenceContent,
    ModelFieldSelectionContext,
    ModelFormFieldContext,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelKnowledgeCitation,
    ModelMessage,
    ModelProposedContentsItem,
    ModelProposedFormChange,
    ModelProvenanceMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRuntimeProposal,
    ModelTextContent,
    ModelTool,
    ModelTurnContext,
)
from backend.domain.models import (
    AgentAction,
    AgentProposalSource,
    CustomerNextStep,
    FormSource,
    FormStatus,
    ModelDecisionProvenance,
    NeededFor,
    ProposedContentsItem,
    ProposedFormChange,
    ResponsibleParty,
    RuntimeInvocationTrace,
    RuntimeTraceRecord,
)
from backend.domain.realtime import AgentTurnProgressStage
from backend.domain.turn_field_contract import RepairOutcome, TurnFieldContractViolation
from backend.prompts import (
    CLAIMANT_V7_PROMPT_ID,
    MOTOR_CLAIMANT_PROMPT_ID,
    load_motor_claimant_prompt,
)
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.services.agent import (
    AgentEvidenceReference,
    AgentProposal,
    AgentTurnContext,
    AgentTurnProvider,
)
from backend.services.agent_tools import read_claim_for_runtime
from backend.services.context_budget import build_request_budget
from backend.services.context_planner import ContextBudgetExceeded
from backend.services.context_resolver import resolver_for_turn
from backend.services.isolated_context_executor import execute_isolated_context_plan
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.model_request_planner import context_resolve_tool, plan_model_turn
from backend.services.prompt_composer import load_response_schema
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)
from backend.services.turn_field_contract import bind_provider_schema, validate_field_changes
from backend.services.turn_router import route_turn

logger = logging.getLogger(__name__)

_UNSUPPORTED_EXECUTIONAL_CLAIM = re.compile(
    r'\b(?:I|we|Northwind)\s+(?:have\s+)?(?:arranged|booked|submitted|sent|contacted|'
    r'approved|completed|scheduled)\b',
    re.IGNORECASE,
)


def _truthful_external_reply(reply: str, service_offer_ids: list[str]) -> str:
    """Prevent prose from claiming an external side effect without Runtime evidence."""

    if not _UNSUPPORTED_EXECUTIONAL_CLAIM.search(reply):
        return reply
    if service_offer_ids:
        return (
            'I found a registered support option. Review what would be shared and give your '
            'consent before Northwind sends anything.'
        )
    return (
        'I could not prepare a registered support option yet. You can continue the Claim while '
        'I clarify what support is available.'
    )


_PROPOSAL_ADAPTER = TypeAdapter(ModelAgentProposal)
_RUNTIME_PROPOSAL_ADAPTER = TypeAdapter(ModelRuntimeProposal)


def _merge_field_contract_repair(
    original: dict[str, object],
    repaired: dict[str, object],
    invalid_field_codes: set[str],
) -> dict[str, object]:
    repaired_changes = repaired.get('field_changes')
    original_changes = original.get('field_changes')
    if not isinstance(repaired_changes, list) or not isinstance(original_changes, list):
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
    replacements: dict[str, dict[str, object]] = {}
    for item in repaired_changes:
        if not isinstance(item, dict):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        field_code = item.get('field_code')
        if not isinstance(field_code, str) or field_code not in invalid_field_codes:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        if field_code in replacements:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        replacements[field_code] = item
    if set(replacements) != invalid_field_codes:
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)

    merged_changes: list[object] = []
    for item in original_changes:
        if not isinstance(item, dict):
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        field_code = item.get('field_code')
        merged_changes.append(replacements.get(str(field_code), item))
    return {**original, 'field_changes': merged_changes}


_V7_ANSWER_ADAPTER = TypeAdapter(V7AnswerProposal)
_V7_INTAKE_ADAPTER = TypeAdapter(V7IntakeProposal)
_V7_EXTERNAL_ADAPTER = TypeAdapter(V7ExternalOfferProposal)
_V7_EVIDENCE_ADAPTER = TypeAdapter(V7EvidenceActionProposal)
_V7_CREATION_ADAPTER = TypeAdapter(V7ClaimCreationProposal)
_V7_SOURCED_SUMMARY_ADAPTER = TypeAdapter(V7SourcedSummaryProposal)
_SYSTEM_INSTRUCTION = load_motor_claimant_prompt()
_CONTEXT_TOOL_NAMES = frozenset(
    {'knowledge_search', 'policy_history', 'claim_history', 'evidence.history'}
)

_FIELD_DEFINITIONS = build_default_registry().field_by_code


@dataclass(frozen=True, slots=True)
class _ObservedModelInvocation:
    request: ModelRequest
    response: ModelResponse | None
    latency_ms: float
    request_stage: str


def _model_context_size_metrics(
    context: AgentTurnContext,
    context_json: str,
) -> dict[str, int]:
    return {
        'claim_context_chars': len(context_json),
        'conversation_history_chars': sum(
            len(message.content) for message in context.conversation_messages
        ),
        'knowledge_citation_chars': sum(len(item.text) for item in context.knowledge_results),
        'tool_result_chars': len(
            json.dumps(list(context.tool_results), separators=(',', ':'), sort_keys=True)
        ),
        'external_service_chars': len(
            json.dumps(
                [item.model_dump(mode='json') for item in context.external_services],
                separators=(',', ':'),
                sort_keys=True,
            )
        ),
    }


def _normalise_model_field_value(field_code: str, value: Any) -> Any:
    """Normalise provider scalar spellings without changing the registered contract."""

    definition = _FIELD_DEFINITIONS.get(field_code)
    value_type = definition.value_type if definition is not None else None
    if value_type == 'boolean' and isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {'true', 'yes', 'y', '1'}:
            return True
        if normalized in {'false', 'no', 'n', '0'}:
            return False
        negative = re.search(
            r"\b(?:no|none|nobody|not|never|without|isn't|wasn't|cannot|can't)\b",
            normalized,
        )
        if field_code == 'incident.injury_or_danger' and re.search(
            r'\b(?:injur(?:y|ies|ed)|hurt|danger|unsafe|emergency)\b', normalized
        ):
            return not bool(negative)
        if field_code == 'vehicle.drivable' and re.search(
            r'\b(?:driv(?:e|en|able)|roadworthy|safe|unsafe)\b', normalized
        ):
            return not bool(negative or re.search(r'\bunsafe\b', normalized))
        if field_code == 'parties.other_parties' and re.search(
            r'\b(?:another|other|second|person|people|vehicle|party)\b', normalized
        ):
            return not bool(negative)
        if field_code == 'property.habitable' and re.search(
            r'\b(?:habitable|live|safe|unsafe|uninhabitable)\b', normalized
        ):
            return not bool(negative or re.search(r'\b(?:unsafe|uninhabitable)\b', normalized))
    if value_type == 'enum' and isinstance(value, str):
        return value.strip().casefold()
    if value_type == 'text_list' and isinstance(value, str):
        return [
            item.strip()
            for item in re.split(r'\s*(?:,|;|\band\b)\s*', value, flags=re.IGNORECASE)
            if item.strip()
        ]
    return value


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
                    brand=item.brand,
                    model=item.model,
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
        attached_evidence=[
            ModelAttachedEvidenceContext(
                evidence_id=item.evidence_id,
                media_type=item.media_type,
            )
            for item in context.evidence
        ],
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
        external_services=list(context.external_services),
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
        conversation_history=[
            ModelProvenanceMessage(
                message_id=message.message_id,
                content=json.dumps(
                    {'actor': message.actor.value, 'content': message.content},
                    separators=(',', ':'),
                ),
            )
            for message in context.conversation_messages
        ],
        field_value_contracts={
            code: {
                'value_type': definition.value_type,
                'allowed_values': sorted(definition.allowed_values),
            }
            for code in sorted(model_field_codes)
            if (definition := _FIELD_DEFINITIONS.get(code)) is not None
        },
    )


def _claimant_supports_model_change(
    change: ModelProposedFormChange,
    normalized_message: str,
) -> bool:
    if not change.reported_text:
        return False
    quote = ' '.join(change.reported_text.split()).casefold()
    if not quote or quote not in normalized_message:
        return False
    value: Any = _normalise_model_field_value(change.field_code, change.value)
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
            isinstance(item, str) and ' '.join(item.split()).casefold() in quote for item in value
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


def _model_form_change(
    change: ModelProposedFormChange,
    *,
    message_text: str | None,
    evidence: tuple[AgentEvidenceReference, ...],
) -> ProposedFormChange:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    source = FormSource.INFERENCE
    if change.source_evidence_id is not None:
        attached = evidence_by_id.get(change.source_evidence_id)
        if attached is None:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        source = (
            FormSource.IMAGE if attached.media_type.startswith('image/') else FormSource.DOCUMENT
        )
    elif _claimant_supports_model_change(
        change,
        ' '.join((message_text or '').split()).casefold(),
    ):
        source = FormSource.CLAIMANT
    return ProposedFormChange(
        field_code=change.field_code,
        value=_normalise_model_field_value(change.field_code, change.value),
        source=source,
        status=(FormStatus.CONFIRMED if source is FormSource.CLAIMANT else FormStatus.PROPOSED),
        needed_for=change.needed_for,
        confidence=change.confidence,
        precision=change.precision,
        relation=change.relation,
        reported_text=change.reported_text,
        source_evidence_id=change.source_evidence_id,
    )


def _model_contents_item_change(
    item: ModelProposedContentsItem,
    *,
    evidence: tuple[AgentEvidenceReference, ...],
) -> ProposedContentsItem:
    if item.source_evidence_id is not None and item.source_evidence_id not in {
        record.evidence_id for record in evidence
    }:
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
    return ProposedContentsItem(
        item_id=item.item_id,
        description=item.description,
        category=item.category,
        quantity=item.quantity,
        brand=item.brand,
        model=item.model,
        loss_type=item.loss_type,
        ownership=item.ownership,
        estimated_value=item.estimated_value,
        confidence=item.confidence,
        relation=item.relation,
        reported_text=item.reported_text,
        source_evidence_id=item.source_evidence_id,
    )


def _agent_proposal(
    proposal: ModelAgentProposal,
    *,
    message_text: str | None,
    evidence: tuple[AgentEvidenceReference, ...],
    provider_model: str | None,
    provider_request_id: str | None,
    prompt_id: str,
    action_code: str | None = None,
    runtime_action_code: str | None = None,
) -> AgentProposal:
    return AgentProposal(
        action=proposal.action,
        reason_codes=proposal.reason_codes,
        customer_reason=proposal.customer_reason,
        customer_response=proposal.customer_response,
        customer_next_step=proposal.customer_next_step,
        form_changes=[
            _model_form_change(change, message_text=message_text, evidence=evidence)
            for change in proposal.form_changes
        ],
        contents_item_changes=[
            _model_contents_item_change(item, evidence=evidence)
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
        external_service_intents=[],
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

    def _complete(self, request: ModelRequest, context: AgentTurnContext) -> ModelResponse:
        snapshot = context.runtime_configuration_snapshot
        if context.evidence:
            resolver = context.evidence_resolver
            if resolver is None:
                raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
            if snapshot is not None:
                completion = getattr(
                    self._gateway,
                    'complete_for_snapshot_with_evidence',
                    None,
                )
                if not callable(completion):
                    raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
                return cast(ModelResponse, cast(Any, completion)(request, snapshot, resolver))
            completion = getattr(self._gateway, 'complete_with_evidence', None)
            if not callable(completion):
                raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
            return cast(ModelResponse, cast(Any, completion)(request, resolver))
        complete_for_snapshot = getattr(self._gateway, 'complete_for_snapshot', None)
        if snapshot is not None and callable(complete_for_snapshot):
            return cast(ModelResponse, cast(Any, complete_for_snapshot)(request, snapshot))
        return self._gateway.complete(request)

    def _open_exchange(
        self,
        request: ModelRequest,
        context: AgentTurnContext,
    ) -> Callable[[ModelRequest], ModelResponse]:
        """Fix one concrete provider adapter for all invocations in this turn."""

        snapshot = context.runtime_configuration_snapshot
        if context.evidence:
            resolver = context.evidence_resolver
            if resolver is None:
                raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
            if snapshot is not None:
                opener = getattr(
                    self._gateway,
                    'open_exchange_for_snapshot_with_evidence',
                    None,
                )
                if callable(opener):
                    exchange = cast(Any, opener)(request, snapshot, resolver)
                    return cast(Callable[[ModelRequest], ModelResponse], exchange.complete)
            else:
                opener = getattr(self._gateway, 'open_exchange_with_evidence', None)
                if callable(opener):
                    exchange = cast(Any, opener)(request, resolver)
                    return cast(Callable[[ModelRequest], ModelResponse], exchange.complete)
        elif snapshot is not None:
            opener = getattr(self._gateway, 'open_exchange_for_snapshot', None)
            if callable(opener):
                exchange = cast(Any, opener)(request, snapshot)
                return cast(Callable[[ModelRequest], ModelResponse], exchange.complete)
        else:
            opener = getattr(self._gateway, 'open_exchange', None)
            if callable(opener):
                exchange = cast(Any, opener)(request)
                return cast(Callable[[ModelRequest], ModelResponse], exchange.complete)
        return lambda next_request: self._complete(next_request, context)

    def _observed_complete(
        self,
        request: ModelRequest,
        context: AgentTurnContext,
        request_stage: str,
        observations: list[_ObservedModelInvocation],
        completion: Callable[[ModelRequest], ModelResponse] | None = None,
    ) -> ModelResponse:
        if context.progress_reporter is not None:
            context.progress_reporter(AgentTurnProgressStage.MODEL_WAITING, 'model.response')
        started_at = perf_counter()
        try:
            response = (
                completion(request) if completion is not None else self._complete(request, context)
            )
        except ModelGatewayError:
            observations.append(
                _ObservedModelInvocation(
                    request=request,
                    response=None,
                    latency_ms=(perf_counter() - started_at) * 1000,
                    request_stage=request_stage,
                )
            )
            raise
        observations.append(
            _ObservedModelInvocation(
                request=request,
                response=response,
                latency_ms=(perf_counter() - started_at) * 1000,
                request_stage=request_stage,
            )
        )
        return response

    def _record_observations(
        self,
        observations: list[_ObservedModelInvocation],
        context_sizes: dict[str, int],
        failure: ModelGatewayError | None = None,
    ) -> None:
        if self._operations is None:
            return
        invocation_count = len(observations)
        for index, observation in enumerate(observations):
            if failure is not None and index == invocation_count - 1:
                self._operations.failed(
                    observation.request,
                    failure,
                    observation.latency_ms,
                    observation.response,
                    request_stage=observation.request_stage,
                    invocation_ordinal=index + 1,
                    invocation_count=invocation_count,
                    context_sizes=context_sizes,
                )
                continue
            if observation.response is None:
                continue
            self._operations.succeeded(
                observation.request,
                observation.response,
                observation.latency_ms,
                request_stage=observation.request_stage,
                invocation_ordinal=index + 1,
                invocation_count=invocation_count,
                context_sizes=context_sizes,
            )

    @staticmethod
    def _shadow_v7_plan(context: AgentTurnContext) -> dict[str, object]:
        """Plan v7 without exposing content or changing the active v6 turn."""

        if context.runtime_configuration_snapshot is None:
            return {'status': 'not_available'}
        try:
            plan = plan_model_turn(context)
        except Exception as error:
            return {'status': 'failed', 'error_type': type(error).__name__}
        if plan is None:
            route = route_turn(context)
            return {
                'status': 'planned_model_free',
                'route': f'{route.product_family or "unresolved"}:{route.task.value}',
            }
        return {
            'status': 'planned',
            'route': f'{plan.route.product_family}:{plan.route.task.value}',
            'request_profile_id': plan.request_profile.profile_id,
            'prompt_bundle_id': plan.prompt_bundle_id,
            'schema_id': plan.schema_id,
            'raw_input_tokens': plan.request_budget.raw_input_tokens,
            'context_sections': sorted(plan.context_plan.inline_context),
            'omitted_sections': sorted(plan.context_plan.omitted_sections),
        }

    def _v7_request(
        self,
        plan: PlannedModelTurn,
        context: AgentTurnContext,
        messages: list[ModelMessage],
        *,
        include_tools: bool,
    ) -> ModelRequest:
        tools = [context_resolve_tool()] if include_tools else []
        return ModelRequest(
            model_profile_id=context.model_profile_id,
            purpose=CLAIMANT_AGENT_PURPOSE,
            prompt_version=CLAIMANT_V7_PROMPT_ID,
            privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
            required_capabilities=ModelCapabilities(
                structured_output=True,
                tools=bool(tools),
                image_input=any(item.media_type.startswith('image/') for item in context.evidence),
                document_input=any(
                    item.media_type == 'application/pdf' for item in context.evidence
                ),
            ),
            messages=messages,
            response_schema=plan.response_schema,
            tools=tools,
            max_output_tokens=plan.request_profile.output_limit,
        )

    def _v7_proposal(
        self,
        plan: PlannedModelTurn,
        context: AgentTurnContext,
        response: ModelResponse,
        invocations: list[RuntimeInvocationTrace],
        *,
        tool_call_id: str | None,
        tool_arguments: dict[str, object],
        tool_output: dict[str, object],
        started_at: datetime,
        request_budgets: list[ModelRequestBudget],
        repair_attempted: bool = False,
        repair_outcome: RepairOutcome | None = None,
        field_contract_violations: list[dict[str, str]] | None = None,
    ) -> AgentProposal:
        if response.structured_output is None:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
        raw_output = dict(response.structured_output)
        legacy_service_offer_ids = raw_output.pop('service_offer_ids', [])
        model_service_offer_ids = (
            [item for item in legacy_service_offer_ids if isinstance(item, str)]
            if isinstance(legacy_service_offer_ids, list)
            else []
        )
        try:
            if plan.schema_id == 'claimant.intake-patch.v1':
                parsed: object = _V7_INTAKE_ADAPTER.validate_python(raw_output)
            elif plan.schema_id == 'claimant.external-offer.v1':
                parsed = _V7_EXTERNAL_ADAPTER.validate_python(raw_output)
            elif plan.schema_id == 'claimant.evidence-action.v1':
                parsed = _V7_EVIDENCE_ADAPTER.validate_python(raw_output)
            elif plan.schema_id == 'claimant.claim-creation.v1':
                parsed = _V7_CREATION_ADAPTER.validate_python(raw_output)
            elif plan.schema_id == 'claimant.sourced-summary.v1':
                parsed = _V7_SOURCED_SUMMARY_ADAPTER.validate_python(raw_output)
            else:
                parsed = _V7_ANSWER_ADAPTER.validate_python(raw_output)
        except ValidationError:
            raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None

        answer = (
            V7AnswerProposal(
                reply=parsed.summary,
                next_step='Continue the Claim with the sourced review when ready.',
                reason_codes=['ISOLATED_CONTEXT_REVIEWED'],
            )
            if isinstance(parsed, V7SourcedSummaryProposal)
            else cast(V7AnswerProposal, parsed)
        )
        form_changes: list[ProposedFormChange] = []
        contents_changes: list[ProposedContentsItem] = []
        service_offer_ids: list[str] = []
        evidence_id: str | None = None
        source_claim_id: str | None = None
        removal_scope: str | None = None
        if isinstance(parsed, V7IntakeProposal):
            if plan.field_contract is None:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            parsed = parsed.model_copy(
                update={
                    'field_changes': validate_field_changes(
                        plan.field_contract,
                        parsed.field_changes,
                    )
                }
            )
            form_changes = [
                _model_form_change(
                    item, message_text=context.message_text, evidence=context.evidence
                )
                for item in parsed.field_changes
            ]
            contents_changes = [
                _model_contents_item_change(item, evidence=context.evidence)
                for item in parsed.contents_item_changes
            ]
        elif isinstance(parsed, V7EvidenceActionProposal):
            evidence_id = parsed.evidence_id
            source_claim_id = parsed.source_claim_id
            removal_scope = parsed.removal_scope

        available_services = {item.service_identity for item in context.external_services}
        service_offer_ids = [
            service_id
            for service_id in context.selected_external_service_ids
            if service_id in available_services
        ]
        rejected_optional_ids = sorted(set(model_service_offer_ids) - set(service_offer_ids))
        if rejected_optional_ids:
            logger.info(
                'agent_optional_capability_rejected',
                extra={
                    'claim_id': context.claim.claim_id,
                    'session_id': context.session_id,
                    'component': 'capability_selector',
                    'internal_error_code': 'OPTIONAL_CAPABILITY_REJECTED',
                    'selected_services': service_offer_ids,
                    'rejected_count': len(rejected_optional_ids),
                },
            )
        answer = answer.model_copy(
            update={'reply': _truthful_external_reply(answer.reply, service_offer_ids)}
        )
        if service_offer_ids and context.progress_reporter is not None:
            context.progress_reporter(
                AgentTurnProgressStage.OFFER_PREPARING,
                'external.support_options',
            )

        action_code = 'conversation.answer'
        runtime_action = 'runtime.continue'
        status = 'continue_current_report'
        if plan.route.task is TurnTask.EXTERNAL_SUPPORT and service_offer_ids:
            runtime_action = 'runtime.wait_for_user'
            status = 'external_service_consent_required'
        elif plan.route.task is TurnTask.CLAIM_CREATION:
            if isinstance(parsed, V7ClaimCreationProposal) and parsed.ready:
                action_code = 'claim.prepare_creation'
                status = 'ready_to_create'
            else:
                runtime_action = 'runtime.wait_for_user'
                status = 'more_information_required'
        elif plan.route.task is TurnTask.EVIDENCE_HISTORY and isinstance(
            parsed, V7EvidenceActionProposal
        ):
            action_code = (
                'claim.propose_evidence_reuse'
                if parsed.action == 'reuse'
                else 'claim.propose_evidence_remove'
            )
            runtime_action = 'runtime.wait_for_user'
            status = 'evidence_confirmation_required'
        elif plan.route.task in {TurnTask.INTAKE, TurnTask.CORRECTION}:
            next_required = (
                context.branch_evaluation.requirements.next_required_item
                if context.branch_evaluation is not None
                else None
            )
            if next_required is not None:
                runtime_action = 'runtime.wait_for_user'
                status = 'more_information_required'

        elapsed_ms = sum(item.latency_ms for item in invocations)
        cache_read_values = [
            item.cache_read_input_tokens
            for item in invocations
            if item.cache_read_input_tokens is not None
        ]
        cache_write_values = [
            item.cache_write_input_tokens
            for item in invocations
            if item.cache_write_input_tokens is not None
        ]
        cache_read_tokens = sum(cache_read_values) if cache_read_values else None
        cache_write_tokens = sum(cache_write_values) if cache_write_values else None
        if plan.provider_capability.prompt_cache_type == 'none':
            cache_miss_reason = 'provider_cache_unsupported'
        elif cache_read_tokens:
            cache_miss_reason = None
        elif cache_read_tokens is None:
            cache_miss_reason = 'provider_cache_usage_unavailable'
        else:
            cache_miss_reason = 'prefix_not_cached'
        output_values = [
            item.output_tokens for item in invocations if item.output_tokens is not None
        ]
        first_token_values = [
            item.first_token_latency_ms
            for item in invocations
            if item.first_token_latency_ms is not None
        ]
        trace = RuntimeTraceRecord(
            trace_id=new_id('trc'),
            claim_id=context.claim.claim_id,
            session_id=context.session_id,
            model_profile_id=context.model_profile_id,
            trigger_message_id=context.trigger_message_id,
            evidence=[
                {
                    'evidence_id': item.evidence_id,
                    'media_type': item.media_type,
                    'outcome': 'submitted',
                }
                for item in context.evidence
            ],
            invocations=invocations,
            tool_call_id=tool_call_id,
            tool_name='context.resolve' if tool_call_id is not None else None,
            tool_arguments=tool_arguments,
            tool_output=tool_output,
            tool_result_status='succeeded' if tool_call_id is not None else None,
            action_code=action_code,
            runtime_action_code=runtime_action,
            reason_codes=answer.reason_codes,
            release_set_id=(
                context.runtime_configuration_snapshot.release_set_id
                if context.runtime_configuration_snapshot is not None
                else None
            ),
            request_profile_id=plan.request_profile.profile_id,
            provider_capability_version=plan.provider_capability.capability_version,
            prompt_bundle_id=plan.prompt_bundle_id,
            fragment_refs=plan.fragment_refs,
            schema_id=plan.schema_id,
            field_contract_id=(
                plan.field_contract.contract_id if plan.field_contract is not None else None
            ),
            field_registry_version=(
                plan.field_contract.registry_version if plan.field_contract is not None else None
            ),
            branch_evaluation_revision=(
                plan.field_contract.branch_evaluation_revision
                if plan.field_contract is not None
                else None
            ),
            field_contract_violations=field_contract_violations or [],
            repair_attempted=repair_attempted,
            repair_outcome=repair_outcome,
            route=f'{plan.route.product_family}:{plan.route.task.value}',
            context_sections=list(plan.context_plan.inline_context),
            context_load_decisions=[
                item.model_dump(mode='json') for item in plan.context_plan.load_decisions
            ],
            request_budget={
                'invocations': [item.model_dump(mode='json') for item in request_budgets],
                'turn_cumulative_tokens': request_budgets[-1].turn_cumulative_tokens,
                'hard_limit': request_budgets[-1].hard_limit,
            },
            cache_layout_version=plan.cache_plan.layout_version,
            prefix_fingerprint=plan.cache_plan.prefix_fingerprint,
            tool_manifest_id=plan.cache_plan.tool_manifest_id,
            resolved_ref_count=int(tool_call_id is not None),
            model_invocations=len(invocations),
            tool_calls=int(tool_call_id is not None),
            output_tokens=sum(output_values) if output_values else None,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_miss_reason=cache_miss_reason,
            first_token_latency_ms=first_token_values[0] if first_token_values else None,
            total_latency_ms=elapsed_ms,
            summary_state_mismatch=plan.context_plan.summary_state_mismatch,
            slo_met=elapsed_ms <= 10_000,
            status='succeeded',
            created_at=started_at,
            finished_at=datetime.now(UTC),
        )
        return AgentProposal(
            action=AgentAction.UPDATE,
            action_code=action_code,
            reason_codes=answer.reason_codes,
            customer_reason=f'The {plan.route.task.value} proposal passed the v7 Runtime boundary.',
            customer_response=answer.reply,
            customer_next_step=CustomerNextStep(
                status=status,
                summary=answer.next_step,
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
            form_changes=form_changes,
            contents_item_changes=contents_changes,
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            controlled_rule_authorised=False,
            proposal_source=AgentProposalSource.MODEL_GATEWAY,
            model_provenance=ModelDecisionProvenance(
                provider_model=response.provider_model,
                provider_request_id=response.provider_request_id,
                prompt_id=plan.prompt_bundle_id,
            ),
            runtime_trace=trace,
            evidence_id=evidence_id,
            source_claim_id=source_claim_id,
            removal_scope=removal_scope,
            external_service_intents=[
                {'service_identity': item, 'requested_action': 'submit_request'}
                for item in service_offer_ids
            ],
        )

    def _propose_v7_turn(self, context: AgentTurnContext) -> AgentProposal:
        try:
            plan = plan_model_turn(context)
        except ContextBudgetExceeded:
            budget_response = (
                context.runtime_policy.controlled_rules.deterministic_responses.get(
                    'context_budget_exceeded'
                )
                if context.runtime_policy is not None
                else None
            ) or 'Please provide one shorter detail so I can continue this report safely.'
            return AgentProposal(
                action=AgentAction.UPDATE,
                reason_codes=['CONTEXT_BUDGET_EXCEEDED'],
                customer_reason='Authority-critical context exceeded the published request budget.',
                customer_response=budget_response,
                customer_next_step=CustomerNextStep(
                    status='shorter_detail_required',
                    summary='Provide one shorter detail.',
                    responsible_party=ResponsibleParty.CLAIMANT,
                ),
                form_changes=[],
                state_changes=[],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=[],
            )
        if plan is None:
            route = route_turn(context)
            return AgentProposal(
                action=AgentAction.UPDATE,
                action_code='conversation.answer',
                reason_codes=['PRODUCT_FAMILY_REQUIRED'],
                customer_reason='A single Claim family is required.',
                customer_response=route.deterministic_response or 'Please choose one Claim type.',
                customer_next_step=CustomerNextStep(
                    status='claim_family_required',
                    summary='Choose motor, home, or contents.',
                    responsible_party=ResponsibleParty.CLAIMANT,
                ),
                form_changes=[],
                state_changes=[],
                proposed_signals=[],
                required_tools=[],
                next_action_requirements=[],
            )

        started_at = datetime.now(UTC)
        if plan.request_profile.isolated:
            isolated_observations: list[_ObservedModelInvocation] = []
            context_sizes = _model_context_size_metrics(
                context,
                json.dumps(plan.context_payload, separators=(',', ':'), sort_keys=True),
            )
            try:
                outcome = execute_isolated_context_plan(
                    lambda request: self._observed_complete(
                        request,
                        context,
                        'isolated',
                        isolated_observations,
                    ),
                    context,
                    plan,
                    (
                        context.runtime_policy.controlled_rules.context_budget_policy
                        if context.runtime_policy is not None
                        and context.runtime_policy.controlled_rules.context_budget_policy
                        is not None
                        else ContextBudgetPolicy()
                    ),
                )
                result = self._v7_proposal(
                    plan,
                    context,
                    outcome.response,
                    [_runtime_invocation_trace(1, outcome.response, outcome.latency_ms)],
                    tool_call_id=None,
                    tool_arguments={},
                    tool_output={
                        'isolated_task_id': outcome.task.task_id,
                        'source_refs': outcome.result.source_refs,
                        'source_versions': outcome.result.source_versions,
                        'truncated': outcome.result.truncated,
                    },
                    started_at=started_at,
                    request_budgets=[outcome.request_budget],
                )
            except ModelGatewayError as error:
                self._record_observations(isolated_observations, context_sizes, error)
                raise
            self._record_observations(isolated_observations, context_sizes)
            return result
        context_json = json.dumps(plan.context_payload, separators=(',', ':'), sort_keys=True)
        user_message = (
            ModelMessage(
                role=ModelRole.USER,
                content_blocks=[
                    ModelTextContent(text=context_json),
                    *[
                        ModelEvidenceContent(
                            evidence_id=item.evidence_id,
                            media_type=item.media_type,
                        )
                        for item in context.evidence
                    ],
                ],
            )
            if context.evidence
            else ModelMessage(role=ModelRole.USER, content=context_json)
        )
        messages = [
            ModelMessage(role=ModelRole.SYSTEM, content=plan.system_instruction),
            user_message,
        ]
        observations: list[_ObservedModelInvocation] = []
        invocations: list[RuntimeInvocationTrace] = []
        tool_call_id: str | None = None
        tool_arguments: dict[str, object] = {}
        tool_output: dict[str, object] = {}
        response: ModelResponse | None = None
        request_budgets = [plan.request_budget]
        context_sizes = _model_context_size_metrics(context, context_json)
        try:
            request = self._v7_request(
                plan,
                context,
                messages,
                include_tools=bool(plan.request_profile.tool_names),
            )
            exchange_completion = self._open_exchange(request, context)
            response = self._observed_complete(
                request,
                context,
                'single',
                observations,
                exchange_completion,
            )
            invocations.append(_runtime_invocation_trace(1, response, observations[-1].latency_ms))
            if plan.request_profile.requires_tool_continuation and not response.tool_calls:
                raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
            if response.tool_calls:
                if (
                    len(response.tool_calls) != 1
                    or response.tool_calls[0].name != 'context.resolve'
                    or plan.request_profile.max_model_invocations != 2
                ):
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
                tool_call = response.tool_calls[0]
                tool_call_id = tool_call.call_id
                tool_arguments = dict(tool_call.arguments)
                try:
                    if context.progress_reporter is not None:
                        context.progress_reporter(
                            AgentTurnProgressStage.TOOL_RUNNING,
                            'context.resolve',
                        )
                    ref = str(tool_call.arguments['ref'])
                    selector = str(tool_call.arguments['selector'])
                    raw_max_tokens = tool_call.arguments['max_tokens']
                    if isinstance(raw_max_tokens, bool) or not isinstance(
                        raw_max_tokens, str | int
                    ):
                        raise ValueError('max_tokens must be an integer.')
                    max_tokens = int(raw_max_tokens)
                    resolved = resolver_for_turn(context, plan.context_plan).resolve(
                        ref,
                        selector,
                        max_tokens,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from error
                continuation_tool_output = {
                    'ref': resolved.ref,
                    'selector': resolved.selector,
                    'content': resolved.content,
                    'next_cursor': resolved.next_cursor,
                    'truncated': resolved.truncated,
                    'actual_tokens': resolved.actual_tokens,
                }
                tool_output = {
                    key: value
                    for key, value in continuation_tool_output.items()
                    if key != 'content'
                }
                continuation_messages = [
                    *messages,
                    ModelMessage(
                        role=ModelRole.ASSISTANT,
                        content=response.text,
                        tool_calls=response.tool_calls,
                    ),
                    ModelMessage(
                        role=ModelRole.TOOL,
                        name='context.resolve',
                        tool_call_id=tool_call.call_id,
                        content=json.dumps(
                            continuation_tool_output,
                            separators=(',', ':'),
                            sort_keys=True,
                        ),
                    ),
                ]
                continuation = self._v7_request(
                    plan,
                    context,
                    continuation_messages,
                    include_tools=False,
                )
                continuation_budget = build_request_budget(
                    policy=(
                        context.runtime_policy.controlled_rules.context_budget_policy
                        if context.runtime_policy is not None
                        and context.runtime_policy.controlled_rules.context_budget_policy
                        is not None
                        else ContextBudgetPolicy()
                    ),
                    profile=plan.request_profile,
                    prompt='',
                    schema=plan.response_schema,
                    context={
                        'messages': [item.model_dump(mode='json') for item in continuation_messages]
                    },
                    tools=[],
                    prior_turn_tokens=plan.request_budget.raw_input_tokens,
                )
                request_budgets.append(continuation_budget)
                plan = plan.model_copy(update={'request_budget': continuation_budget})
                response = self._observed_complete(
                    continuation,
                    context,
                    'continuation',
                    observations,
                    exchange_completion,
                )
                invocations.append(
                    _runtime_invocation_trace(2, response, observations[-1].latency_ms)
                )
                if response.tool_calls:
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
            if response.completion_status is ModelCompletionStatus.INCOMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.INCOMPLETE_RESPONSE)
            if response.completion_status is ModelCompletionStatus.REFUSED:
                raise ModelGatewayError(ModelGatewayErrorCode.REFUSED_RESPONSE)
            if response.completion_status is not ModelCompletionStatus.COMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            if context.progress_reporter is not None:
                context.progress_reporter(
                    AgentTurnProgressStage.TURN_VALIDATING,
                    'field_contract.validate',
                )
            try:
                result = self._v7_proposal(
                    plan,
                    context,
                    response,
                    invocations,
                    tool_call_id=tool_call_id,
                    tool_arguments=tool_arguments,
                    tool_output=tool_output,
                    started_at=started_at,
                    request_budgets=request_budgets,
                )
            except TurnFieldContractViolation as contract_error:
                violations = [item.model_dump(mode='json') for item in contract_error.violations]
                logger.info(
                    'agent.field_contract.validation',
                    extra={
                        'turn_id': context.trigger_message_id,
                        'model_profile_id': context.model_profile_id,
                        'field_contract_id': (
                            plan.field_contract.contract_id
                            if plan.field_contract is not None
                            else None
                        ),
                        'violations': violations,
                        'repair_attempted': True,
                        'repair_outcome': 'started',
                    },
                )
                if tool_call_id is not None or plan.field_contract is None:
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
                original_output = response.structured_output
                if not isinstance(original_output, dict):
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
                invalid_field_codes = {violation['field_code'] for violation in violations}
                original_changes = original_output.get('field_changes')
                if not isinstance(original_changes, list):
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
                invalid_changes = [
                    item
                    for item in original_changes
                    if isinstance(item, dict) and item.get('field_code') in invalid_field_codes
                ]
                repair_contract = plan.field_contract.model_copy(
                    update={
                        'fields': [
                            item
                            for item in plan.field_contract.fields
                            if item.field_code in invalid_field_codes
                        ]
                    }
                )
                bound_schema = bind_provider_schema(
                    load_response_schema(plan.schema_id),
                    repair_contract,
                )
                repair_properties = bound_schema.get('properties')
                if not isinstance(repair_properties, dict):
                    raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
                repair_field_changes = repair_properties.get('field_changes')
                if not isinstance(repair_field_changes, dict):
                    raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
                repair_schema: dict[str, object] = {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['field_changes'],
                    'properties': {'field_changes': repair_field_changes},
                }
                repair_messages = [
                    ModelMessage(
                        role=ModelRole.SYSTEM,
                        content=(
                            'Correct only the invalid field_changes. Preserve the response intent, '
                            'use only the supplied field contract, and do not request tools.'
                        ),
                    ),
                    ModelMessage(
                        role=ModelRole.USER,
                        content=json.dumps(
                            {
                                'invalid_fields': violations,
                                'field_contract': {
                                    item.field_code: {
                                        'value_type': item.value_type,
                                        'allowed_values': item.allowed_values,
                                    }
                                    for item in plan.field_contract.fields
                                    if item.field_code in invalid_field_codes
                                },
                                'invalid_field_changes': invalid_changes,
                            },
                            separators=(',', ':'),
                            sort_keys=True,
                        ),
                    ),
                ]
                repair_request = ModelRequest(
                    model_profile_id=context.model_profile_id,
                    purpose=CLAIMANT_AGENT_PURPOSE,
                    prompt_version=CLAIMANT_V7_PROMPT_ID,
                    privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
                    required_capabilities=ModelCapabilities(structured_output=True),
                    messages=repair_messages,
                    response_schema=repair_schema,
                    tools=[],
                    max_output_tokens=80,
                )
                repair_profile = plan.request_profile.model_copy(
                    update={
                        'profile_id': 'field-contract-repair.v1',
                        'input_hard_limit': 1200,
                        'output_limit': 80,
                        'isolated': True,
                    }
                )
                repair_budget = build_request_budget(
                    policy=(
                        context.runtime_policy.controlled_rules.context_budget_policy
                        if context.runtime_policy is not None
                        and context.runtime_policy.controlled_rules.context_budget_policy
                        is not None
                        else ContextBudgetPolicy()
                    ),
                    profile=repair_profile,
                    prompt='',
                    schema=repair_schema,
                    context={
                        'messages': [item.model_dump(mode='json') for item in repair_messages]
                    },
                    tools=[],
                    prior_turn_tokens=0,
                )
                request_budgets.append(repair_budget)
                response = self._observed_complete(
                    repair_request,
                    context,
                    'field_contract_repair',
                    observations,
                    exchange_completion,
                )
                invocations.append(
                    _runtime_invocation_trace(2, response, observations[-1].latency_ms)
                )
                if (
                    response.tool_calls
                    or response.completion_status is not ModelCompletionStatus.COMPLETE
                    or not isinstance(response.structured_output, dict)
                ):
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
                repaired_output = response.structured_output
                response = response.model_copy(
                    update={
                        'structured_output': _merge_field_contract_repair(
                            original_output,
                            repaired_output,
                            {violation['field_code'] for violation in violations},
                        )
                    }
                )
                if context.progress_reporter is not None:
                    context.progress_reporter(
                        AgentTurnProgressStage.TURN_VALIDATING,
                        'field_contract.repair_validate',
                    )
                try:
                    result = self._v7_proposal(
                        plan,
                        context,
                        response,
                        invocations,
                        tool_call_id=None,
                        tool_arguments={},
                        tool_output={},
                        started_at=started_at,
                        request_budgets=request_budgets,
                        repair_attempted=True,
                        repair_outcome='corrected',
                        field_contract_violations=violations,
                    )
                except TurnFieldContractViolation:
                    logger.info(
                        'agent.field_contract.validation',
                        extra={
                            'turn_id': context.trigger_message_id,
                            'model_profile_id': context.model_profile_id,
                            'field_contract_id': plan.field_contract.contract_id,
                            'violations': violations,
                            'repair_attempted': True,
                            'repair_outcome': 'failed',
                        },
                    )
                    raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
        except ModelGatewayError as error:
            self._record_observations(observations, context_sizes, error)
            raise
        self._record_observations(observations, context_sizes)
        return result

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        if context.evidence_refs != [item.evidence_id for item in context.evidence]:
            raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
        if (
            context.runtime_policy is not None
            and context.runtime_policy.instruction.prompt_version == CLAIMANT_V7_PROMPT_ID
        ):
            return self._propose_v7_turn(context)
        shadow_context_plan = self._shadow_v7_plan(context)
        instruction = (
            context.runtime_policy.instruction.system_prompt
            if context.runtime_policy is not None
            else (self._instruction_provider() if self._instruction_provider else None)
            or _SYSTEM_INSTRUCTION
        )
        instruction = (
            f'{instruction}\n\n'
            'Runtime contract: first call the read-only claim.read tool with an empty object. '
            'After its result, return JSON with action_code="conversation.answer" for ordinary '
            'intake. When customer_next_step.status is "ready_to_create", use '
            'action_code="claim.prepare_creation" to ask for the final creation choice; do not '
            'use claim.create because the authenticated creation boundary dispatches that action '
            'only after the claimant submits the explicit choice. Use '
            'action_code="human.create_handoff" only when the claimant explicitly '
            'requests human help or a deterministic safety/support rule requires it. When the '
            'claimant asks to find, reuse, or remove prior Evidence, use '
            'action_code="claim.propose_evidence_reuse" or '
            'action_code="claim.propose_evidence_remove" with the Evidence identifiers. The '
            'Runtime will load authorised Evidence history and ask you to re-plan before it '
            'accepts either proposal. A reuse proposal must ask for explicit claimant '
            'confirmation before any Evidence API attach operation. If an Evidence history '
            'result contains page.next_cursor, do not describe the page as an exhaustive '
            'not-found result; a later bounded lookup may continue from that cursor. '
            'runtime_action_code, reason_codes, customer_reason, customer_response, '
            'customer_next_step, and only registered form_changes or contents_item_changes '
            'grounded in the claimant message. Preserve approximate values and reported_text. '
            'Do not claim that a formal Claim was created, an external provider was contacted, '
            'or a staff member accepted the handoff unless the Runtime returns that result. '
            'Treat external_services as read-only Runtime facts. Follow their claimant meaning, '
            'limitation, pending owner, and next action; never infer provider completion, advance '
            'a lifecycle status, or retry an unknown outcome from model judgement. '
            'Use conversation_history only as context; Claim State and registered facts are '
            'authoritative, and do not repeat a question already answered by a confirmed fact. '
            'Every form change value must match field_value_contracts exactly: use JSON booleans '
            'for boolean fields and only a listed string for enum fields. For a fact read from an '
            'attached Evidence block, including a contents item, set source_evidence_id to the '
            'exact matching ID in attached_evidence and leave reported_text empty. Never use an '
            'Evidence ID that is not listed there. Attachment-derived facts remain proposals for '
            'claimant confirmation. Do not derive contents ownership or value from an attachment.'
        )
        prompt_version = (
            context.runtime_policy.instruction.prompt_version
            if context.runtime_policy is not None
            else MOTOR_CLAIMANT_PROMPT_ID
        )
        context_json = json.dumps(
            _model_turn_context(context).model_dump(mode='json'),
            separators=(',', ':'),
        )
        user_message = (
            ModelMessage(
                role=ModelRole.USER,
                content_blocks=[
                    ModelTextContent(text=context_json),
                    *[
                        ModelEvidenceContent(
                            evidence_id=item.evidence_id,
                            media_type=item.media_type,
                        )
                        for item in context.evidence
                    ],
                ],
            )
            if context.evidence
            else ModelMessage(role=ModelRole.USER, content=context_json)
        )
        messages = [
            ModelMessage(role=ModelRole.SYSTEM, content=instruction),
            user_message,
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
                image_input=any(item.media_type.startswith('image/') for item in context.evidence),
                document_input=any(
                    item.media_type == 'application/pdf' for item in context.evidence
                ),
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
            required_tool_name=claim_read.name if self._gateway.capabilities.tools else None,
        )
        context_sizes = _model_context_size_metrics(context, context_json)
        observed_invocations: list[_ObservedModelInvocation] = []
        response: ModelResponse | None = None
        invocations: list[RuntimeInvocationTrace] = []
        tool_call_id: str | None = None
        tool_arguments: dict[str, object] = {}
        tool_output: dict[str, object] = {}
        try:
            response = self._observed_complete(
                request,
                context,
                'initial',
                observed_invocations,
            )
            invocations.append(
                _runtime_invocation_trace(
                    1,
                    response,
                    observed_invocations[-1].latency_ms,
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
                tool_output = dict(tool_result)
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
                        image_input=any(
                            item.media_type.startswith('image/') for item in context.evidence
                        ),
                        document_input=any(
                            item.media_type == 'application/pdf' for item in context.evidence
                        ),
                    ),
                    messages=continuation_messages,
                    response_schema=_RUNTIME_PROPOSAL_ADAPTER.json_schema(),
                )
                response = self._observed_complete(
                    continuation,
                    context,
                    'continuation',
                    observed_invocations,
                )
                invocations.append(
                    _runtime_invocation_trace(
                        2,
                        response,
                        observed_invocations[-1].latency_ms,
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
                # ModelRuntimeProposal validates registry membership.  Keep the
                # explicit lookup here as a second boundary so a malformed or
                # stale provider response can never introduce a private action.
                try:
                    action_contract(runtime_proposal.action_code)
                    action_contract(runtime_proposal.runtime_action_code)
                except ValueError:
                    raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY) from None
                evidence_action_requested = runtime_proposal.action_code in {
                    'claim.propose_evidence_reuse',
                    'claim.propose_evidence_remove',
                }
                evidence_history_loaded = any(
                    item.get('tool') == 'evidence.history' for item in context.tool_results
                )
                effective_action_code = (
                    'conversation.answer'
                    if evidence_action_requested and not evidence_history_loaded
                    else runtime_proposal.action_code
                )
                result = AgentProposal(
                    action=(
                        AgentAction.HANDOFF
                        if runtime_proposal.action_code == 'human.create_handoff'
                        else AgentAction.UPDATE
                    ),
                    action_code=effective_action_code,
                    reason_codes=runtime_proposal.reason_codes,
                    customer_reason=runtime_proposal.customer_reason,
                    customer_response=runtime_proposal.customer_response,
                    customer_next_step=runtime_proposal.customer_next_step,
                    form_changes=[
                        _model_form_change(
                            change,
                            message_text=context.message_text,
                            evidence=context.evidence,
                        )
                        for change in runtime_proposal.form_changes
                    ],
                    contents_item_changes=[
                        _model_contents_item_change(item, evidence=context.evidence)
                        for item in runtime_proposal.contents_item_changes
                    ],
                    state_changes=[],
                    proposed_signals=[],
                    required_tools=(
                        [{'tool': 'evidence.history', 'operation': 'list'}]
                        if evidence_action_requested and not evidence_history_loaded
                        else []
                    ),
                    next_action_requirements=[],
                    proposal_source=AgentProposalSource.MODEL_GATEWAY,
                    handoff_priority=runtime_proposal.handoff_priority,
                    evidence_id=runtime_proposal.evidence_id,
                    source_claim_id=runtime_proposal.source_claim_id,
                    removal_scope=runtime_proposal.removal_scope,
                    external_service_intents=[
                        item.model_dump(mode='json')
                        for item in runtime_proposal.external_service_intents
                    ],
                    # Model output is advisory. Deterministic support/safety interrupts are
                    # evaluated before this provider and are the only source of handoff authority.
                    controlled_rule_authorised=False,
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
                        evidence=[
                            {
                                'evidence_id': item.evidence_id,
                                'media_type': item.media_type,
                                'outcome': 'submitted',
                            }
                            for item in context.evidence
                        ],
                        invocations=invocations,
                        tool_call_id=tool_call_id or 'unknown',
                        tool_name=claim_read.name,
                        tool_arguments=tool_arguments,
                        tool_output=tool_output,
                        tool_result_status='succeeded',
                        action_code=effective_action_code,
                        runtime_action_code=runtime_proposal.runtime_action_code,
                        reason_codes=runtime_proposal.reason_codes,
                        shadow_context_plan=shadow_context_plan,
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
                    evidence=context.evidence,
                    provider_model=response.provider_model,
                    provider_request_id=response.provider_request_id,
                    prompt_id=prompt_version,
                )
        except ModelGatewayError as error:
            self._record_observations(observed_invocations, context_sizes, error)
            raise
        self._record_observations(observed_invocations, context_sizes)
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
        cache_read_input_tokens=(usage.cache_read_input_tokens if usage is not None else None),
        cache_write_input_tokens=(usage.cache_write_input_tokens if usage is not None else None),
        first_token_latency_ms=response.first_token_latency_ms,
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

    def _v7_knowledge_context(
        self,
        context: AgentTurnContext,
        max_tokens: int,
    ) -> dict[str, object]:
        product = _knowledge_product(context.claim.incident_type)
        if product is None:
            return {
                'status': 'no_evidence',
                'chunks': [],
                'limitations': ['A confirmed product family is required for scoped search.'],
            }
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
        if resolution_error:
            return {
                'status': 'unavailable',
                'chunks': [],
                'limitations': [
                    'The active Runtime release does not select an approved knowledge version.'
                ],
            }
        knowledge_version = published.version if published is not None else 'MVP-2026.1'
        try:
            chunks = self._retriever.search(
                KnowledgeSearch(
                    text=(context.message_text or '').strip(),
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
        except KnowledgeRetrievalUnavailable:
            return {
                'status': 'unavailable',
                'chunks': [],
                'limitations': ['Approved knowledge retrieval is temporarily unavailable.'],
            }
        if not chunks:
            return {
                'status': 'no_evidence',
                'chunks': [],
                'limitations': [
                    'No applicable approved knowledge was found for the supplied scope and date.'
                ],
            }
        max_chars_per_chunk = max(120, max_tokens * 3 // len(chunks))
        return {
            'status': 'evidence_found',
            'chunks': [
                {
                    'document_id': chunk.document_id,
                    'chunk_id': chunk.chunk_id,
                    'title': chunk.title,
                    'section_path': chunk.section_path,
                    'source_uri': chunk.source_uri,
                    'version': chunk.version,
                    'text': chunk.text[:max_chars_per_chunk],
                }
                for chunk in chunks
            ],
            'limitations': [],
        }

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        if (
            context.runtime_policy is not None
            and context.runtime_policy.instruction.prompt_version == CLAIMANT_V7_PROMPT_ID
        ):
            source_context = context
            context = replace(
                context,
                knowledge_context_loader=lambda max_tokens: self._v7_knowledge_context(
                    source_context,
                    max_tokens,
                ),
            )
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
