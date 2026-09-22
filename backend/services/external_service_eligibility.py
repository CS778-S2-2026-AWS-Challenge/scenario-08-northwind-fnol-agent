"""Runtime eligibility, including consent cooldown and handoff precedence."""

from backend.domain.external_service_registry import (
    ExternalLifecycleStatus,
    ExternalServiceLifecycleProjection,
)
from backend.domain.models import ActorType, MessageRecord, WorkingClaim
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent_external_lifecycle import build_agent_external_lifecycle_context
from backend.services.external_service_offers import detected_service_intents


def eligible_service_ids(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    family: str | None,
    recent_turns: tuple[MessageRecord, ...],
    *,
    current_text: str = '',
    lifecycle: tuple[ExternalServiceLifecycleProjection, ...] | None = None,
) -> frozenset[str]:
    if family is None or any(
        item.status.value not in {'resolved', 'cancelled'}
        for item in repository.list_handoffs(claim.claim_id, claim.customer_id)
    ):
        return frozenset()
    available = {
        item.service_identity
        for item in (
            lifecycle
            if lifecycle is not None
            else build_agent_external_lifecycle_context(
                repository, claim.claim_id, claim.assessor_routing, family
            )
        )
        if item.operation_status is ExternalLifecycleStatus.CONSENT_REQUIRED
    }
    renewed = {
        item['service_identity']
        for item in detected_service_intents(current_text, [], product_family=family)
    }
    for consent in claim.external_service_consents:
        if consent.status.value == 'granted':
            # The claimant already said yes. The lifecycle projection normally
            # reflects that (a dispatched task moves off CONSENT_REQUIRED), but a
            # service can still surface here through the CONSENT_REQUIRED
            # fallback for identities with no task yet -- dispatch pending,
            # skipped in this deployment, or a prior attempt whose failure was
            # swallowed. Re-offering an already-granted permission is never
            # correct; only an explicit fresh request reopens it.
            if consent.service_identity not in renewed:
                available.discard(consent.service_identity)
            continue
        if consent.status.value not in {'declined', 'withdrawn'}:
            continue
        decided_at = consent.withdrawn_at or consent.granted_at
        elapsed_turns = sum(
            item.actor is ActorType.CLAIMANT and item.created_at > decided_at
            for item in recent_turns
        )
        if elapsed_turns < 3 and consent.service_identity not in renewed:
            available.discard(consent.service_identity)
    return frozenset(available)
