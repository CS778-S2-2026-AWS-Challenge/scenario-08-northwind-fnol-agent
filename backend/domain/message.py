from collections.abc import Sequence
from datetime import datetime
from heapq import heappop, heappush

from backend.domain.models import (
    ActorType,
    EvidenceRecord,
    MessageRecord,
    MessageVisibility,
    SessionRecord,
)

_ACTOR_VISIBILITY = {
    ActorType.CLAIMANT: frozenset({MessageVisibility.CLAIMANT_VISIBLE, MessageVisibility.SHARED}),
    ActorType.AGENT: frozenset({MessageVisibility.CLAIMANT_VISIBLE, MessageVisibility.SHARED}),
    ActorType.STAFF: frozenset(MessageVisibility),
    ActorType.SYSTEM: frozenset(MessageVisibility),
}


class DuplicateClientMessage(ValueError):
    """A claimant retry identity already belongs to another durable Message."""


def message_order_key(message: MessageRecord) -> tuple[datetime, str]:
    """Return the deterministic tie-break key used within the causal order."""

    return message.created_at, message.message_id


def order_messages(messages: Sequence[MessageRecord]) -> list[MessageRecord]:
    """Return a stable total order that always places a reply after its target.

    The persisted ``in_reply_to`` edge is authoritative. Timestamp and identifier
    order only independent messages, so random identifiers cannot invert a
    persisted causal relationship.
    """

    by_id = {message.message_id: message for message in messages}
    children: dict[str, list[MessageRecord]] = {}
    indegree = {message.message_id: 0 for message in messages}
    for message in messages:
        if message.in_reply_to in by_id:
            children.setdefault(message.in_reply_to, []).append(message)
            indegree[message.message_id] += 1

    ordered: list[MessageRecord] = []
    available: list[tuple[datetime, str, MessageRecord]] = []
    for message in messages:
        if indegree[message.message_id] == 0:
            heappush(available, (*message_order_key(message), message))
    while available:
        _, _, message = heappop(available)
        ordered.append(message)
        for reply in children.get(message.message_id, ()):
            indegree[reply.message_id] -= 1
            if indegree[reply.message_id] == 0:
                heappush(available, (*message_order_key(reply), reply))

    # Persisted validation rejects cycles. Keep malformed legacy data visible and
    # deterministic rather than silently dropping it from a read projection.
    ordered_ids = {message.message_id for message in ordered}
    ordered.extend(
        sorted(
            (message for message in messages if message.message_id not in ordered_ids),
            key=message_order_key,
        )
    )
    return ordered


def validate_message_record(
    message: MessageRecord,
    *,
    session: SessionRecord,
    evidence: Sequence[EvidenceRecord],
    reply: MessageRecord | None,
    duplicate_client_message: MessageRecord | None,
) -> None:
    """Validate one Message and its persisted Claim-context associations.

    Args:
        message: Message crossing the persistence boundary.
        session: Authoritative Session named by the Message.
        evidence: Authoritative Evidence records named by the Message.
        reply: Authoritative Message named by ``in_reply_to``, when present.
        duplicate_client_message: Existing Message with the same claimant retry identity.

    Raises:
        ValueError: The Message shape or a cross-record association is invalid.
    """

    if session.session_id != message.session_id or session.claim_id != message.claim_id:
        raise ValueError('Message Claim and Session associations do not match.')
    if not message.content:
        raise ValueError('Message content must not be empty.')
    if message.visibility not in _ACTOR_VISIBILITY[message.actor]:
        raise ValueError('Message actor and visibility are inconsistent.')
    if message.actor is not ActorType.CLAIMANT and message.client_message_id is not None:
        raise ValueError('Only claimant Messages may carry client_message_id.')
    if len(message.evidence_refs) != len(set(message.evidence_refs)):
        raise ValueError('Message evidence_refs must not contain duplicates.')
    evidence_by_id = {item.evidence_id: item for item in evidence}
    if set(message.evidence_refs) != set(evidence_by_id):
        raise ValueError('Message Evidence references must resolve exactly once.')
    if any(item.claim_id != message.claim_id for item in evidence):
        raise ValueError('Message Evidence must belong to the same Claim.')
    if message.in_reply_to == message.message_id:
        raise ValueError('A Message cannot reply to itself.')
    if message.in_reply_to is not None and (
        reply is None
        or reply.claim_id != message.claim_id
        or reply.session_id != message.session_id
    ):
        raise ValueError('Message reply target must belong to the same Claim and Session.')
    if (
        duplicate_client_message is not None
        and duplicate_client_message.message_id != message.message_id
    ):
        raise DuplicateClientMessage(
            'The claimant client_message_id is already used by another Message.'
        )
