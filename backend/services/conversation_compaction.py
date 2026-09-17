"""Post-response verified conversation compaction for Agent Context Runtime v7."""

import json
import logging
from datetime import UTC, datetime

from backend.domain.agent_context_runtime import VerifiedConversationSummary
from backend.domain.models import FormStatus, MessageRecord, MessageVisibility, WorkingClaim
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository
from backend.services.context_budget import estimate_json_tokens
from backend.services.runtime_agent_policy import RuntimeAgentPolicyResolver
from backend.services.runtime_configuration import RuntimeConfigurationResolutionError

logger = logging.getLogger(__name__)

RECENT_RAW_TURNS = 4
COMPACTION_THRESHOLD_TOKENS = 900
MAX_REPORTED_EXCERPTS = 8


def _visible_messages(messages: list[MessageRecord]) -> list[MessageRecord]:
    return [item for item in messages if item.visibility is not MessageVisibility.INTERNAL_ONLY]


def _message_text(message: MessageRecord) -> str:
    content = message.content
    text = content.get('text') if isinstance(content, dict) else None
    if isinstance(text, str):
        return text
    return json.dumps(content, separators=(',', ':'), sort_keys=True)


def _summary_text(claim: WorkingClaim, covered: list[MessageRecord]) -> str:
    confirmed_facts = {
        field_code: field.value
        for field_code, field in sorted(claim.form.items())
        if field.status is FormStatus.CONFIRMED
    }
    excerpts = [
        {
            'message_id': item.message_id,
            'actor': item.actor.value,
            'reported_text': _message_text(item)[:320],
            'authority': 'reported_history_only',
        }
        for item in covered[-MAX_REPORTED_EXCERPTS:]
    ]
    payload = {
        'authority': (
            'Authoritative Claim State takes precedence. Reported history is not a confirmed fact.'
        ),
        'claim_revision': claim.revision,
        'confirmed_claim_facts': confirmed_facts,
        'covered_message_count': len(covered),
        'recent_reported_history': excerpts,
        'older_wording': (
            'Resolve the bounded message_range reference when exact wording is needed.'
        ),
    }
    encoded = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    if len(encoded) <= 5000:
        return encoded
    payload['recent_reported_history'] = excerpts[-2:]
    encoded = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    return encoded[:5000]


def compact_conversation(
    repository: PersistenceRepository,
    customer_id: str,
    claim_id: str,
    session_id: str,
) -> VerifiedConversationSummary | None:
    """Create an immutable summary only when older raw history crosses the token threshold."""

    claim = repository.get_claim(claim_id, customer_id)
    if claim is None or repository.get_session(claim_id, session_id, customer_id) is None:
        return None
    messages = _visible_messages(repository.list_messages(claim_id, session_id, customer_id))
    covered = messages[:-RECENT_RAW_TURNS]
    if not covered:
        return None
    existing = repository.get_latest_conversation_summary(claim_id, session_id, customer_id)
    last_covered_id = covered[-1].message_id
    if existing is not None and existing.covered_message_range.endswith(f'..{last_covered_id}'):
        return existing
    if estimate_json_tokens([item.content for item in covered]) < COMPACTION_THRESHOLD_TOKENS:
        return existing
    source_ids = [item.message_id for item in covered]
    summary = VerifiedConversationSummary(
        summary_id=f'summary:{session_id}:{last_covered_id}',
        claim_id=claim_id,
        session_id=session_id,
        source_message_ids=source_ids,
        covered_message_range=f'{source_ids[0]}..{source_ids[-1]}',
        generator_profile_and_version='deterministic-verified-compactor@v1',
        claim_revision_at_generation=claim.revision,
        summary=_summary_text(claim, covered),
        verified_against_claim_revision=claim.revision,
        created_at=datetime.now(UTC).isoformat(),
    )
    repository.save_conversation_summary(summary, customer_id)
    return summary


def compact_conversation_after_response(
    repository: PersistenceRepository,
    customer_id: str,
    claim_id: str,
    session_id: str,
) -> None:
    """Best-effort background boundary; failure preserves messages and prior summaries."""

    try:
        compact_conversation(repository, customer_id, claim_id, session_id)
    except (IdempotencyConflict, KeyError, ValueError, RuntimeError):
        logger.exception(
            'conversation_compaction.failed',
            extra={'claim_id': claim_id, 'session_id': session_id},
        )


def compact_conversation_after_response_if_enabled(
    repository: PersistenceRepository,
    policy_resolver: RuntimeAgentPolicyResolver,
    customer_id: str,
    claim_id: str,
    session_id: str,
) -> None:
    """Compact only for a release that explicitly enables verified summaries."""

    try:
        policy = policy_resolver.resolve_for_turn()
    except RuntimeConfigurationResolutionError:
        logger.exception(
            'conversation_compaction.policy_unavailable',
            extra={'claim_id': claim_id, 'session_id': session_id},
        )
        return
    if policy is None or not policy.features.verified_rolling_summary:
        return
    compact_conversation_after_response(repository, customer_id, claim_id, session_id)
