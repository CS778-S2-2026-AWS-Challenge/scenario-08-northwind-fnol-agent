from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from backend.domain.models import (
    ActorReference,
    ActorType,
    AssertionRelation,
    ContentsLossType,
    ContentsOwnership,
    FactPrecision,
    FactResolutionState,
    FormSource,
    FormStatus,
    MessageRecord,
    MessageVisibility,
    NeededFor,
    ProposedContentsItem,
    ProposedFormChange,
    StructuredFormField,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.fact_resolution import (
    confirm_contents_item,
    confirm_form_field,
    infer_precision,
    provenance_messages_for_fields,
    resolve_contents_item_change,
    resolve_form_change,
)

NOW = datetime(2026, 9, 8, tzinfo=UTC)
ACTOR = ActorReference(actor_type=ActorType.CLAIMANT, actor_id='vp-test')


def _field(value: object, status: FormStatus = FormStatus.CONFIRMED) -> StructuredFormField:
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        source_refs=['msg-old'],
        status=status,
        needed_for=NeededFor.CURRENT_ACTION,
        confidence=1.0,
        updated_at=NOW,
        updated_by=ACTOR,
    )


def _proposal(value: object, *, text: str | None = None) -> ProposedFormChange:
    return ProposedFormChange(
        field_code='incident.occurred_at',
        value=value,
        source=FormSource.CLAIMANT,
        status=FormStatus.CONFIRMED,
        needed_for=NeededFor.CURRENT_ACTION,
        reported_text=text,
    )


def _item(description: str, value: int | None = None) -> ProposedContentsItem:
    return ProposedContentsItem(
        description=description,
        category='electronics',
        quantity=1,
        loss_type=ContentsLossType.DAMAGED,
        ownership=ContentsOwnership.OWNED,
        estimated_value=({'amount': value, 'currency': 'NZD'} if value is not None else None),
        confidence=0.9,
    )


def test_precision_preserves_range_approximation_and_unknown() -> None:
    assert (
        infer_precision(
            'incident.occurred_at',
            {'precision': 'partial'},
            None,
        )
        is FactPrecision.PARTIAL
    )
    assert (
        infer_precision('incident.occurred_at', {'precision': 'not-valid'}, None)
        is FactPrecision.UNKNOWN
    )
    assert (
        infer_precision('incident.occurred_at', 'x', 'between Monday and Tuesday')
        is FactPrecision.RANGE
    )
    assert infer_precision('incident.occurred_at', 'x', 'about 9am') is FactPrecision.APPROXIMATE
    assert infer_precision('incident.occurred_at', '', '') is FactPrecision.UNKNOWN
    assert infer_precision('incident.location', 'x', 'about here') is FactPrecision.EXACT


def test_form_resolution_initial_equivalent_refinement_and_conflict() -> None:
    initial = resolve_form_change(
        field_code='incident.occurred_at',
        existing=None,
        proposal=_proposal('Monday', text='about Monday'),
        source_ref='msg-1',
        message_text='about Monday',
        timestamp=NOW,
        accepted_status=FormStatus.PROPOSED,
        updated_by=ACTOR,
    )
    assert initial.assertions[0].relation is AssertionRelation.INITIAL
    equivalent = resolve_form_change(
        field_code='incident.occurred_at',
        existing=initial,
        proposal=_proposal('Monday'),
        source_ref='msg-2',
        message_text='Monday',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert equivalent.assertions[-1].relation is AssertionRelation.EQUIVALENT
    refined = resolve_form_change(
        field_code='incident.occurred_at',
        existing=initial,
        proposal=_proposal('2026-09-08T09:00:00Z'),
        source_ref='msg-3',
        message_text='exactly 9am',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert refined.current_assertion_id == refined.assertions[-1].assertion_id
    conflict = resolve_form_change(
        field_code='incident.occurred_at',
        existing=refined,
        proposal=_proposal('Tuesday'),
        source_ref='msg-4',
        message_text='Tuesday',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert conflict.status is FormStatus.DISPUTED
    assert conflict.resolution_state is FactResolutionState.CLARIFICATION_REQUIRED


def test_confirmation_and_contents_history_preserve_current_assertion() -> None:
    field = _field('Monday', FormStatus.PROPOSED)
    confirmed = confirm_form_field(field, timestamp=NOW, updated_by=ACTOR)
    assert confirmed.status is FormStatus.CONFIRMED
    item = resolve_contents_item_change(
        existing=None,
        proposal=_item('Laptop'),
        item_id='item-1',
        source_ref='msg-1',
        message_text='Laptop',
        timestamp=NOW,
        accepted_status=FormStatus.PROPOSED,
        updated_by=ACTOR,
    )
    assert item.assertions[0].relation is AssertionRelation.INITIAL
    same = resolve_contents_item_change(
        existing=item,
        proposal=_item('Laptop'),
        item_id='item-1',
        source_ref='msg-2',
        message_text='Laptop',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert same.assertions[-1].relation is AssertionRelation.EQUIVALENT
    same = confirm_contents_item(same, timestamp=NOW, updated_by=ACTOR)
    conflict = resolve_contents_item_change(
        existing=same,
        proposal=_item('Phone'),
        item_id='item-1',
        source_ref='msg-3',
        message_text='Actually it was a phone',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert conflict.status is FormStatus.CONFIRMED
    assert conflict.assertions[-1].relation is AssertionRelation.CORRECTION
    material = resolve_contents_item_change(
        existing=same,
        proposal=_item('Phone'),
        item_id='item-1',
        source_ref='msg-4',
        message_text='The item was a phone',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert material.status is FormStatus.DISPUTED
    assert (
        confirm_contents_item(item, timestamp=NOW, updated_by=ACTOR).status is FormStatus.CONFIRMED
    )


def test_legacy_field_history_and_approximate_to_exact_refinement_are_preserved() -> None:
    existing = _field('around Monday')
    existing = existing.model_copy(
        update={
            'precision': FactPrecision.APPROXIMATE,
            'assertions': [],
        }
    )
    refined = resolve_form_change(
        field_code='incident.occurred_at',
        existing=existing,
        proposal=_proposal('Monday at 9am'),
        source_ref='msg-refined',
        message_text='Monday at 9am',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )

    assert refined.assertions[0].assertion_id == 'ast_legacy_incident_occurred_at'
    assert refined.assertions[0].status is FormStatus.SUPERSEDED
    assert refined.assertions[-1].relation is AssertionRelation.REFINEMENT


def test_provenance_messages_only_loads_sources_for_clarification() -> None:
    message = MessageRecord(
        message_id='msg_conflict',
        claim_id='clm_vp',
        session_id='ses_vp',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'It happened on Tuesday.'},
        created_at=NOW,
    )

    class Repository:
        def list_sessions_for_claim(self, claim_id: str, customer_id: str) -> list[object]:
            assert (claim_id, customer_id) == ('clm_vp', 'cus_vp')
            return [SimpleNamespace(session_id='ses_vp')]

        def list_messages(
            self, claim_id: str, session_id: str, customer_id: str
        ) -> list[MessageRecord]:
            assert (claim_id, session_id, customer_id) == ('clm_vp', 'ses_vp', 'cus_vp')
            return [message]

    field = _field('Monday').model_copy(
        update={
            'resolution_state': FactResolutionState.CLARIFICATION_REQUIRED,
            'source_refs': ['msg_conflict', 'msg_missing'],
        }
    )
    resolved = provenance_messages_for_fields(
        cast(PersistenceRepository, Repository()),
        claim_id='clm_vp',
        customer_id='cus_vp',
        fields=[field],
    )

    assert [item.message_id for item in resolved] == ['msg_conflict']
    assert (
        provenance_messages_for_fields(
            cast(PersistenceRepository, Repository()),
            claim_id='clm_vp',
            customer_id='cus_vp',
            fields=[_field('Monday')],
        )
        == []
    )


def test_contents_legacy_history_and_estimated_value_refinement_are_recorded() -> None:
    proposed = resolve_contents_item_change(
        existing=None,
        proposal=_item('Laptop'),
        item_id='item-legacy',
        source_ref='msg-legacy',
        message_text='Laptop',
        timestamp=NOW,
        accepted_status=FormStatus.PROPOSED,
        updated_by=ACTOR,
    )
    legacy = proposed.model_copy(update={'assertions': [], 'status': FormStatus.PROPOSED})
    refined = resolve_contents_item_change(
        existing=legacy,
        proposal=_item('Laptop'),
        item_id='item-legacy',
        source_ref='msg-legacy-refinement',
        message_text='Laptop details',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert refined.assertions[0].assertion_id == 'ast_legacy_item-legacy'

    confirmed_without_value = confirm_contents_item(proposed, timestamp=NOW, updated_by=ACTOR)
    priced = resolve_contents_item_change(
        existing=confirmed_without_value,
        proposal=_item('Laptop', value=1200),
        item_id='item-legacy',
        source_ref='msg-price',
        message_text='The laptop is worth 1200 dollars.',
        timestamp=NOW,
        accepted_status=FormStatus.CONFIRMED,
        updated_by=ACTOR,
    )
    assert priced.assertions[-1].relation is AssertionRelation.REFINEMENT
