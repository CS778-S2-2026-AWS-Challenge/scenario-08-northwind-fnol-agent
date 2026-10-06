"""Read-only, claimant-safe projections of successfully lodged Claims."""

from calendar import monthrange
from datetime import date, datetime

from pydantic import Field

from backend.domain.models import ContractModel, TemporalFactValue, WorkingClaim


def incident_calendar_date(value: object) -> date | None:
    """Read a single recorded incident day without resolving uncertain ranges.

    Args:
        value: Registered temporal fact value or an ISO date/time string.
    Returns:
        The recorded calendar date, or None when no single date is known.
    Raises:
        None.
    """
    if isinstance(value, TemporalFactValue):
        if value.precision.value in {'range', 'unknown', 'approximate'}:
            return None
        value = value.date
    elif isinstance(value, dict):
        if value.get('precision') in {'range', 'unknown', 'approximate'}:
            return None
        value = value.get('date')
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class LodgedClaimSummary(ContractModel):
    claim_id: str
    claim_number: str | None = None
    product_family: str | None = None
    occurred_at: str | TemporalFactValue | None = None
    lodged_at: datetime
    description: str | None = Field(default=None, max_length=240)
    stated_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class LodgedClaimHistory(ContractModel):
    count_past_12_months: int = Field(ge=0)
    claims: list[LodgedClaimSummary] = Field(max_length=50)
    as_of: datetime
    window_start: datetime


def history_window_start(as_of: datetime) -> datetime:
    """Return the inclusive calendar-year boundary, retaining the supplied timezone.

    Args:
        as_of: Timezone-aware query timestamp.
    Returns:
        The same calendar date last year, with leap day clamped to February 28.
    Raises:
        ValueError: The query timestamp lacks a timezone.
    """
    if as_of.utcoffset() is None:
        raise ValueError('History as_of must include a timezone.')
    return as_of.replace(
        year=as_of.year - 1,
        day=min(as_of.day, monthrange(as_of.year - 1, as_of.month)[1]),
    )


def lodged_claim_summary(claim: WorkingClaim) -> LodgedClaimSummary:
    """Project only lodged identity and supplied incident facts.

    Args:
        claim: A completed Claim with a created external Claim result.
    Returns:
        Bounded history facts without adjudication or internal signals.
    Raises:
        ValueError: The Claim has not successfully been lodged.
    """
    terminal = claim.terminal_disposition
    external = claim.external_claim
    if (
        terminal is None
        or terminal.value.value != 'completed'
        or terminal.reason_code.value != 'CLAIM_CREATED'
        or external is None
        or external.creation_status.value != 'created'
        or not external.external_claim_id
    ):
        raise ValueError('History requires a completed, successfully lodged Claim.')
    facts = {key: field.value for key, field in claim.form.items()}
    return history_summary_from_facts(
        claim_id=claim.claim_id,
        claim_number=external.claim_number,
        product_family=claim.incident_type,
        lodged_at=terminal.recorded_at,
        facts=facts,
    )


def history_summary_from_facts(
    *,
    claim_id: str,
    claim_number: str | None,
    product_family: str | None,
    lodged_at: datetime,
    facts: dict[str, object],
) -> LodgedClaimSummary:
    """Project registered facts, preserving temporal precision and absent amounts.

    Args:
        claim_id: Owned Working Claim identity.
        claim_number: Claim number supplied by the creation result, if present.
        product_family: The stored Claim family.
        lodged_at: The successful creation disposition timestamp.
        facts: Registered form values, never provider payloads.
    Returns:
        An allow-listed summary; missing values stay absent.
    """
    description = facts.get('incident.description')
    amount = facts.get('loss.estimated_amount')
    occurred_at = facts.get('incident.occurred_at')
    if isinstance(occurred_at, dict):
        occurred_at = TemporalFactValue.model_validate(occurred_at)
    return LodgedClaimSummary(
        claim_id=claim_id,
        claim_number=claim_number,
        product_family=product_family,
        occurred_at=(occurred_at if isinstance(occurred_at, str | TemporalFactValue) else None),
        lodged_at=lodged_at,
        description=description[:240] if isinstance(description, str) else None,
        stated_amount=(
            float(amount)
            if isinstance(amount, int | float) and not isinstance(amount, bool)
            else None
        ),
    )
