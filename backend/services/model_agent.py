import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    ModelRequestBudget,
    PlannedModelTurn,
    TurnTask,
)
from backend.domain.agent_v7 import (
    V7AnswerProposal,
    V7EvidenceActionProposal,
    V7SourcedSummaryProposal,
)
from backend.domain.agent_v8 import V8TurnProposal
from backend.domain.branch_registry import BranchRuleEvaluator, build_default_registry
from backend.domain.ids import new_id
from backend.domain.knowledge import (
    KnowledgeRetrievalUnavailable,
    KnowledgeRetriever,
    KnowledgeSearch,
)
from backend.domain.model_gateway import (
    CLAIMANT_AGENT_PRIVACY_CLASS,
    CLAIMANT_AGENT_PURPOSE,
    ModelAgentProposal,
    ModelCapabilities,
    ModelCompletionStatus,
    ModelEvidenceContent,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelRuntimeProposal,
    ModelTextContent,
)
from backend.domain.models import (
    AgentAction,
    AgentProposalSource,
    CustomerNextStep,
    ModelDecisionProvenance,
    ProposedContentsItem,
    ProposedFormChange,
    ResponsibleParty,
    RuntimeInvocationTrace,
    RuntimeTraceRecord,
)
from backend.domain.realtime import AgentTurnProgressStage
from backend.domain.turn_field_contract import RepairOutcome, TurnFieldContractViolation
from backend.prompts import CLAIMANT_V8_PROMPT_ID
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.services.agent import (
    AgentProposal,
    AgentTurnContext,
    AgentTurnProvider,
    published_prompt_version,
)
from backend.services.context_budget import build_request_budget
from backend.services.context_planner import ContextBudgetExceeded
from backend.services.context_resolver import ContextResultBudgetExceeded, resolver_for_turn
from backend.services.isolated_context_executor import execute_isolated_context_plan
from backend.services.knowledge_manifest import approved_version_for_product
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.model_request_planner import (
    context_resolve_tool,
    detach_unreadable_evidence,
    plan_model_turn,
    prepare_model_family_context,
)
from backend.services.prompt_composer import load_response_schema
from backend.services.reply_consistency import (
    ConsistencyReview,
    keep_recorded_parts,
    review_reply,
)
from backend.services.reply_judge import ReplyJudge
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)
from backend.services.turn_family_resolution import resolve_turn_family
from backend.services.turn_field_contract import bind_provider_schema
from backend.services.turn_proposal_validation import (
    ValidatedTurn,
    parse_turn_proposal,
    truthful_reply,
    validate_turn_proposal,
)
from backend.services.validation_diagnostic import validation_path

logger = logging.getLogger(__name__)

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


_V7_EVIDENCE_ADAPTER = TypeAdapter(V7EvidenceActionProposal)
_V7_SOURCED_SUMMARY_ADAPTER = TypeAdapter(V7SourcedSummaryProposal)

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
        'contents': 'contents',
    }.get(incident_type or '')


class GatewayAgent:
    def __init__(
        self,
        gateway: ModelGateway,
        operations: ModelOperationsRecorder | None = None,
        reply_judge: ReplyJudge | None = None,
        turn_time_limit_seconds: float | None = None,
    ) -> None:
        self._gateway = gateway
        self._operations = operations
        self._reply_judge = reply_judge
        self._turn_time_limit_seconds = turn_time_limit_seconds

    def _require_turn_time(self, started_at: datetime) -> None:
        """Stop before another model call once the whole turn is over its limit.

        Each call has its own provider timeout; this caps the turn, so a slow
        first answer is not followed by a second slow call the claimant waits on.
        """
        limit = self._turn_time_limit_seconds
        if limit is not None and (datetime.now(UTC) - started_at).total_seconds() >= limit:
            raise ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True)

    def _review(self, validated: ValidatedTurn, context: AgentTurnContext) -> ConsistencyReview:
        """Review the reply after the turn's model calls.

        The turn time limit caps the turn's own model calls; the review model runs
        after them with its own timeout, so a reply is never left to rules because
        the turn was slow.
        """

        review = review_reply(validated, self._reply_judge)
        logger.info(
            'agent_turn_reply_review',
            extra={
                'claim_id': context.claim.claim_id,
                'trigger_message_id': context.trigger_message_id,
                'words_reviewed': review.words_reviewed,
                'problems': [item.kind for item in review.inconsistencies],
            },
        )
        return review

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
            prompt_version=published_prompt_version(context),
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
            required_tool_name=(
                'context.resolve'
                if tools
                and (
                    plan.request_profile.requires_tool_continuation
                    or 'policy_lookup' in plan.route.intents
                )
                else None
            ),
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
        authorized_policy_sources: list[dict[str, object]] | None = None,
        diagnostic_stage: str = 'initial',
    ) -> AgentProposal:
        if response.structured_output is None:
            logger.warning(
                'agent_turn_envelope_missing',
                extra={
                    'schema_id': plan.schema_id,
                    'completion_status': response.completion_status.value,
                    'finish_reason': response.finish_reason,
                    'text_present': bool(response.text),
                    'text_length': len(response.text) if response.text else 0,
                    'tool_call_count': len(response.tool_calls),
                    'provider_model': response.provider_model,
                },
            )
            raise ModelGatewayError(
                ModelGatewayErrorCode.MALFORMED_RESPONSE,
                diagnostic_code=f'{diagnostic_stage}_output_missing',
            )
        raw_output = dict(response.structured_output)
        try:
            parsed: Any
            optional_rejections: list[dict[str, str]] = []
            if plan.schema_id == 'claimant.turn.v1':
                parsed, optional_rejections = parse_turn_proposal(raw_output)
            elif plan.schema_id == 'claimant.evidence-action.v1':
                parsed = _V7_EVIDENCE_ADAPTER.validate_python(raw_output)
            elif plan.schema_id == 'claimant.sourced-summary.v1':
                parsed = _V7_SOURCED_SUMMARY_ADAPTER.validate_python(raw_output)
            else:
                # Only the current prompt pack's response schemas are published.
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        except ValidationError as error:
            logger.warning(
                'agent_turn_envelope_invalid',
                extra={
                    'schema_id': plan.schema_id,
                    'errors': [
                        {
                            'loc': '.'.join(str(part) for part in item['loc']),
                            'type': item['type'],
                            'msg': item.get('msg'),
                            'input': str(item.get('input'))[:200],
                        }
                        for item in error.errors()[:8]
                    ],
                },
            )
            raise ModelGatewayError(
                ModelGatewayErrorCode.MALFORMED_RESPONSE,
                diagnostic_code=f'{diagnostic_stage}_output_schema_validation',
                diagnostic_path=validation_path(error.errors()),
            ) from None

        if isinstance(parsed, V8TurnProposal):
            answer = V7AnswerProposal(
                reply=parsed.reply,
                next_step=(
                    parsed.next_question.wording
                    if parsed.next_question is not None
                    else 'Continue the current report.'
                ),
                reason_codes=parsed.reason_codes or [f'TURN_{parsed.action.upper()}'],
            )
        elif isinstance(parsed, V7SourcedSummaryProposal):
            answer = V7AnswerProposal(
                reply=parsed.summary,
                next_step='Continue the Claim with the sourced review when ready.',
                reason_codes=['ISOLATED_CONTEXT_REVIEWED'],
            )
        else:
            answer = cast(V7AnswerProposal, parsed)
        form_changes: list[ProposedFormChange] = []
        contents_changes: list[ProposedContentsItem] = []
        service_offer_ids: list[str] = []
        model_required_items: list[str] = []
        evidence_id: str | None = None
        source_claim_id: str | None = None
        removal_scope: str | None = None
        proposal_confirms_batch = False
        validated_turn: ValidatedTurn | None = None
        if isinstance(parsed, V8TurnProposal):
            if plan.field_contract is None:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            branch_evaluation = context.branch_evaluation
            if branch_evaluation is None:
                evaluator = (
                    context.runtime_policy.branch_evaluator()
                    if context.runtime_policy is not None
                    else BranchRuleEvaluator()
                )
                branch_evaluation = evaluator.evaluate(
                    context.claim,
                    latest_message=context.message_text,
                    recomputation_reason='turn_proposal_validation',
                )
            validated_turn = validate_turn_proposal(
                parsed,
                branch_evaluation=branch_evaluation,
                eligible_service_ids=(
                    cast(frozenset[str], context.eligible_service_ids)
                    if getattr(context, 'eligible_service_ids', None) is not None
                    else {item.service_identity for item in context.external_services}
                ),
                safety_interrupt=getattr(context, 'safety_interrupt', None),
                field_contract=plan.field_contract,
                open_handoffs=getattr(context, 'open_handoffs', ()),
                message_text=context.message_text,
                evidence=context.evidence,
                authorized_policy_sources=authorized_policy_sources or (),
                service_eligibility_resolver=context.service_eligibility_resolver,
                authorised_service_ids={
                    consent.service_identity
                    for consent in context.claim.external_service_consents
                    if consent.status.value == 'granted'
                },
            )
            if optional_rejections:
                validated_turn = replace(
                    validated_turn, rejected=[*optional_rejections, *validated_turn.rejected]
                )
            validated_turn = replace(
                validated_turn,
                earlier_open_questions=tuple(
                    str(item.get('question'))
                    for item in getattr(context, 'northwind_questions', ())
                    if item.get('state') == 'open' and item.get('question')
                ),
            )
            form_changes = validated_turn.form_changes
            contents_changes = validated_turn.contents_item_changes
            service_offer_ids = list(validated_turn.service_identities)
            if validated_turn.next_question is not None:
                model_required_items = list(validated_turn.next_question.field_codes)
            proposal_confirms_batch = validated_turn.confirms_batch
            answer = answer.model_copy(update={'reply': validated_turn.reply})
        elif isinstance(parsed, V7EvidenceActionProposal):
            evidence_id = parsed.evidence_id
            source_claim_id = parsed.source_claim_id
            removal_scope = parsed.removal_scope

        available_services = {item.service_identity for item in context.external_services}
        if isinstance(parsed, V8TurnProposal):
            service_offer_ids = [
                service_id for service_id in service_offer_ids if service_id in available_services
            ]
        else:
            service_offer_ids = [
                service_id
                for service_id in context.selected_external_service_ids
                if service_id in available_services
            ]
        if validated_turn is None:
            answer = answer.model_copy(update={'reply': truthful_reply(answer.reply)})
        if service_offer_ids and context.progress_reporter is not None:
            context.progress_reporter(
                AgentTurnProgressStage.OFFER_PREPARING,
                'external.support_options',
            )

        action_code = 'conversation.answer'
        action = AgentAction.UPDATE
        handoff_priority = None
        runtime_action = 'runtime.continue'
        status = 'continue_current_report'
        if 'external' in plan.route.intents and service_offer_ids:
            runtime_action = 'runtime.wait_for_user'
            status = 'external_service_consent_required'
        elif plan.route.task is TurnTask.CLAIM_CREATION:
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
        if validated_turn is not None:
            if validated_turn.next_question is not None:
                answer = answer.model_copy(
                    update={'next_step': validated_turn.next_question.wording}
                )
                status = 'more_information_required'
                runtime_action = 'runtime.wait_for_user'
            if validated_turn.ready_to_create:
                action_code = 'claim.prepare_creation'
                status = 'ready_to_create'
                runtime_action = 'runtime.continue'
            if validated_turn.escalation is not None and not context.open_handoffs:
                urgent = validated_turn.escalation.kind == 'urgent_safety'
                action = AgentAction.URGENT_HANDOFF if urgent else AgentAction.HANDOFF
                action_code = 'human.create_handoff'
                runtime_action = 'runtime.pause_for_review'
                handoff_priority = 'urgent' if urgent else 'high'
                status = 'waiting_for_professional'

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
            action=action,
            action_code=action_code,
            reason_codes=answer.reason_codes,
            customer_reason=f'The {plan.route.task.value} proposal passed the v7 Runtime boundary.',
            customer_response=answer.reply,
            customer_next_step=CustomerNextStep(
                status=status,
                summary=answer.next_step,
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=model_required_items,
            ),
            form_changes=form_changes,
            contents_item_changes=contents_changes,
            state_changes=validated_turn.state_changes if validated_turn is not None else [],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            controlled_rule_authorised=context.safety_interrupt is not None,
            handoff_priority=handoff_priority,
            proposal_source=AgentProposalSource.MODEL_GATEWAY,
            model_provenance=ModelDecisionProvenance(
                provider_model=response.provider_model,
                provider_request_id=response.provider_request_id,
                prompt_id=plan.prompt_bundle_id,
            ),
            runtime_trace=trace,
            confirms_batch=proposal_confirms_batch,
            raw_v8_proposal=parsed if isinstance(parsed, V8TurnProposal) else None,
            validated_turn=validated_turn,
            evidence_id=evidence_id,
            source_claim_id=source_claim_id,
            removal_scope=removal_scope,
            external_service_intents=[
                {'service_identity': item, 'requested_action': 'submit_request'}
                for item in service_offer_ids
            ],
        )

    def _propose_v7_turn(self, context: AgentTurnContext) -> AgentProposal:
        context = prepare_model_family_context(context)
        context = detach_unreadable_evidence(context)
        # Capture only guidance actually fetched through the server-authorized
        # context loader in this turn, never model-supplied tool/source strings.
        judgment_sources: list[dict[str, object]] = []
        judgment_source_candidates: dict[str, dict[str, object]] = {}
        knowledge_loader = context.knowledge_context_loader
        if knowledge_loader is not None:

            def load_judgment_guidance(
                max_tokens: int, clause_ids: Sequence[str]
            ) -> dict[str, object]:
                result = knowledge_loader(max_tokens, clause_ids)
                chunks = result.get('chunks')
                if result.get('status') == 'evidence_found' and isinstance(chunks, list):
                    for item in chunks:
                        if isinstance(item, dict) and isinstance(item.get('chunk_id'), str):
                            judgment_source_candidates[item['chunk_id']] = dict(item)
                    # Citation provenance stays server-side; the model needs the
                    # selected clause identity and its complete wording.
                    return {
                        'guidance_status': result['guidance_status'],
                        'returned_clause_ids': result['returned_clause_ids'],
                        'not_found': result['not_found'],
                        'chunks': [
                            {'chunk_id': item['chunk_id'], 'text': item['text']}
                            for item in chunks
                            if isinstance(item, dict)
                        ],
                    }
                return result

            context = replace(context, knowledge_context_loader=load_judgment_guidance)
        try:
            plan = plan_model_turn(context)
        except ContextBudgetExceeded:
            if (
                context.runtime_policy is not None
                and context.runtime_policy.instruction.prompt_version == CLAIMANT_V8_PROMPT_ID
            ):
                logger.warning(
                    'agent_turn_input_budget_hard_exceeded',
                    extra={
                        'claim_id': context.claim.claim_id,
                        'trigger_message_id': context.trigger_message_id,
                        'diagnostic': 'context_budget_exceeded',
                    },
                )
                raise ModelGatewayError(
                    ModelGatewayErrorCode.CONFIGURATION,
                    provider_error_type='context_budget_exceeded',
                ) from None
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
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)

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
                    authorized_policy_sources=judgment_sources,
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
        if 'policy_clause_directory' in plan.context_plan.inline_context:
            tool_output['policy_clause_directory'] = plan.context_plan.inline_context[
                'policy_clause_directory'
            ]
        response: ModelResponse | None = None
        request_budgets = [plan.request_budget]
        context_sizes = _model_context_size_metrics(context, context_json)
        recall_started = False
        recall_response_received = False
        response_stage = 'initial'
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
            # Ordinary claimant turns offer read-only references; the model may
            # answer without consulting them. Evidence-action envelopes still
            # require their source lookup before proposing reuse or removal.
            if (
                plan.request_profile.requires_tool_continuation
                and plan.schema_id != 'claimant.turn.v1'
                and not response.tool_calls
            ):
                raise ModelGatewayError(
                    ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
                    diagnostic_code='initial_tool_call_required',
                    diagnostic_path='tool_calls',
                )
            if response.tool_calls:
                if len(response.tool_calls) != 1:
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
                        diagnostic_code='initial_tool_call_count',
                        diagnostic_path='tool_calls',
                    )
                if response.tool_calls[0].name != 'context.resolve':
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
                        diagnostic_code='initial_tool_name',
                        diagnostic_path='tool_calls.0.name',
                    )
                if plan.request_profile.max_model_invocations != 2:
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
                        diagnostic_code='request_profile_invocation_limit',
                        diagnostic_path='request_profile.max_model_invocations',
                    )
                tool_call = response.tool_calls[0]
                tool_call_id = tool_call.call_id
                tool_arguments = dict(tool_call.arguments)
                if 'policy_lookup' in plan.route.intents:
                    policy_references = [
                        item
                        for item in plan.context_plan.references
                        if item.resource_type == 'policy_version'
                    ]
                    if len(policy_references) == 1:
                        policy_reference = policy_references[0]
                        tool_arguments.setdefault('ref', policy_reference.ref)
                        if len(policy_reference.available_selectors) == 1:
                            tool_arguments.setdefault(
                                'selector', policy_reference.available_selectors[0]
                            )
                        # The complete-clause budget is a server safety boundary. A model-selected
                        # lower value can omit the final exclusions or schedule condition.
                        tool_arguments['max_tokens'] = policy_reference.max_resolve_tokens
                try:
                    if context.progress_reporter is not None:
                        context.progress_reporter(
                            AgentTurnProgressStage.TOOL_RUNNING,
                            'context.resolve',
                        )
                    ref = str(tool_arguments['ref'])
                    selector = str(tool_arguments['selector'])
                    raw_max_tokens = tool_arguments['max_tokens']
                    if isinstance(raw_max_tokens, bool) or not isinstance(
                        raw_max_tokens, str | int
                    ):
                        raise ValueError('max_tokens must be an integer.')
                    max_tokens = int(raw_max_tokens)
                    resolved = resolver_for_turn(context, plan.context_plan).resolve(
                        ref,
                        selector,
                        max_tokens,
                        clause_ids=cast(Sequence[str], tool_arguments.get('clause_ids', [])),
                    )
                except ContextResultBudgetExceeded:
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.MALFORMED_RESPONSE,
                        diagnostic_code='context_result_budget_exceeded',
                        diagnostic_path='context.resolve.max_tokens',
                    ) from None
                except (KeyError, TypeError, ValueError):
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.MALFORMED_RESPONSE,
                        diagnostic_code='context_resolution_invalid',
                        diagnostic_path='context.resolve.arguments',
                    ) from None
                continuation_tool_output = {
                    'ref': resolved.ref,
                    'selector': resolved.selector,
                    'content': resolved.content,
                    'next_cursor': resolved.next_cursor,
                    'truncated': resolved.truncated,
                    'actual_tokens': resolved.actual_tokens,
                }
                tool_output = {
                    **tool_output,
                    **{
                        key: value
                        for key, value in continuation_tool_output.items()
                        if key != 'content'
                    },
                }
                if isinstance(resolved.content, dict):
                    guidance = resolved.content.get('approved_guidance')
                    if isinstance(guidance, dict):
                        returned_chunks = guidance.get('chunks')
                        if isinstance(returned_chunks, list):
                            judgment_sources.clear()
                            judgment_sources.extend(
                                judgment_source_candidates[item['chunk_id']]
                                for item in returned_chunks
                                if isinstance(item, dict)
                                and isinstance(item.get('chunk_id'), str)
                                and item['chunk_id'] in judgment_source_candidates
                            )
                        if 'clause_ids' in tool_arguments:
                            tool_output['requested_clause_ids'] = tool_arguments['clause_ids']
                        for key in (
                            'returned_clause_ids',
                            'not_found',
                            'not_included',
                            'guidance_status',
                        ):
                            if key in guidance:
                                tool_output[key] = guidance[key]
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
                self._require_turn_time(started_at)
                response = self._observed_complete(
                    continuation,
                    context,
                    'continuation',
                    observations,
                    exchange_completion,
                )
                response_stage = 'continuation'
                invocations.append(
                    _runtime_invocation_trace(2, response, observations[-1].latency_ms)
                )
                if response.tool_calls:
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
                        diagnostic_code='continuation_tool_call',
                        diagnostic_path='tool_calls',
                    )
            if response.completion_status is ModelCompletionStatus.INCOMPLETE:
                raise ModelGatewayError(ModelGatewayErrorCode.INCOMPLETE_RESPONSE)
            if response.completion_status is ModelCompletionStatus.REFUSED:
                raise ModelGatewayError(ModelGatewayErrorCode.REFUSED_RESPONSE)
            if response.completion_status is not ModelCompletionStatus.COMPLETE:
                logger.warning(
                    'agent_turn_unknown_completion_status',
                    extra={
                        'completion_status': response.completion_status,
                        'finish_reason': response.finish_reason,
                    },
                )
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
                    authorized_policy_sources=judgment_sources,
                    tool_call_id=tool_call_id,
                    tool_arguments=tool_arguments,
                    tool_output=tool_output,
                    started_at=started_at,
                    request_budgets=request_budgets,
                    diagnostic_stage=response_stage,
                )
                validated_turn = result.validated_turn
                review = (
                    self._review(validated_turn, context) if validated_turn is not None else None
                )
                if review is not None and validated_turn is not None and not review.consistent:
                    # The words contradict the ledger. Hand the ruling back to
                    # the model once; Runtime never rewrites the reply itself.
                    logger.info(
                        'agent_turn_consistency_recall',
                        extra={
                            'claim_id': context.claim.claim_id,
                            'trigger_message_id': context.trigger_message_id,
                            'problems': [
                                {'kind': item.kind, 'detail': item.detail}
                                for item in review.inconsistencies
                            ],
                        },
                    )
                    recall_messages = [
                        *messages,
                        ModelMessage(
                            role=ModelRole.ASSISTANT,
                            content=json.dumps(
                                response.structured_output, separators=(',', ':'), sort_keys=True
                            ),
                        ),
                        ModelMessage(
                            role=ModelRole.USER,
                            content=json.dumps(
                                review.runtime_review(validated_turn.rejected),
                                separators=(',', ':'),
                                sort_keys=True,
                            ),
                        ),
                    ]
                    recall = self._v7_request(plan, context, recall_messages, include_tools=False)
                    recall_budget = build_request_budget(
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
                            'messages': [item.model_dump(mode='json') for item in recall_messages]
                        },
                        tools=[],
                        prior_turn_tokens=plan.request_budget.raw_input_tokens,
                    )
                    request_budgets.append(recall_budget)
                    self._require_turn_time(started_at)
                    first_output = response.structured_output
                    recall_started = True
                    response = self._observed_complete(
                        recall,
                        context,
                        'consistency_recall',
                        observations,
                        exchange_completion,
                    )
                    recall_response_received = True
                    invocations.append(
                        _runtime_invocation_trace(
                            len(invocations) + 1, response, observations[-1].latency_ms
                        )
                    )
                    if response.completion_status is not ModelCompletionStatus.COMPLETE:
                        raise ModelGatewayError(
                            ModelGatewayErrorCode.MALFORMED_RESPONSE,
                            diagnostic_code='consistency_recall_completion_status',
                        )
                    response = response.model_copy(
                        update={
                            'structured_output': keep_recorded_parts(
                                first_output, response.structured_output
                            )
                        }
                    )
                    result = self._v7_proposal(
                        plan,
                        context,
                        response,
                        invocations,
                        authorized_policy_sources=judgment_sources,
                        tool_call_id=tool_call_id,
                        tool_arguments=tool_arguments,
                        tool_output=tool_output,
                        started_at=started_at,
                        request_budgets=request_budgets,
                        diagnostic_stage='consistency_recall',
                    )
                    second_review = (
                        self._review(result.validated_turn, context)
                        if result.validated_turn is not None
                        else None
                    )
                    if second_review is not None and not second_review.truthful:
                        # Still untrue after the rewrite: the saved message enters
                        # the existing persist-first recovery path unchanged.
                        logger.info(
                            'agent_turn_consistency_failed',
                            extra={
                                'claim_id': context.claim.claim_id,
                                'problems': [
                                    {'kind': item.kind, 'detail': item.detail}
                                    for item in second_review.inconsistencies
                                ],
                            },
                        )
                        raise ModelGatewayError(
                            ModelGatewayErrorCode.MALFORMED_RESPONSE,
                            diagnostic_code='consistency_recall_truthfulness',
                            diagnostic_path=(
                                'reply.' + second_review.inconsistencies[0].kind
                                if second_review.inconsistencies
                                else 'reply'
                            ),
                        )
            except TurnFieldContractViolation as contract_error:
                if plan.schema_id == 'claimant.turn.v1':
                    logger.warning(
                        'agent_turn_field_contract_violation',
                        extra={
                            'violations': [
                                item.model_dump(mode='json') for item in contract_error.violations
                            ],
                        },
                    )
                    # v8 validation drops and records individual field changes it
                    # cannot accept (validate_turn_proposal, reject_invalid), so a
                    # contract violation reaching here is a defect, not model
                    # noise: fail through persist-first recovery rather than
                    # spend another model call on a repair.
                    raise ModelGatewayError(
                        ModelGatewayErrorCode.MALFORMED_RESPONSE,
                        diagnostic_code=f'{response_stage}_field_contract_violation',
                        diagnostic_path=(
                            f'field_changes.{contract_error.violations[0].field_code}'
                            if contract_error.violations
                            else 'field_changes'
                        ),
                    ) from contract_error
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
                    prompt_version=published_prompt_version(context),
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
                        authorized_policy_sources=judgment_sources,
                        tool_call_id=None,
                        tool_arguments={},
                        tool_output={},
                        started_at=started_at,
                        request_budgets=request_budgets,
                        repair_attempted=True,
                        repair_outcome='corrected',
                        field_contract_violations=violations,
                        diagnostic_stage='field_contract_repair',
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
            if error.diagnostic_code is not None and error.diagnostic_code.startswith('proposal_'):
                stage = 'consistency_recall' if recall_started else response_stage
                error.diagnostic_code = f'{stage}_{error.diagnostic_code}'
            if recall_started and error.diagnostic_code is None:
                if recall_response_received:
                    error.diagnostic_code = 'consistency_recall_proposal_validation'
                elif error.code is ModelGatewayErrorCode.MALFORMED_RESPONSE:
                    error.diagnostic_code = 'consistency_recall_provider_output_invalid'
                else:
                    error.diagnostic_code = 'consistency_recall_gateway_failure'
            elif (
                error.diagnostic_code is None
                and error.code is ModelGatewayErrorCode.MALFORMED_RESPONSE
            ):
                error.diagnostic_code = f'{response_stage}_response_validation'
            self._record_observations(observations, context_sizes, error)
            raise
        self._record_observations(observations, context_sizes)
        return result

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        if context.evidence_refs != [item.evidence_id for item in context.evidence]:
            raise ModelGatewayError(ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE)
        published_prompt_version(context)
        return self._propose_v7_turn(context)


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

    def _knowledge_scope(self, context: AgentTurnContext) -> KnowledgeSearch | dict[str, object]:
        if (
            context.runtime_policy is not None
            and not context.runtime_policy.features.knowledge_retrieval
        ):
            return {
                'status': 'unavailable',
                'chunks': [],
                'limitations': ['Knowledge retrieval is disabled by published configuration.'],
            }
        resolution = context.turn_family_resolution or resolve_turn_family(
            context.claim,
            context.branch_evaluation,
            context.message_text,
            model_family_judgment=True,
        )
        product = _knowledge_product(resolution.product_family)
        if product is None:
            return {
                'status': 'no_evidence',
                'chunks': [],
                'limitations': ['A resolved product family is required for scoped search.'],
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
        # The approved manifest names the version when no release selects one; no default.
        knowledge_version = (
            published.version if published is not None else approved_version_for_product(product)
        )
        if knowledge_version is None:
            return {
                'status': 'unavailable',
                'chunks': [],
                'limitations': [
                    f'The approved knowledge manifest has no single version for {product}.'
                ],
            }
        return KnowledgeSearch(
            text='',
            jurisdiction='NZ',
            visibility='customer_and_staff',
            authority='northwind_synthetic_demo',
            version=knowledge_version,
            insurer='Northwind Insurance',
            product=product,
            effective_at=datetime.now(UTC),
            limit=3,
        )

    def _clause_directory(self, scope: KnowledgeSearch | dict[str, object]) -> dict[str, object]:
        if isinstance(scope, dict):
            return {
                'policy_clause_directory': [],
                'guidance_status': scope['status'],
                'limitations': scope['limitations'],
            }
        try:
            chunks = self._retriever.list_clauses(scope)
        except KnowledgeRetrievalUnavailable:
            return {
                'policy_clause_directory': [],
                'guidance_status': 'unavailable',
                'limitations': ['Approved knowledge retrieval is temporarily unavailable.'],
            }
        return {
            'policy_clause_directory': [
                {
                    'clause_id': chunk.clause_id,
                    'title': chunk.section_path.partition(' - ')[2],
                }
                for chunk in chunks
            ],
            'guidance_status': 'available' if chunks else 'no_evidence',
            'limitations': [],
        }

    def _v7_knowledge_context(
        self,
        scope: KnowledgeSearch | dict[str, object],
        max_tokens: int,
        clause_ids: Sequence[str],
    ) -> dict[str, object]:
        # The resolver enforces the complete structured-result budget. Never cut
        # a clause: its final sentence can carry an exclusion or schedule condition.
        del max_tokens
        requested = list(dict.fromkeys(clause_ids))
        trace: dict[str, object] = {
            'requested_clause_ids': requested,
            'returned_clause_ids': [],
            'not_found': [],
        }
        if isinstance(scope, dict):
            return {**scope, **trace, 'guidance_status': scope['status']}
        if not requested:
            return {
                **trace,
                'status': 'no_evidence',
                'guidance_status': 'no_clause_selected',
                'chunks': [],
                'limitations': [],
            }
        try:
            chunks = self._retriever.get_clauses(scope, requested)
        except KnowledgeRetrievalUnavailable:
            return {
                **trace,
                'status': 'unavailable',
                'guidance_status': 'unavailable',
                'chunks': [],
                'limitations': ['Approved knowledge retrieval is temporarily unavailable.'],
            }
        returned = [chunk.clause_id for chunk in chunks]
        return {
            'status': 'evidence_found' if chunks else 'no_evidence',
            'guidance_status': 'evidence_found' if chunks else 'no_evidence',
            'requested_clause_ids': requested,
            'returned_clause_ids': returned,
            'not_found': [clause_id for clause_id in requested if clause_id not in returned],
            'chunks': [
                {
                    'document_id': chunk.document_id,
                    'chunk_id': chunk.chunk_id,
                    'title': chunk.title,
                    'section_path': chunk.section_path,
                    'source_uri': chunk.source_uri,
                    'version': chunk.version,
                    'checksum': chunk.checksum,
                    'text': chunk.text,
                }
                for chunk in chunks
            ],
            'limitations': [],
        }

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        if (
            context.runtime_policy is not None
            and context.runtime_policy.instruction.prompt_version == CLAIMANT_V8_PROMPT_ID
        ):
            source_context = context
            scope: KnowledgeSearch | dict[str, object] | None = None

            def turn_scope() -> KnowledgeSearch | dict[str, object]:
                nonlocal scope
                if scope is None:
                    scope = self._knowledge_scope(source_context)
                return scope

            context = replace(
                context,
                knowledge_clause_directory_loader=lambda: self._clause_directory(turn_scope()),
                knowledge_context_loader=lambda max_tokens, clause_ids: self._v7_knowledge_context(
                    turn_scope(),
                    max_tokens,
                    clause_ids,
                ),
            )
        return self._provider.propose_turn(context)
