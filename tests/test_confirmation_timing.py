from datetime import UTC, datetime

from backend.domain.models import (
    ConfirmationRequestRecord,
    CustomerNextStep,
    FormSource,
    FormStatus,
    StructuredFormField,
    WorkingClaim,
)
from backend.services.turn_reducer import can_confirm, shown_values_fingerprint


def _confirmation() -> tuple[
    WorkingClaim, dict[str, StructuredFormField], ConfirmationRequestRecord
]:
    field = StructuredFormField(
        value='Symonds Street',
        source=FormSource.INFERENCE,
        status=FormStatus.PROPOSED,
        source_refs=['message:original'],
        needed_for='current_action',
        updated_at=datetime.now(UTC),
        updated_by={'actor_type': 'agent', 'actor_id': 'model'},
    )
    form = {'incident.location': field}
    claim = WorkingClaim(
        claim_id='clm_timing',
        customer_id='cus_timing',
        channel='web_agent',
        locale='en-NZ',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        revision=8,
        form=form,
        customer_next_step=CustomerNextStep(
            status='confirmation_requested',
            summary='Confirm Symonds Street.',
            responsible_party='claimant',
        ),
    )
    request = ConfirmationRequestRecord(
        confirmation_id='cnf_shown',
        claim_id=claim.claim_id,
        claim_revision=7,
        field_codes=list(form),
        shown_values_fingerprint=shown_values_fingerprint(form, list(form)),
        created_at=datetime.now(UTC),
    )
    return claim, form, request


def test_message_own_revision_increment_does_not_invalidate_displayed_confirmation() -> None:
    claim, form, request = _confirmation()
    assert can_confirm(claim, form, request, revision_before_message=7, confirms_batch=True)
    assert not can_confirm(claim, form, request, revision_before_message=8, confirms_batch=True)


def test_same_turn_correction_cannot_confirm_undisplayed_replacement() -> None:
    claim, form, request = _confirmation()
    changed = {
        'incident.location': form['incident.location'].model_copy(update={'value': 'Queen Street'})
    }
    assert not can_confirm(claim, changed, request, revision_before_message=7, confirms_batch=True)


def test_plain_yes_cannot_confirm_without_current_displayed_request() -> None:
    claim, form, request = _confirmation()
    assert not can_confirm(claim, form, None, revision_before_message=7, confirms_batch=True)
    assert not can_confirm(claim, form, request, revision_before_message=7, confirms_batch=False)
    assert not can_confirm(
        claim,
        form,
        request.model_copy(update={'claim_revision': 6}),
        revision_before_message=7,
        confirms_batch=True,
    )
