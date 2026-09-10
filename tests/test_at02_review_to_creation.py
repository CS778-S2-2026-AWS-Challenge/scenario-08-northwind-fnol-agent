"""`AT-02` must reach claim creation, and only after its professional review.

The scenario is the canonical `professional_review` business path. Its claim family was
`property`, which `claim_creation.py` does not accept, so the path dead-ended: staff could
work the claim but it could never be created. #690 made `property` explicitly unsupported
and so gave a recorded open decision a consequence.

Correcting the family alone is not enough, and that is what these assert. Three guards
stand between this claim and creation — the family, the open professional review, and the
open handoff — and the scenario has to pass all three legitimately. The review resolving
to `coverage: clear` is not this fixture's choice: it is what the action registry projects
for `human.resolve_handoff`, and the submitted payload must equal that projection exactly.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario

SCENARIO_PATH = (
    Path(__file__).resolve().parents[1]
    / 'backend'
    / 'demo_data'
    / 'scenarios'
    / 'AT-02-coverage-ambiguity.json'
)
CLAIMANT = {'Authorization': 'Bearer synthetic-claimant'}
STAFF = {'Authorization': 'Bearer synthetic-staff'}


@pytest.fixture
def repository() -> FixtureRepository:
    store = FixtureRepository()
    seed_scenario(store, load_scenario(SCENARIO_PATH))
    return store


@pytest.fixture
def client(repository: FixtureRepository) -> Iterator[TestClient]:
    app = create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), repository)
    with TestClient(app) as test_client:
        yield test_client


def _claim_id() -> str:
    return load_scenario(SCENARIO_PATH).claim.claim_id


def _revision(client: TestClient, claim_id: str) -> str:
    return str(client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()['revision'])


def _detail(client: TestClient, claim_id: str) -> dict[str, Any]:
    body: dict[str, Any] = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF).json()
    return body


def _resolve_handoff(client: TestClient, claim_id: str, handoff_id: str) -> Any:
    """Resolve using the projection's own payload, which is the only one accepted."""

    action = next(
        item
        for item in _detail(client, claim_id)['allowed_actions']
        if item['action_code'] == 'human.resolve_handoff'
    )
    defaults = action['payload_defaults']
    return client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve',
        headers={
            **STAFF,
            'Idempotency-Key': 'at02-resolve',
            'If-Match': _revision(client, claim_id),
        },
        json={
            'result': {**defaults['result'], 'summary': 'Policy section confirmed after review.'},
            'state_changes': defaults['state_changes'],
            'customer_update': {
                **defaults['customer_update'],
                'summary': 'A claims professional confirmed the policy section.',
            },
        },
    )


def test_the_scenario_uses_a_supported_claim_family() -> None:
    """`property` is not a family the creation service accepts, and never was for this claim.

    Its own policy number is `POL-MVP-HOME-2048` and its description is water ingress to a
    ground floor. The label was the only thing wrong.
    """

    claim = load_scenario(SCENARIO_PATH).claim

    assert claim.incident_type == 'home'
    assert claim.form['claim.product_family'].value == 'home'
    assert claim.form['policy.policy_number'].value.startswith('POL-MVP-HOME')


# Each confirmed fact, and a phrase the record it cites must actually contain. A
# `source_ref` that resolves to a real record but not to supporting content is worse than
# a missing one, because it looks checked.
SUPPORTING_PHRASE = {
    'incident.description': 'water entered the ground floor',
    'incident.location': '18 rimu street',
    'property.address': '18 rimu street',
    'incident.occurred_at': 'evening of 14 august',
    'property.affected_areas': 'hallway',
    'loss.description': 'skirting boards',
    'incident.injury_or_danger': 'nobody was hurt',
    'property.ongoing_risk': 'still seeping in',
    'property.habitable': 'still living here',
}


def test_every_confirmed_fact_cites_a_record_that_supports_it() -> None:
    """A `source_ref` must resolve to content that actually establishes the value.

    The first attempt at this correction attached eight confirmed claimant facts to
    `msg_at02_claimant_1`, whose whole text is "Water entered the ground floor after
    several days of heavy rain." That message establishes none of an address, a
    timestamp, a hallway, current leakage, habitability, or an absence of injury —
    absence of a statement is not a stated negative.
    """

    scenario = load_scenario(SCENARIO_PATH)
    messages = {
        message.message_id: str(message.content.get('text', '')).lower()
        for message in scenario.messages
    }
    retrievals = {record.retrieval_id for record in scenario.retrievals}

    confirmed = {
        code: field
        for code, field in scenario.claim.form.items()
        if field.status.value == 'confirmed'
    }
    assert confirmed, 'the scenario must confirm something'

    for code, field in confirmed.items():
        assert field.source_refs, f'{code} confirms a value while citing nothing'
        for ref in field.source_refs:
            assert ref in messages or ref in retrievals, f'{code} cites {ref}, which does not exist'
        phrase = SUPPORTING_PHRASE.get(code)
        if phrase is None:
            continue
        cited = ' '.join(messages.get(ref, '') for ref in field.source_refs)
        assert phrase in cited, f'{code} cites a record that does not say "{phrase}"'


def test_the_family_is_taken_from_the_policy_not_read_into_a_sentence() -> None:
    """`claim.product_family` is a classification, not something the claimant declared.

    No message in this scenario states a product family. The retrieved policy record
    does — product "Home Plus" — so that is the authority, and the source type says so.
    """

    field = load_scenario(SCENARIO_PATH).claim.form['claim.product_family']

    assert field.value == 'home'
    assert field.source.value == 'policy'
    assert field.source_refs == ['ret_fixture_at02_policy']


def test_who_updated_a_field_agrees_with_where_it_came_from() -> None:
    """`source`, `source_refs`, and `updated_by` are three statements about one origin.

    A field sourced from a policy retrieval but stamped as updated by the claimant
    attributes a system classification to a claimant action, and a consumer reading the
    audit metadata rather than the source would believe it. The three have to agree.
    """

    scenario = load_scenario(SCENARIO_PATH)
    holders = {
        'claim.form': scenario.claim.form,
        'handoff packet': scenario.handoffs[0].packet.form_snapshot,
    }

    for label, form in holders.items():
        for code, field in form.items():
            actor = field.updated_by.actor_type.value
            if field.source.value == 'claimant':
                assert actor == 'claimant', f'{label}: {code}'
                assert all(ref.startswith('msg_') for ref in field.source_refs), f'{label}: {code}'
            elif field.source.value == 'policy':
                # The convention `policy.policy_number` already uses in this fixture.
                assert actor == 'system', f'{label}: {code}'
                assert all(ref.startswith('ret_') for ref in field.source_refs), f'{label}: {code}'


def test_an_evening_is_not_an_exact_timestamp() -> None:
    """ "The evening of 14 August" fixes the day, and the stored precision says so."""

    field = load_scenario(SCENARIO_PATH).claim.form['incident.occurred_at']

    assert field.precision.value == 'approximate'


def test_the_coverage_question_is_not_confirmed_away() -> None:
    """`incident.cause` stays disputed: it *is* the ambiguity this scenario demonstrates.

    Confirming it would make `requirements.ready` true and delete the reason the card
    exists, which is why the required-fact migration deliberately leaves it alone.
    """

    claim = load_scenario(SCENARIO_PATH).claim

    assert claim.form['incident.cause'].status.value == 'disputed'
    assert claim.claim_state.coverage.value == 'ambiguous'


def test_the_handoff_packet_is_a_snapshot_of_the_whole_claim_form() -> None:
    """Staff receive what the claim holds, not a subset frozen before it was filled in.

    `handoffs.py` snapshots `claim.form` entire, so a fixture whose packet carries fewer
    fields than its claim describes a handoff the code could not have produced — and the
    staff member reviewing it would be deciding on a partial record without being told.
    Adding confirmed facts without syncing the packet is exactly how that happens.
    """

    scenario = load_scenario(SCENARIO_PATH)
    packet = scenario.handoffs[0].packet

    assert set(packet.form_snapshot) == set(scenario.claim.form)
    for code, field in scenario.claim.form.items():
        assert packet.form_snapshot[code].value == field.value, code
        assert packet.form_snapshot[code].status == field.status, code
        assert packet.form_snapshot[code].source_refs == field.source_refs, code


def test_the_packet_cites_every_record_its_fields_cite() -> None:
    """`source_refs` is the union of the fields' own references, plus the retrievals.

    The two claimant turns that carry the new facts have to appear here, or the packet
    points staff at provenance it does not include.
    """

    scenario = load_scenario(SCENARIO_PATH)
    packet = scenario.handoffs[0].packet
    field_refs = {ref for field in scenario.claim.form.values() for ref in field.source_refs}

    assert field_refs <= set(packet.source_refs)
    assert {'msg_at02_claimant_2', 'msg_at02_claimant_3'} <= set(packet.source_refs)


def test_the_acceptance_metadata_matches_the_fixture_it_describes() -> None:
    """`expected` is read by humans, so a stale value is a false statement about the fixture."""

    scenario = load_scenario(SCENARIO_PATH)
    confirmed = sorted(
        code for code, field in scenario.claim.form.items() if field.status.value == 'confirmed'
    )

    assert sorted(scenario.expected['confirmed_fields']) == confirmed
    # Renamed when the evidence condition and file lifecycle were separated.
    assert scenario.expected['evidence_state'] == scenario.claim.claim_state.evidence.value


def test_creation_is_refused_while_the_professional_review_is_open(
    client: TestClient,
) -> None:
    """The family guard now passes and the next guard correctly still refuses."""

    claim_id = _claim_id()

    response = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'at02-early',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    assert response.status_code == 409
    error = response.json()['error']
    assert error['code'] == 'INVALID_STATE_TRANSITION'
    # The professional-review guard, not the family guard it used to fail on.
    assert error['message'] == 'This report is not ready for controlled claim creation.'


def test_review_then_creation_succeeds_and_keeps_the_conflict(
    client: TestClient,
) -> None:
    """The whole path: refused, reviewed through the staff authority, then created.

    What the review settles is the coverage question. What it does not settle — the
    conflicting evidence and the disputed cause — survives creation, because creation is
    not a decision about either.
    """

    claim_id = _claim_id()
    handoff_id = load_scenario(SCENARIO_PATH).handoffs[0].handoff_id

    accepted = client.post(
        f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
        headers={
            **STAFF,
            'Idempotency-Key': 'at02-accept',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )
    assert accepted.status_code == 200
    # Accepting does not settle anything on its own.
    assert _detail(client, claim_id)['claim_state']['workflow_state'] == 'professional_review'

    resolved = _resolve_handoff(client, claim_id, handoff_id)
    assert resolved.status_code == 200
    after_review = _detail(client, claim_id)['claim_state']
    assert after_review['workflow_state'] == 'ready_for_next'
    # The registry's own projected state change, not this test's preference.
    assert after_review['coverage'] == 'clear'

    created = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'at02-create',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )
    assert created.status_code == 201

    final = _detail(client, claim_id)
    assert final['claim_state']['workflow_state'] == 'created'
    assert final['claim_state']['evidence'] == 'in_conflict'
    gaps = {
        (gap['kind'], gap['code']): gap['status']
        for gap in final['work_summary']['missing_information']
    }
    assert gaps[('field', 'incident.cause')] == 'disputed'
    assert gaps[('evidence', 'other_document')] == 'conflicting'
