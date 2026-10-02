"""Read a Claim's whole conversation, across every session it has had."""

from __future__ import annotations

from backend.domain.message import order_messages
from backend.domain.models import MessageRecord, WorkingClaim
from backend.repositories.protocols import PersistenceRepository


def claim_messages(repository: PersistenceRepository, claim: WorkingClaim) -> list[MessageRecord]:
    """Every message on a Claim across its sessions, in conversation order."""

    messages: list[MessageRecord] = []
    for session in repository.list_sessions_for_claim(claim.claim_id, claim.customer_id):
        messages.extend(
            repository.list_messages(claim.claim_id, session.session_id, claim.customer_id)
        )
    return order_messages(messages)
