"""Least-privilege execution for large, read-only Agent context tasks."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

from pydantic import TypeAdapter, ValidationError

from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    IsolatedContextResult,
    IsolatedContextTask,
    ModelRequestBudget,
    PlannedModelTurn,
)
from backend.domain.agent_v7 import V7SourcedSummaryProposal
from backend.domain.ids import new_id
from backend.domain.model_gateway import (
    CLAIMANT_AGENT_PRIVACY_CLASS,
    CLAIMANT_AGENT_PURPOSE,
    ModelCapabilities,
    ModelCompletionStatus,
    ModelEvidenceContent,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTextContent,
)
from backend.services.agent import AgentTurnContext
from backend.services.context_budget import build_request_budget
from backend.services.context_resolver import resolver_for_turn

_SUMMARY_ADAPTER = TypeAdapter(V7SourcedSummaryProposal)
_ISOLATED_INSTRUCTION = (
    'Perform only the bounded read-only review in the supplied task. Return a sourced summary. '
    'Do not propose or perform Claim mutation, consent action, or an external side effect. '
    'Use only the supplied Context Reference IDs in source_refs and state every limitation.'
)


@dataclass(frozen=True, slots=True)
class IsolatedExecutionOutcome:
    task: IsolatedContextTask
    result: IsolatedContextResult
    response: ModelResponse
    request: ModelRequest
    request_budget: ModelRequestBudget
    latency_ms: float


def _task_for_plan(context: AgentTurnContext, plan: PlannedModelTurn) -> IsolatedContextTask:
    if not plan.request_profile.isolated or not plan.context_plan.isolated_tasks:
        raise ValueError('The model plan does not contain an isolated context task.')
    isolated_ids = set(plan.context_plan.isolated_tasks)
    isolated_refs = [
        reference
        for reference in plan.context_plan.references
        if any(reference.ref.endswith(f':{resource_id}') for resource_id in isolated_ids)
    ]
    if not isolated_refs:
        raise ValueError('The isolated context task has no scoped Context Reference.')
    if 'evidence.current' in isolated_ids and any(
        item.media_type == 'application/pdf' for item in context.evidence
    ):
        task_type = 'long_document'
    elif 'evidence.current' in isolated_ids and len(context.evidence) > 4:
        task_type = 'multi_evidence'
    elif 'claim-history.customer' in isolated_ids:
        task_type = 'cross_claim'
    else:
        raise ValueError('The isolated context task type cannot be determined safely.')
    return IsolatedContextTask(
        task_id=new_id('ict'),
        task_type=task_type,
        authority_scope=f'claim:{context.claim.claim_id}:revision:{context.claim.revision}',
        input_refs=isolated_refs,
        permitted_resolvers=['context.resolve'],
        max_input_tokens=plan.request_profile.input_hard_limit,
        max_output_tokens=plan.request_profile.output_limit,
    )


def execute_isolated_context_plan(
    complete: Callable[[ModelRequest], ModelResponse],
    context: AgentTurnContext,
    plan: PlannedModelTurn,
    budget_policy: ContextBudgetPolicy,
) -> IsolatedExecutionOutcome:
    """Resolve scoped inputs server-side and make one mutation-incapable model request."""

    task = _task_for_plan(context, plan)
    resolver = resolver_for_turn(context, plan.context_plan)
    resolved: list[dict[str, object]] = []
    for reference in task.input_refs:
        selector = reference.available_selectors[0]
        chunk = resolver.resolve(reference.ref, selector, reference.max_resolve_tokens)
        resolved.append(
            {
                'ref': chunk.ref,
                'selector': chunk.selector,
                'content': chunk.content,
                'truncated': chunk.truncated,
            }
        )
    payload: dict[str, object] = {
        'task': task.model_dump(mode='json'),
        'resolved_context': resolved,
        'latest_message': context.message_text,
    }
    selected_evidence = (
        context.evidence if task.task_type in {'long_document', 'multi_evidence'} else ()
    )
    user_message = ModelMessage(
        role=ModelRole.USER,
        content_blocks=[
            ModelTextContent(text=json.dumps(payload, separators=(',', ':'), sort_keys=True)),
            *[
                ModelEvidenceContent(evidence_id=item.evidence_id, media_type=item.media_type)
                for item in selected_evidence
            ],
        ],
    )
    request = ModelRequest(
        model_profile_id=context.model_profile_id,
        purpose=CLAIMANT_AGENT_PURPOSE,
        prompt_version='northwind-fnol-claimant-v7',
        privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
        required_capabilities=ModelCapabilities(
            structured_output=True,
            image_input=any(item.media_type.startswith('image/') for item in selected_evidence),
            document_input=any(item.media_type == 'application/pdf' for item in selected_evidence),
        ),
        messages=[
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=f'{plan.system_instruction}\n\n{_ISOLATED_INSTRUCTION}',
            ),
            user_message,
        ],
        response_schema=plan.response_schema,
        max_output_tokens=task.max_output_tokens,
    )
    request_budget = build_request_budget(
        policy=budget_policy,
        profile=plan.request_profile,
        prompt=f'{plan.system_instruction}\n\n{_ISOLATED_INSTRUCTION}',
        schema=plan.response_schema,
        context=payload,
        tools=[],
    )
    started = perf_counter()
    response = complete(request)
    latency_ms = (perf_counter() - started) * 1000
    if response.tool_calls:
        raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
    if response.completion_status is not ModelCompletionStatus.COMPLETE:
        raise ModelGatewayError(ModelGatewayErrorCode.INCOMPLETE_RESPONSE)
    try:
        parsed = _SUMMARY_ADAPTER.validate_python(response.structured_output)
    except ValidationError:
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE) from None
    allowed_refs = {item.ref for item in task.input_refs}
    if not set(parsed.source_refs).issubset(allowed_refs):
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
    result = IsolatedContextResult(
        task_id=task.task_id,
        summary=parsed.summary,
        source_refs=parsed.source_refs,
        source_versions={item.ref: item.version for item in task.input_refs},
        truncated=parsed.truncated or any(bool(item['truncated']) for item in resolved),
        limitations=parsed.limitations,
    )
    return IsolatedExecutionOutcome(
        task=task,
        result=result,
        response=response,
        request=request,
        request_budget=request_budget,
        latency_ms=latency_ms,
    )
