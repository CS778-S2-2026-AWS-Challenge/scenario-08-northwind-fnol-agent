"""Frozen v3.9: normalization metadata describes an actual value transformation."""

from datetime import UTC, datetime

import pytest

from backend.domain.models import ActorReference, FormSource, FormStatus, ProposedFormChange
from backend.services.fact_resolution import resolve_form_change
from backend.services.turn_proposal_validation import claimant_report_supports_value


@pytest.mark.parametrize(
    'value,normalised',
    [
        ('yesterday afternoon', False),
        ('2026-09-20 afternoon', True),
    ],
)
def test_claimant_temporal_provenance_tracks_actual_normalization(
    value: str,
    normalised: bool,
) -> None:
    quote = 'yesterday afternoon'
    assert claimant_report_supports_value(
        'incident.occurred_at', value, quote, 'My car was hit yesterday afternoon.'
    )
    field = resolve_form_change(
        field_code='incident.occurred_at',
        existing=None,
        proposal=ProposedFormChange(
            field_code='incident.occurred_at',
            value=value,
            reported_text=quote,
            source=FormSource.CLAIMANT,
            status=FormStatus.CONFIRMED,
        ),
        source_ref='msg_time',
        message_text='My car was hit yesterday afternoon.',
        timestamp=datetime(2026, 9, 21, tzinfo=UTC),
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ActorReference(actor_type='agent', actor_id='model_gateway'),
    )
    assert field.normalised is normalised
    assert field.source is FormSource.CLAIMANT
    assert field.status is FormStatus.CONFIRMED
