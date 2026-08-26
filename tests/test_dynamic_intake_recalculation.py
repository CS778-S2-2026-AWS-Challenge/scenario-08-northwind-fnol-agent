from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.domain.intake import next_controlled_intake_step
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.services.agent import AgentTurnContext, ControlledAgent


def _confirmed_field(value: object) -> StructuredFormField:
    timestamp = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        status=FormStatus.CONFIRMED,
        needed_for=NeededFor.CURRENT_ACTION,
        confidence=1.0,
        updated_at=timestamp,
        updated_by=ActorReference(
            actor_type=ActorType.CLAIMANT,
            actor_id='cus_dynamic',
        ),
    )


def _complete_claim(claim_family: str) -> WorkingClaim:
    timestamp = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)
    return WorkingClaim(
        claim_id=f'clm_{claim_family}',
        customer_id='cus_dynamic',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type=claim_family,
        form={
            'incident.description': _confirmed_field('A synthetic incident.'),
            'incident.location': _confirmed_field('Auckland'),
            'loss.description': _confirmed_field('Synthetic loss'),
        },
        customer_next_step=CustomerNextStep(
            status='confirmation_required',
            summary='Stale claimant-owned step.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_form_patch_immediately_recalculates_after_out_of_order_confirmed_facts(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'dynamic-patch-claim'},
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']

    patched = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={
            'updates': [
                {
                    'field_code': 'incident.location',
                    'value': 'Queen Street',
                    'status': 'confirmed',
                },
                {
                    'field_code': 'incident.description',
                    'value': 'Another car hit mine from behind.',
                    'status': 'confirmed',
                },
            ]
        },
    )

    assert patched.status_code == 200
    assert patched.json()['revision'] == 2
    next_step = patched.json()['customer_next_step']
    assert next_step['status'] == 'describe_loss'
    assert next_step['required_items'] == ['loss.description']

    persisted = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert persisted.status_code == 200
    assert persisted.json()['customer_next_step'] == next_step


@pytest.mark.parametrize('claim_family', ['home', 'contents'])
def test_completed_non_motor_claim_keeps_resolver_owned_next_step_on_later_message(
    claim_family: str,
) -> None:
    claim = _complete_claim(claim_family)
    expected_next_step = next_controlled_intake_step(claim)

    proposal = ControlledAgent().propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses_dynamic',
            trigger_message_id='msg_dynamic',
            message_text='Thanks, that is everything I have for now.',
            evidence_refs=[],
        )
    )

    assert proposal.customer_next_step == expected_next_step
    assert proposal.customer_next_step.status == 'core_details_confirmed'
    assert proposal.customer_next_step.responsible_party is ResponsibleParty.NORTHWIND
