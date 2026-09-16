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
from backend.domain.models import MessageRecord, MessageVisibility, NeededFor
from backend.services.agent import AgentTurnContext
from backend.services.context_budget import estimate_json_tokens


class ContextBudgetExceeded(ValueError):
    """Raised when authority-critical context cannot fit without truncation."""


def _message_projection(message: MessageRecord) -> dict[str, object]:
    return {'actor': message.actor.value, 'content': message.content}


def _claim_projection(context: AgentTurnContext, route: TurnRoute) -> dict[str, object]:
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
            'source_refs': field.source_refs,
        }
        for code, field in claim.form.items()
        if code in allowed_fields and field.needed_for is NeededFor.CURRENT_ACTION
    }
    return {
        'claim_id': claim.claim_id,
        'revision': claim.revision,
        'product_family': route.product_family,
        'workflow_state': claim.claim_state.workflow_state.value,
        'next_action': claim.claim_state.next_action.value,
        'current_fields': current_fields,
        'contents_items': [item.model_dump(mode='json') for item in claim.contents_items],
        'requirements': (
            {
                'satisfied': branch.requirements.satisfied,
                'missing_required_now': branch.requirements.missing_required_now,
                'next_required_item': branch.requirements.next_required_item,
                'ready': branch.requirements.ready,
            }
            if branch is not None
            else {}
        ),
        'field_value_contracts': {
            item.field_code: {
                'selection_state': item.selection_state.value,
                'value_state': item.value_state.value,
            }
            for item in (branch.field_selection if branch is not None else [])
            if item.selection_state.value not in {'inactive', 'system_owned'}
        },
    }


def _external_service_projection(context: AgentTurnContext, route: TurnRoute) -> list[object]:
    matched: list[object] = []
    requested = {item.casefold() for item in route.capability_ids}
    for service in context.external_services:
        identity = service.service_identity.casefold()
        if requested and not any(capability in identity for capability in requested):
            continue
        matched.append(
            {
                'service_identity': service.service_identity,
                'claimant_purpose': service.purpose,
                'supported_action': service.requested_action,
                'required_consent_scope': list(service.disclosure_fields),
                'current_status': service.operation_status.value,
                'next_allowed_action': service.next_action,
            }
        )
        if len(matched) == 3:
            break
    return matched


def _catalogue(
    context: AgentTurnContext,
    route: TurnRoute,
    summary: VerifiedConversationSummary | None,
) -> tuple[list[ContextCatalogueEntry], bool]:
    claim_scope = f'claim:{context.claim.claim_id}:revision:{context.claim.revision}'
    entries = [
        ContextCatalogueEntry(
            resource_id='claim.current',
            resource_type='claim_projection',
            load_mode=ContextLoadMode.ALWAYS,
            priority=1,
            estimated_tokens=estimate_json_tokens(_claim_projection(context, route)),
            authority_scope=claim_scope,
            cache_segment='claim',
            inline_value=_claim_projection(context, route),
        ),
        ContextCatalogueEntry(
            resource_id='message.latest',
            resource_type='latest_message',
            load_mode=ContextLoadMode.ALWAYS,
            priority=0,
            estimated_tokens=estimate_json_tokens(context.message_text or ''),
            authority_scope=claim_scope,
            inline_value=context.message_text or '',
        ),
    ]
    visible_messages = [
        item
        for item in context.conversation_messages
        if item.visibility is not MessageVisibility.INTERNAL_ONLY
    ]
    recent = visible_messages[-4:]
    if recent:
        recent_value = [_message_projection(item) for item in recent]
        entries.append(
            ContextCatalogueEntry(
                resource_id='conversation.recent',
                resource_type='recent_messages',
                load_mode=ContextLoadMode.AUTO_CANDIDATE,
                priority=3,
                estimated_tokens=estimate_json_tokens(recent_value),
                authority_scope=claim_scope,
                inline_value=recent_value,
            )
        )
    summary_state_mismatch = False
    if summary is not None and summary.claim_revision_at_generation <= context.claim.revision:
        try:
            summary_payload = json.loads(summary.summary)
        except (json.JSONDecodeError, TypeError):
            summary_payload = None
        if isinstance(summary_payload, dict):
            summary_facts = summary_payload.get('confirmed_claim_facts')
            if isinstance(summary_facts, dict):
                summary_state_mismatch = any(
                    code in context.claim.form and context.claim.form[code].value != value
                    for code, value in summary_facts.items()
                )
        if summary_state_mismatch:
            summary = None
    if summary is not None and summary.claim_revision_at_generation <= context.claim.revision:
        entries.append(
            ContextCatalogueEntry(
                resource_id='conversation.summary',
                resource_type='rolling_summary',
                load_mode=ContextLoadMode.COMPACTED,
                priority=4,
                estimated_tokens=estimate_json_tokens(summary.summary),
                authority_scope=claim_scope,
                inline_value={
                    'summary_id': summary.summary_id,
                    'summary': summary.summary,
                    'claim_revision_at_generation': summary.claim_revision_at_generation,
                },
            )
        )
    if len(visible_messages) > len(recent):
        older = visible_messages[: -len(recent)] if recent else visible_messages
        entries.append(
            ContextCatalogueEntry(
                resource_id='conversation.older',
                resource_type='recent_messages',
                load_mode=ContextLoadMode.REFERENCE,
                priority=4,
                estimated_tokens=0,
                authority_scope=claim_scope,
                selectors=['page'],
                inline_value={
                    'first_message_id': older[0].message_id,
                    'last_message_id': older[-1].message_id,
                },
            )
        )
    if context.evidence:
        evidence_value = [
            {'evidence_id': item.evidence_id, 'media_type': item.media_type, 'status': 'submitted'}
            for item in context.evidence
        ]
        entries.append(
            ContextCatalogueEntry(
                resource_id='evidence.current',
                resource_type='evidence',
                load_mode=(
                    ContextLoadMode.ISOLATED
                    if len(context.evidence) > 4
                    or any(item.media_type == 'application/pdf' for item in context.evidence)
                    else ContextLoadMode.EXPLICIT
                ),
                priority=3,
                estimated_tokens=estimate_json_tokens(evidence_value),
                authority_scope=claim_scope,
                selectors=['metadata'] if len(context.evidence) > 4 else [],
                inline_value=evidence_value,
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
                inline_value=None,
            )
        )
    services = _external_service_projection(context, route)
    if services:
        entries.append(
            ContextCatalogueEntry(
                resource_id='external.services',
                resource_type='external_service',
                load_mode=ContextLoadMode.AUTO_CANDIDATE,
                priority=2,
                estimated_tokens=estimate_json_tokens(services),
                authority_scope=claim_scope,
                cache_segment='service-registry',
                inline_value=services,
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
                inline_value=knowledge,
            )
        )
    if 'policy-search' in route.capability_ids and (
        context.policy_context_loader is not None
        or context.knowledge_context_loader is not None
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
                inline_value=None,
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
                load_mode=(
                    ContextLoadMode.ISOLATED if cross_claim else ContextLoadMode.REFERENCE
                ),
                priority=2,
                estimated_tokens=0,
                authority_scope=f'customer:{context.claim.customer_id}',
                selectors=['relevant_claims'],
                inline_value=None,
            )
        )
    return entries, summary_state_mismatch


def plan_context(
    context: AgentTurnContext,
    route: TurnRoute,
    *,
    budget_limit: int,
    reserved_tokens: int,
    summary: VerifiedConversationSummary | None = None,
) -> ContextPlan:
    catalogue, summary_state_mismatch = _catalogue(context, route, summary)
    available = max(0, budget_limit - reserved_tokens)
    used = 0
    inline: dict[str, Any] = {}
    selected: list[str] = []
    references: list[ContextReference] = []
    decisions: list[ContextLoadDecision] = []
    omitted: list[str] = []
    isolated_tasks: list[str] = []

    for entry in sorted(catalogue, key=lambda item: (item.priority, item.resource_id)):
        required = entry.priority <= 2
        fits = used + entry.estimated_tokens <= available
        if entry.load_mode is ContextLoadMode.ISOLATED:
            disposition = ContextDisposition.ISOLATED
        elif entry.load_mode is ContextLoadMode.REFERENCE:
            disposition = ContextDisposition.REFERENCED
        elif entry.load_mode is ContextLoadMode.COMPACTED and fits:
            disposition = ContextDisposition.COMPACTED
            inline[entry.resource_id] = entry.inline_value
            selected.append(entry.resource_id)
            used += entry.estimated_tokens
        elif fits:
            disposition = ContextDisposition.INCLUDED
            inline[entry.resource_id] = entry.inline_value
            selected.append(entry.resource_id)
            used += entry.estimated_tokens
        elif required:
            raise ContextBudgetExceeded(
                f'Authority-critical context {entry.resource_id} exceeds the request budget.'
            )
        elif entry.selectors:
            disposition = ContextDisposition.REFERENCED
        else:
            disposition = ContextDisposition.OMITTED
            omitted.append(entry.resource_id)

        if disposition in {ContextDisposition.REFERENCED, ContextDisposition.ISOLATED}:
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
                max_resolve_tokens=min(600, max(1, available - used)),
            )
            references.append(reference)
            selected.append(entry.resource_id)
            if disposition is ContextDisposition.ISOLATED:
                isolated_tasks.append(entry.resource_id)
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
    if references:
        inline['context_references'] = [item.model_dump(mode='json') for item in references]
    inline['turn_focus'] = {
        'claim_revision': context.claim.revision,
        'route': f'{route.product_family or "unresolved"}:{route.task.value}',
        'current_objective': route.task.value,
        'next_required_item': (
            context.branch_evaluation.requirements.next_required_item
            if context.branch_evaluation is not None
            else None
        ),
        'allowed_field_scope': sorted(
            {
                item.field_code
                for item in (
                    context.branch_evaluation.field_selection
                    if context.branch_evaluation is not None
                    else []
                )
                if item.selection_state.value not in {'inactive', 'system_owned'}
            }
        ),
    }
    return ContextPlan(
        catalogue_entries=catalogue,
        selected_resource_ids=selected,
        inline_context=inline,
        references=references,
        permitted_resolvers=['context.resolve'] if references else [],
        isolated_tasks=isolated_tasks,
        load_decisions=decisions,
        omitted_sections=omitted,
        estimated_tokens=used,
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
