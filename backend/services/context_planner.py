"""Build a bounded, explainable context plan for one claimant turn."""

import json
from datetime import UTC, datetime
from typing import Any

from backend.domain.agent_context_runtime import (
    ContextCatalogueEntry,
    ContextDisposition,
    ContextLoadDecision,
    ContextLoadMode,
    ContextPlan,
    ContextReference,
    TurnRoute,
    VerifiedConversationSummary,
)
from backend.domain.branch_registry import CLAIMANT_HIDDEN_FIELDS
from backend.domain.external_service_registry import ExternalLifecycleStatus
from backend.domain.models import MessageRecord, MessageVisibility, NeededFor
from backend.domain.turn_field_contract import TurnFieldContract
from backend.services.agent import AgentTurnContext
from backend.services.context_budget import estimate_json_tokens


class ContextBudgetExceeded(ValueError):
    """Raised when authority-critical context cannot fit without truncation."""


def _message_projection(message: MessageRecord) -> dict[str, object]:
    return {'actor': message.actor.value, 'content': message.content}


def _claim_projection(
    context: AgentTurnContext,
    route: TurnRoute,
) -> dict[str, object]:
    claim = context.claim
    branch = context.branch_evaluation
    allowed_fields = (
        {
            item.field_code
            for item in branch.field_selection
            if item.selection_state.value not in {'inactive', 'system_owned'}
        }
        if branch is not None
        else set(claim.form)
    )
    current_fields = {
        code: {
            'value': field.value,
            'status': field.status.value,
            'precision': field.precision.value,
        }
        for code, field in claim.form.items()
        if (
            code in allowed_fields
            and code not in CLAIMANT_HIDDEN_FIELDS
            and field.needed_for is NeededFor.CURRENT_ACTION
        )
    }
    projection: dict[str, object] = {
        'claim_id': claim.claim_id,
        'revision': claim.revision,
        'product_family': route.product_family,
        'workflow_state': claim.claim_state.workflow_state.value,
        'next_action': claim.claim_state.next_action.value,
    }
    v8 = (
        context.runtime_policy is not None
        and context.runtime_policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
    )
    optional_sections: dict[str, object] = {
        'handoff_open': bool(getattr(context, 'open_handoffs', ())),
        'safety_interrupt': getattr(getattr(context, 'safety_interrupt', None), 'kind', None),
        'current_fields': current_fields,
        'contents_items': [item.model_dump(mode='json') for item in claim.contents_items],
        # The form as it stands, bucketed by what still needs the claimant, what
        # is awaiting someone else, and what is settled. The model reads this and
        # decides what to do; Runtime does not pre-select a next question.
        'requirements': (
            {
                'unresolved': branch.requirements.unresolved,
                'ready': branch.requirements.ready,
            }
            if branch is not None
            else None
        ),
        'last_question': getattr(context, 'last_question', None),
        'remaining_questions': getattr(context, 'remaining_questions', None),
        'documents': list(getattr(context, 'documents', ())),
        # Files received this turn that this provider cannot open. They are
        # saved for the claims team; the model acknowledges them by kind.
        'received_but_unreadable': [
            {'evidence_id': item.evidence_id, 'media_type': item.media_type}
            for item in getattr(context, 'unattached_evidence', ())
        ],
    }
    if v8:
        optional_sections['eligible_services'] = _external_service_projection(context, route)
    projection.update({key: value for key, value in optional_sections.items() if value})
    return projection


def _external_service_projection(context: AgentTurnContext, route: TurnRoute) -> list[object]:
    if getattr(context, 'open_handoffs', ()):
        return []
    v8 = (
        context.runtime_policy is not None
        and context.runtime_policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
    )
    if not v8 and route.task.value in {'evidence_current', 'evidence_history'}:
        return []
    matched: list[object] = []
    eligible_ids = getattr(context, 'eligible_service_ids', None)
    for service in context.external_services:
        if v8 and service.operation_status is not ExternalLifecycleStatus.CONSENT_REQUIRED:
            continue
        if not v8 and eligible_ids is not None and service.service_identity not in eligible_ids:
            continue
        if (
            not v8
            and context.selected_external_service_ids
            and service.service_identity not in context.selected_external_service_ids
        ):
            continue
        matched.append(
            {
                'service_identity': service.service_identity,
                'claimant_purpose': service.purpose,
            }
        )
    return matched if v8 else matched[:3]


def _catalogue(
    context: AgentTurnContext,
    route: TurnRoute,
    summary: VerifiedConversationSummary | None,
) -> tuple[list[ContextCatalogueEntry], dict[str, object], bool]:
    claim_scope = f'claim:{context.claim.claim_id}:revision:{context.claim.revision}'
    values: dict[str, object] = {
        'claim.current': _claim_projection(context, route),
        'message.latest': context.message_text or '',
    }
    entries = [
        ContextCatalogueEntry(
            resource_id='claim.current',
            resource_type='claim_projection',
            load_mode=ContextLoadMode.ALWAYS,
            priority=1,
            estimated_tokens=estimate_json_tokens(_claim_projection(context, route)),
            authority_scope=claim_scope,
            cache_segment='claim',
        ),
        ContextCatalogueEntry(
            resource_id='message.latest',
            resource_type='latest_message',
            load_mode=ContextLoadMode.ALWAYS,
            priority=0,
            estimated_tokens=estimate_json_tokens(context.message_text or ''),
            authority_scope=claim_scope,
        ),
    ]
    visible_messages = [
        item
        for item in context.conversation_messages
        if item.visibility is not MessageVisibility.INTERNAL_ONLY
        and item.message_id != context.trigger_message_id
    ]
    recent = visible_messages[-4:]
    if recent:
        recent_value = [_message_projection(item) for item in recent]
        values['conversation.recent'] = recent_value
        entries.append(
            ContextCatalogueEntry(
                resource_id='conversation.recent',
                resource_type='recent_messages',
                load_mode=ContextLoadMode.ROUTE_MATCH,
                priority=3,
                estimated_tokens=estimate_json_tokens(recent_value),
                authority_scope=claim_scope,
            )
        )
    summary_state_mismatch = False
    if summary is not None and (
        summary.claim_id != context.claim.claim_id
        or summary.session_id != context.session_id
        or summary.verified_against_claim_revision != summary.claim_revision_at_generation
        or summary.verified_against_claim_revision > context.claim.revision
    ):
        summary_state_mismatch = True
        summary = None
    if summary is not None and summary.claim_revision_at_generation <= context.claim.revision:
        try:
            summary_payload = json.loads(summary.summary)
        except (json.JSONDecodeError, TypeError):
            summary_payload = None
        if isinstance(summary_payload, dict):
            summary_facts = summary_payload.get('confirmed_claim_facts')
            if isinstance(summary_facts, dict):
                summary_state_mismatch = any(
                    code not in context.claim.form or context.claim.form[code].value != value
                    for code, value in summary_facts.items()
                )
        if summary_state_mismatch:
            summary = None
    if summary is not None and summary.claim_revision_at_generation <= context.claim.revision:
        values['conversation.summary'] = {
            'summary_id': summary.summary_id,
            'summary': summary.summary,
            'claim_revision_at_generation': summary.claim_revision_at_generation,
        }
        entries.append(
            ContextCatalogueEntry(
                resource_id='conversation.summary',
                resource_type='rolling_summary',
                load_mode=ContextLoadMode.COMPACTED,
                priority=4,
                estimated_tokens=estimate_json_tokens(summary.summary),
                authority_scope=claim_scope,
            )
        )
    if len(visible_messages) > len(recent):
        entries.append(
            ContextCatalogueEntry(
                resource_id='conversation.older',
                resource_type='recent_messages',
                load_mode=ContextLoadMode.REFERENCE,
                priority=4,
                estimated_tokens=0,
                authority_scope=claim_scope,
                selectors=['page'],
            )
        )
    if context.evidence:
        isolated_evidence = len(context.evidence) > 4 or any(
            item.media_type == 'application/pdf' for item in context.evidence
        )
        evidence_value = [
            {'evidence_id': item.evidence_id, 'media_type': item.media_type, 'status': 'submitted'}
            for item in context.evidence
        ]
        values['evidence.current'] = evidence_value
        entries.append(
            ContextCatalogueEntry(
                resource_id='evidence.current',
                resource_type='evidence',
                load_mode=(
                    ContextLoadMode.ISOLATED if isolated_evidence else ContextLoadMode.EXPLICIT
                ),
                priority=3,
                estimated_tokens=estimate_json_tokens(evidence_value),
                authority_scope=claim_scope,
                selectors=['metadata'] if isolated_evidence else [],
            )
        )
    if (
        route.task.value == 'evidence_history'
        and context.evidence_history_context_loader is not None
    ):
        entries.append(
            ContextCatalogueEntry(
                resource_id='evidence.history',
                resource_type='evidence',
                load_mode=ContextLoadMode.REFERENCE,
                priority=2,
                estimated_tokens=0,
                authority_scope=f'customer:{context.claim.customer_id}',
                selectors=['history'],
            )
        )
    services = _external_service_projection(context, route)
    # v8 includes the complete eligible set in claim.current.  Do not pay for a
    # second copy of the same catalogue in a separate context section.
    v8 = (
        context.runtime_policy is not None
        and context.runtime_policy.instruction.prompt_version == 'northwind-fnol-claimant-v8'
    )
    if services and not v8:
        values['external.services'] = services
        entries.append(
            ContextCatalogueEntry(
                resource_id='external.services',
                resource_type='external_service',
                load_mode=ContextLoadMode.ROUTE_MATCH,
                priority=2,
                estimated_tokens=estimate_json_tokens(services),
                authority_scope=claim_scope,
                cache_segment='service-registry',
            )
        )
    if context.knowledge_results:
        knowledge = [
            {
                'document_id': item.document_id,
                'chunk_id': item.chunk_id,
                'title': item.title,
                'version': item.version,
                'text': item.text[:1200],
            }
            for item in context.knowledge_results[:3]
        ]
        entries.append(
            ContextCatalogueEntry(
                resource_id='knowledge.results',
                resource_type='knowledge',
                load_mode=ContextLoadMode.REFERENCE,
                priority=4,
                estimated_tokens=estimate_json_tokens(knowledge),
                authority_scope=claim_scope,
                selectors=['matching_chunks'],
            )
        )
    if 'policy-search' in route.capability_ids and (
        context.policy_context_loader is not None or context.knowledge_context_loader is not None
    ):
        entries.append(
            ContextCatalogueEntry(
                resource_id='policy.current',
                resource_type='policy',
                load_mode=ContextLoadMode.REFERENCE,
                priority=2,
                estimated_tokens=0,
                authority_scope=claim_scope,
                selectors=['matching_facts_and_guidance'],
            )
        )
    if 'claim-history' in route.capability_ids and (
        context.claim_history_context_loader is not None
    ):
        cross_claim = any(
            term in (context.message_text or '').casefold()
            for term in ('compare', 'across claims', 'all claims', 'multiple claims')
        )
        entries.append(
            ContextCatalogueEntry(
                resource_id='claim-history.customer',
                resource_type='claim_history',
                load_mode=(ContextLoadMode.ISOLATED if cross_claim else ContextLoadMode.REFERENCE),
                priority=2,
                estimated_tokens=0,
                authority_scope=f'customer:{context.claim.customer_id}',
                selectors=['relevant_claims'],
            )
        )
    return entries, values, summary_state_mismatch


def plan_context(
    context: AgentTurnContext,
    route: TurnRoute,
    *,
    budget_limit: int,
    reserved_tokens: int,
    summary: VerifiedConversationSummary | None = None,
    field_contract: TurnFieldContract | None = None,
) -> ContextPlan:
    catalogue, resource_values, summary_state_mismatch = _catalogue(context, route, summary)
    available = max(0, budget_limit - reserved_tokens)
    turn_focus = {
        'claim_revision': context.claim.revision,
        'route': f'{route.product_family or "unresolved"}:{route.task.value}',
        'current_objective': route.task.value,
        'next_required_item': (
            context.branch_evaluation.requirements.next_required_item
            if context.branch_evaluation is not None
            else None
        ),
    }
    inline: dict[str, Any] = {'turn_focus': turn_focus}
    selected: list[str] = []
    references: list[ContextReference] = []
    decisions: list[ContextLoadDecision] = []
    omitted: list[str] = []
    isolated_tasks: list[str] = []

    if estimate_json_tokens(inline) > available:
        raise ContextBudgetExceeded('The authority-critical Turn Focus exceeds the request budget.')

    for entry in sorted(catalogue, key=lambda item: (item.priority, item.resource_id)):
        required = entry.priority <= 2
        disposition: ContextDisposition
        wants_reference = entry.load_mode in {
            ContextLoadMode.REFERENCE,
            ContextLoadMode.ISOLATED,
        }
        value = resource_values.get(entry.resource_id)
        if not wants_reference and value is not None:
            candidate_inline = {**inline, entry.resource_id: value}
            if estimate_json_tokens(candidate_inline) <= available:
                disposition = (
                    ContextDisposition.COMPACTED
                    if entry.load_mode is ContextLoadMode.COMPACTED
                    else ContextDisposition.INCLUDED
                )
                inline = candidate_inline
                selected.append(entry.resource_id)
            elif entry.selectors:
                wants_reference = True
            elif required:
                raise ContextBudgetExceeded(
                    f'Authority-critical context {entry.resource_id} exceeds the request budget.'
                )
            else:
                disposition = ContextDisposition.OMITTED
                omitted.append(entry.resource_id)
        elif not wants_reference:
            if required:
                raise ContextBudgetExceeded(
                    f'Authority-critical context {entry.resource_id} is unavailable.'
                )
            disposition = ContextDisposition.OMITTED
            omitted.append(entry.resource_id)

        if wants_reference:
            resource_type = {
                'recent_messages': 'message_range',
                'knowledge': 'knowledge_chunk',
                'evidence': 'evidence',
                'claim_history': 'claim_history',
                'policy': 'policy_version',
                'external_service': 'external_service',
            }.get(entry.resource_type)
            if resource_type is None:
                raise ValueError(f'{entry.resource_type} cannot be exposed as a Context Reference.')
            reference = ContextReference(
                ref=f'ctxref:{context.session_id}:{entry.resource_id}',
                resource_type=resource_type,
                version=f'claim-revision-{context.claim.revision}',
                summary=f'Bounded {entry.resource_id} context is available on demand.',
                available_selectors=entry.selectors or ['current'],
                max_resolve_tokens=min(
                    600,
                    max(1, available - estimate_json_tokens(inline)),
                ),
            )
            candidate_references = [*references, reference]
            candidate_inline = {
                **inline,
                'context_references': [
                    item.model_dump(mode='json') for item in candidate_references
                ],
            }
            if estimate_json_tokens(candidate_inline) <= available:
                disposition = (
                    ContextDisposition.ISOLATED
                    if entry.load_mode is ContextLoadMode.ISOLATED
                    else ContextDisposition.REFERENCED
                )
                references = candidate_references
                inline = candidate_inline
                selected.append(entry.resource_id)
                if disposition is ContextDisposition.ISOLATED:
                    isolated_tasks.append(entry.resource_id)
            elif required:
                raise ContextBudgetExceeded(
                    f'Authority-critical reference {entry.resource_id} exceeds the request budget.'
                )
            else:
                disposition = ContextDisposition.OMITTED
                omitted.append(entry.resource_id)
        decisions.append(
            ContextLoadDecision(
                resource_id=entry.resource_id,
                load_mode=entry.load_mode,
                selection_reason=(
                    'Required for authoritative route execution.'
                    if required
                    else 'Selected within the remaining route budget.'
                    if disposition is ContextDisposition.INCLUDED
                    else 'Exposed as a bounded reference instead of inline content.'
                    if disposition is ContextDisposition.REFERENCED
                    else 'Included as a verified compacted representation.'
                    if disposition is ContextDisposition.COMPACTED
                    else 'Selected for isolated read-only execution.'
                    if disposition is ContextDisposition.ISOLATED
                    else 'Omitted after lower-priority budget exhaustion.'
                ),
                disposition=disposition,
                estimated_tokens=entry.estimated_tokens,
                authority_scope=entry.authority_scope,
                cache_segment=entry.cache_segment,
            )
        )
    return ContextPlan(
        catalogue_entries=catalogue,
        selected_resource_ids=selected,
        inline_context=inline,
        references=references,
        permitted_resolvers=['context.resolve'] if references else [],
        isolated_tasks=isolated_tasks,
        load_decisions=decisions,
        omitted_sections=omitted,
        estimated_tokens=estimate_json_tokens(inline),
        budget_limit=budget_limit,
        summary_state_mismatch=summary_state_mismatch,
    )


def build_verified_summary(
    context: AgentTurnContext,
    message_ids: list[str],
    summary: str,
) -> VerifiedConversationSummary:
    if not message_ids:
        raise ValueError('A verified summary requires source messages.')
    timestamp = datetime.now(UTC).isoformat()
    return VerifiedConversationSummary(
        summary_id=f'summary:{context.session_id}:{context.claim.revision}',
        claim_id=context.claim.claim_id,
        session_id=context.session_id,
        source_message_ids=message_ids,
        covered_message_range=f'{message_ids[0]}..{message_ids[-1]}',
        generator_profile_and_version='deterministic-claim-projection@v1',
        claim_revision_at_generation=context.claim.revision,
        summary=summary,
        verified_against_claim_revision=context.claim.revision,
        created_at=timestamp,
    )
