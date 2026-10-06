"""Server-owned history checks captured before a Claim-creation reservation."""

from datetime import date, datetime

from backend.domain.claim_creation import ClaimHistoryChecks
from backend.domain.claim_history import incident_calendar_date
from backend.domain.models import FormStatus, WorkingClaim
from backend.repositories.protocols import PersistenceRepository


def _incident_date(claim: WorkingClaim) -> date | None:
    field = claim.form.get('incident.occurred_at')
    if field is None or field.status is not FormStatus.CONFIRMED:
        return None
    return incident_calendar_date(field.value)


def check_lodging_history(
    repository: PersistenceRepository, claim: WorkingClaim, *, as_of: datetime
) -> ClaimHistoryChecks:
    """Evaluate the controlled prior-count and possible-duplicate rules without a model.

    Args:
        repository: The selected business repository, never a fallback profile.
        claim: The authorised current Claim, excluded from both reads.
        as_of: The reservation timestamp defining the rolling calendar-year window.
    Returns:
        Staff-only observations; an unavailable read is explicitly not checked.
    """
    checks = ClaimHistoryChecks(
        checked_at=as_of, prior_claims_12m='not_checked', possible_duplicate='not_checked'
    )
    # This is an isolation boundary: a history dependency failure is an explicit
    # staff limitation, not a reason to lose a safe report or to label it clear.
    try:
        history = repository.query_lodged_claim_history(
            claim.customer_id, claim.claim_id, as_of=as_of, limit=1
        )
    except Exception:
        checks.limitations.append('Claim history count was unavailable at lodging.')
    else:
        checks.count_past_12_months = history.count_past_12_months
        checks.prior_claims_12m = 'hit' if history.count_past_12_months >= 2 else 'clear'
    incident_date = _incident_date(claim)
    if incident_date is None or claim.incident_type is None:
        checks.limitations.append('Duplicate checking requires a confirmed single incident date.')
        return checks
    try:
        matches = repository.find_duplicate_lodged_claim_ids(
            claim.customer_id,
            claim.claim_id,
            product_family=claim.incident_type,
            incident_date=incident_date,
            as_of=as_of,
        )
    except Exception:
        checks.limitations.append('Duplicate history checking was unavailable at lodging.')
    else:
        checks.duplicate_claim_ids = matches
        checks.possible_duplicate = 'hit' if matches else 'clear'
    return checks
