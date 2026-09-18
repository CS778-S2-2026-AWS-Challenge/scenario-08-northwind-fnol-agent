"""Compose one fully validated v7 model turn before transport."""

import json

from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    PlannedModelTurn,
    VerifiedConversationSummary,
)
from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.configuration import ModelRuntimeConfiguration
from backend.domain.model_gateway import ModelTool
from backend.domain.prompt_pack import PromptPackManifest
from backend.services.agent import AgentTurnContext
from backend.services.cache_planner import build_cache_plan
from backend.services.context_budget import build_request_budget, estimate_json_tokens
from backend.services.context_planner import plan_context
from backend.services.prompt_composer import compose_prompt, load_response_schema
from backend.services.provider_capability_registry import (
    provider_capability,
    validate_capability_binding,
    validate_profile_compatibility,
)
from backend.services.request_profile_registry import request_profile_for_task
from backend.services.turn_field_contract import bind_provider_schema, compile_turn_field_contract
from backend.services.turn_router import route_turn

_CONTEXT_RESOLVE_TOOL = ModelTool(
    name='context.resolve',
    description='Resolve one turn-scoped bounded Context Reference.',
    input_schema={
        'type': 'object',
        'additionalProperties': False,
        'required': ['ref', 'selector', 'max_tokens'],
        'properties': {
            'ref': {'type': 'string'},
            'selector': {'type': 'string'},
            'max_tokens': {'type': 'integer', 'minimum': 1, 'maximum': 600},
        },
    },
)


def context_resolve_tool() -> ModelTool:
    """Return the single published lookup tool used for planning and transport."""

    return _CONTEXT_RESOLVE_TOOL


def plan_model_turn(
    context: AgentTurnContext,
    *,
    budget_policy: ContextBudgetPolicy | None = None,
    summary: VerifiedConversationSummary | None = None,
) -> PlannedModelTurn | None:
    route = route_turn(context)
    if not route.model_required:
        return None
    if context.runtime_configuration_snapshot is None:
        raise ValueError('A v7 model turn requires one active Runtime configuration snapshot.')
    model_record = context.runtime_configuration_snapshot.model(context.model_profile_id)
    if model_record is None:
        raise ValueError('The selected model profile is absent from the Runtime snapshot.')
    model_configuration = ModelRuntimeConfiguration.model_validate(model_record.values)
    cross_claim_review = (
        'claim-history' in route.capability_ids
        and context.claim_history_context_loader is not None
        and any(
            term in (context.message_text or '').casefold()
            for term in ('compare', 'across claims', 'all claims', 'multiple claims')
        )
    )
    isolated_evidence_review = len(context.evidence) > 4 or any(
        item.media_type == 'application/pdf' for item in context.evidence
    )
    isolated_review = isolated_evidence_review or cross_claim_review
    runtime_policy = context.runtime_policy
    published_profiles = (
        runtime_policy.tool_policy.request_profiles
        if runtime_policy is not None
        and runtime_policy.instruction.composition_mode == 'fragmented'
        else None
    )
    profile = request_profile_for_task(
        route.task,
        has_current_media=bool(context.evidence),
        isolated_review=isolated_review,
        needs_lookup=(
            route.task is not None
            and (
                (
                    bool({'policy-search', 'claim-history'} & set(route.capability_ids))
                    and (
                        context.policy_context_loader is not None
                        or context.knowledge_context_loader is not None
                        or context.claim_history_context_loader is not None
                    )
                )
                or (
                    route.task.value == 'status_question' and len(context.conversation_messages) > 4
                )
            )
        ),
        profiles=published_profiles,
    )
    capability = (
        runtime_policy.tool_policy.provider_capabilities[context.model_profile_id]
        if runtime_policy is not None
        and runtime_policy.instruction.composition_mode == 'fragmented'
        else provider_capability(model_configuration)
    )
    validate_capability_binding(model_configuration, capability)
    validate_profile_compatibility(profile, capability)
    selected_media = () if cross_claim_review else context.evidence
    for evidence in selected_media:
        required_type = (
            'image/*' if evidence.media_type.startswith('image/') else evidence.media_type
        )
        if required_type not in capability.supported_media_types:
            raise ValueError('The selected provider cannot consume the attached Evidence type.')

    field_contract = None
    if runtime_policy is not None and runtime_policy.instruction.composition_mode == 'fragmented':
        instruction = runtime_policy.instruction
        assert instruction.manifest_version is not None
        manifest = PromptPackManifest(
            prompt_pack_version=instruction.manifest_version,
            fragments=list(instruction.fragments),
        )
        bundle = compose_prompt(
            route,
            manifest,
            {item.fragment_id: item.content for item in instruction.fragments},
        )
        try:
            schema = runtime_policy.tool_policy.schema_registry[profile.schema_id]
        except KeyError as error:
            raise ValueError(
                'The selected schema is absent from the published registry.'
            ) from error
    else:
        bundle = compose_prompt(route)
        schema = load_response_schema(profile.schema_id)
    if profile.schema_id == 'claimant.intake-patch.v1':
        branch_evaluator = (
            runtime_policy.branch_evaluator()
            if runtime_policy is not None
            else BranchRuleEvaluator()
        )
        branch_evaluation = context.branch_evaluation or branch_evaluator.evaluate(
            context.claim,
            latest_message=context.message_text,
            recomputation_reason='model_turn_contract',
        )
        field_contract = compile_turn_field_contract(
            branch_evaluation,
            branch_evaluator.registry,
        )
        schema = bind_provider_schema(schema, field_contract)
    schema = json.loads(json.dumps(schema, separators=(',', ':'), sort_keys=True))
    tools: list[dict[str, object]] = (
        [context_resolve_tool().model_dump(mode='json')] if profile.tool_names else []
    )
    policy = (
        budget_policy
        or (
            runtime_policy.controlled_rules.context_budget_policy
            if runtime_policy is not None
            else None
        )
        or ContextBudgetPolicy()
    )
    reserved = (
        bundle.estimated_tokens
        + estimate_json_tokens(schema)
        + (estimate_json_tokens(tools) if tools else 0)
        + 32
    )
    context_plan = plan_context(
        context,
        route,
        budget_limit=(
            profile.input_hard_limit
            if profile.isolated
            else min(profile.input_hard_limit, policy.ordinary_input_hard_limit)
        ),
        reserved_tokens=reserved,
        summary=summary or context.rolling_summary,
        field_contract=field_contract,
    )
    recent_history_tokens = next(
        (
            item.estimated_tokens
            for item in context_plan.catalogue_entries
            if item.resource_id == 'conversation.recent'
            and item.resource_id in context_plan.inline_context
        ),
        0,
    )
    retrieved_tokens = sum(
        item.estimated_tokens
        for item in context_plan.catalogue_entries
        if item.resource_type in {'knowledge', 'policy', 'claim_history'}
        and item.resource_id in context_plan.inline_context
    )
    budget = build_request_budget(
        policy=policy,
        profile=profile,
        prompt=bundle.compiled_instruction,
        schema=schema,
        context=context_plan.inline_context,
        tools=tools,
        recent_history_tokens=recent_history_tokens,
        retrieved_context_tokens=retrieved_tokens,
    )
    snapshot = context.runtime_configuration_snapshot
    cache_plan = build_cache_plan(
        release_set_id=snapshot.release_set_id or 'unpublished',
        model_profile_id=context.model_profile_id,
        claim_revision=context.claim.revision,
        principal_scope=f'customer:{context.claim.customer_id}',
        bundle=bundle,
        request_profile=profile,
        schema_id=profile.schema_id,
        schema=schema,
        tools=tools,
        context_plan=context_plan,
        layout_version=(
            runtime_policy.features.cache_layout_version
            if runtime_policy is not None and runtime_policy.features.cache_layout_version
            else 'northwind-cache-layout-v1'
        ),
    )
    return PlannedModelTurn(
        route=route,
        request_profile=profile,
        provider_capability=capability,
        prompt_bundle_id=bundle.prompt_bundle_id,
        fragment_refs=[f'{item.fragment_id}@{item.version}' for item in bundle.fragment_refs],
        schema_id=profile.schema_id,
        context_plan=context_plan,
        request_budget=budget,
        cache_plan=cache_plan,
        system_instruction=bundle.compiled_instruction,
        context_payload=context_plan.inline_context,
        response_schema=schema,
        field_contract=field_contract,
    )
