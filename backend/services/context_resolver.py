"""Turn-scoped bounded resolver for v7 Context References."""

import json
from collections.abc import Callable
from dataclasses import dataclass

from backend.domain.agent_context_runtime import ContextPlan, ContextReference
from backend.domain.models import MessageVisibility
from backend.domain.realtime import AgentTurnProgressStage
from backend.services.agent import AgentTurnContext
from backend.services.prompt_composer import estimate_tokens


@dataclass(frozen=True, slots=True)
class ResolvedContextChunk:
    ref: str
    selector: str
    content: dict[str, object] | str
    next_cursor: str | None
    truncated: bool
    actual_tokens: int


class TurnContextResolver:
    def __init__(
        self,
        references: list[ContextReference],
        sources: dict[
            tuple[str, str],
            dict[str, object] | str | Callable[[], dict[str, object] | str],
        ],
        *,
        expected_version: str | None = None,
    ) -> None:
        self._references = {item.ref: item for item in references}
        self._sources = dict(sources)
        self._expected_version = expected_version

    def resolve(self, ref: str, selector: str, max_tokens: int) -> ResolvedContextChunk:
        reference = self._references.get(ref)
        if reference is None or selector not in reference.available_selectors:
            raise ValueError('The Context Reference or selector is not permitted for this turn.')
        if self._expected_version is not None and reference.version != self._expected_version:
            raise ValueError('The Context Reference is stale for the current Claim revision.')
        bounded_limit = min(max_tokens, reference.max_resolve_tokens)
        if bounded_limit < 1:
            raise ValueError('A Context Reference resolution requires a positive token limit.')
        try:
            source = self._sources[(ref, selector)]
        except KeyError as error:
            raise ValueError('The requested Context Reference is unavailable.') from error
        value = source() if callable(source) else source
        if isinstance(value, str):
            encoded = value
            max_chars = bounded_limit * 3
            content: dict[str, object] | str = encoded[:max_chars]
            truncated = len(encoded) > max_chars
        else:
            content = value
            truncated = estimate_tokens(str(value)) > bounded_limit
            if truncated:
                raise ValueError('Structured Context Reference content exceeds its bounded result.')
        return ResolvedContextChunk(
            ref=ref,
            selector=selector,
            content=content,
            next_cursor=None,
            truncated=truncated,
            actual_tokens=min(estimate_tokens(str(content)), bounded_limit),
        )


def resolver_for_turn(context: AgentTurnContext, plan: ContextPlan) -> TurnContextResolver:
    sources: dict[
        tuple[str, str],
        dict[str, object] | str | Callable[[], dict[str, object] | str],
    ] = {}
    visible_messages = [
        item
        for item in context.conversation_messages
        if item.visibility is not MessageVisibility.INTERNAL_ONLY
    ]
    older_messages = (
        list(context.older_message_loader(10))
        if context.older_message_loader is not None
        else visible_messages[:-4]
    )
    for reference in plan.references:
        if reference.resource_type == 'message_range':
            sources[(reference.ref, 'page')] = json.dumps(
                [
                    {'actor': item.actor.value, 'content': item.content}
                    for item in older_messages[:10]
                ],
                separators=(',', ':'),
            )
        elif reference.resource_type == 'knowledge_chunk':
            sources[(reference.ref, 'matching_chunks')] = {
                'chunks': [
                    {
                        'document_id': item.document_id,
                        'chunk_id': item.chunk_id,
                        'version': item.version,
                        'text': item.text[:900],
                    }
                    for item in context.knowledge_results[:3]
                ]
            }
        elif reference.resource_type == 'policy_version':

            def load_policy_and_guidance(
                limit: int = reference.max_resolve_tokens,
            ) -> dict[str, object]:
                if context.progress_reporter is not None:
                    context.progress_reporter(
                        AgentTurnProgressStage.KNOWLEDGE_QUERYING,
                        'policy.lookup',
                    )
                result: dict[str, object] = {}
                if context.policy_context_loader is not None:
                    result['policy'] = context.policy_context_loader(limit)
                if context.knowledge_context_loader is not None:
                    result['approved_guidance'] = context.knowledge_context_loader(limit)
                if not result:
                    raise ValueError('The policy Context Reference has no authorised source.')
                return result

            sources[(reference.ref, 'matching_facts_and_guidance')] = load_policy_and_guidance
        elif reference.resource_type == 'claim_history':
            if context.claim_history_context_loader is not None:

                def load_claim_history(
                    limit: int = reference.max_resolve_tokens,
                ) -> dict[str, object]:
                    assert context.claim_history_context_loader is not None
                    return context.claim_history_context_loader(limit)

                sources[(reference.ref, 'relevant_claims')] = load_claim_history
        elif reference.resource_type == 'external_service':
            sources[(reference.ref, 'current')] = {
                'services': [
                    item.model_dump(
                        mode='json',
                        include={
                            'service_identity',
                            'purpose',
                            'operation_status',
                            'result_status',
                            'claimant_meaning',
                            'next_action',
                        },
                    )
                    for item in context.external_services[:3]
                ]
            }
        elif reference.resource_type == 'evidence':
            if 'metadata' in reference.available_selectors:
                sources[(reference.ref, 'metadata')] = {
                    'evidence': [
                        {'evidence_id': item.evidence_id, 'media_type': item.media_type}
                        for item in context.evidence
                    ]
                }
            if (
                'history' in reference.available_selectors
                and context.evidence_history_context_loader is not None
            ):

                def load_evidence_history(
                    limit: int = reference.max_resolve_tokens,
                ) -> dict[str, object]:
                    assert context.evidence_history_context_loader is not None
                    return context.evidence_history_context_loader(limit)

                sources[(reference.ref, 'history')] = load_evidence_history
    return TurnContextResolver(
        plan.references,
        sources,
        expected_version=f'claim-revision-{context.claim.revision}',
    )
