"""Regression coverage for participant records at the shared Claim mutation boundary."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.models import AgentAction, FormSource, FormStatus, ProposedFormChange
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext
from backend.services.protected_values import ProtectedValueError, UnavailableProtectedValueAdapter
from tests.test_claim_api import create_claim, submit_message


class ParticipantAgent:
    def __init__(self, changes: list[ProposedFormChange]) -> None:
        self.changes = changes

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['PARTICIPANT_INFORMATION_RECORDED'],
            customer_reason='The claimant supplied participant information.',
            customer_response='I have recorded the information you supplied.',
            customer_next_step=context.claim.customer_next_step,
            form_changes=self.changes,
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
        )


def _changes(**values: Any) -> list[ProposedFormChange]:
    return [
        ProposedFormChange(
            field_code=code, value=value, source=FormSource.CLAIMANT, status=FormStatus.CONFIRMED
        )
        for code, value in values.items()
    ]


def test_agent_participant_commit_reads_replay_and_correction(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    activated = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': 'witness.present', 'value': 'yes'}]},
    )
    assert activated.status_code == 200, activated.text
    agent = ParticipantAgent(
        _changes(
            **{
                'policyholder.name': 'Synthetic Policyholder',
                'policyholder.identity_ref': 'identity-policyholder',
                'driver.name': 'Synthetic Driver',
                'driver.identity_ref': 'identity-driver',
                'witness.name': 'Synthetic Witness',
                'witness.phone': '+64 21 555 0101',
            }
        )
    )
    app.state.agent_turn_provider = agent
    arguments: dict[str, Any] = {
        'revision': activated.json()['revision'],
        'text': 'Synthetic Policyholder identity-policyholder, Synthetic Driver identity-driver; '
        'Synthetic Witness +64 21 555 0101 witnessed the accident.',
    }
    first = submit_message(client, auth_headers, claim_id, session_id, **arguments)
    assert first.status_code == 200, first.text
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None and stored.driver is not None and stored.policyholder is not None
    assert stored.driver.name == 'Synthetic Driver'
    assert stored.driver.identity_ref == 'identity-driver'
    assert stored.policyholder.name == 'Synthetic Policyholder'
    assert stored.policyholder.identity_ref == 'identity-policyholder'
    witness_id = stored.witnesses[0].witness_id
    original_assertion = stored.form['witness.name'].assertions[0]
    assert original_assertion.source_refs
    for route, headers in [
        (f'/api/v1/claims/{claim_id}', auth_headers),
        (f'/api/v1/workbench/claims/{claim_id}', staff_auth_headers),
    ]:
        view = client.get(route, headers=headers)
        assert view.status_code == 200, view.text
        assert view.json()['driver']['name'] == stored.driver.name
        assert view.json()['policyholder']['name'] == stored.policyholder.name
        assert view.json()['witnesses'][0]['witness_id'] == witness_id
    replay = submit_message(client, auth_headers, claim_id, session_id, **arguments)
    assert replay.status_code == 200, replay.text
    assert repository.get_claim(claim_id, 'cus_demo') == stored
    assert len(repository.list_agent_decisions(claim_id, 'cus_demo')) == 1

    agent.changes = _changes(**{'witness.name': 'Corrected Witness'})
    correction = submit_message(
        client,
        auth_headers,
        claim_id,
        session_id,
        revision=stored.revision,
        key='correction',
        client_message_id='correction',
        text='Correction: the witness name is Corrected Witness.',
    )
    assert correction.status_code == 200, correction.text
    corrected = repository.get_claim(claim_id, 'cus_demo')
    assert corrected is not None
    assert corrected.witnesses[0].witness_id == witness_id
    assert corrected.witnesses[0].name == 'Corrected Witness'
    assert corrected.form['witness.name'].assertions[0].model_dump(exclude={'status'}) == (
        original_assertion.model_dump(exclude={'status'})
    )
    assert corrected.form['witness.name'].assertions[0].status is FormStatus.SUPERSEDED
    assert len(corrected.form['witness.name'].assertions) == 2


@pytest.mark.parametrize('status', [FormStatus.PROPOSED, FormStatus.DISPUTED])
def test_unsettled_agent_participant_requires_confirmation(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    status: FormStatus,
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    app.state.agent_turn_provider = ParticipantAgent(
        [
            ProposedFormChange(
                field_code='driver.name',
                value='Unsettled Driver',
                source=FormSource.CLAIMANT,
                status=status,
            )
        ]
    )
    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        created['session']['session_id'],
        text='The driver may be Unsettled Driver.',
    )
    assert turn.status_code == 200, turn.text
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.driver is None or stored.driver.name is None
    if status is FormStatus.PROPOSED:
        confirmed = client.post(
            f'/api/v1/claims/{claim_id}/form/confirmations',
            headers={
                **auth_headers,
                'If-Match': str(stored.revision),
                'Idempotency-Key': 'confirm-driver',
            },
            json={'field_codes': ['driver.name']},
        )
        assert confirmed.status_code == 200, confirmed.text
        stored = repository.get_claim(claim_id, 'cus_demo')
        assert stored is not None and stored.driver is not None
        assert stored.driver.name == 'Unsettled Driver'


def test_witness_no_then_yes_does_not_resurrect_old_contacts(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    revision = created['claim']['revision']
    for updates, expected_names in [
        ({'witness.present': 'yes', 'witness.name': 'Old Witness'}, ['Old Witness']),
        ({'witness.present': 'no'}, []),
        ({'witness.present': 'yes'}, []),
        ({'witness.name': 'New Witness'}, ['New Witness']),
    ]:
        patched = client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={**auth_headers, 'If-Match': str(revision)},
            json={
                'updates': [
                    {
                        'field_code': code,
                        'value': value,
                        'correction_reason': 'The claimant corrected witness information.',
                    }
                    for code, value in updates.items()
                ]
            },
        )
        assert patched.status_code == 200, patched.text
        revision = patched.json()['revision']
        stored = repository.get_claim(claim_id, 'cus_demo')
        assert stored is not None
        assert [witness.name for witness in stored.witnesses] == expected_names


@pytest.mark.parametrize('code', ['driver.licence_number', 'other_party.policy_number'])
def test_protected_agent_proposal_is_rejected_before_claim_or_decision_commit(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    code: str,
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    before = repository.get_claim(claim_id, 'cus_demo')
    secret = 'SYNTHETIC-PROTECTED-1234'
    app.state.agent_turn_provider = ParticipantAgent(_changes(**{code: secret}))
    turn = submit_message(
        client,
        auth_headers,
        claim_id,
        created['session']['session_id'],
        text='Please add my protected details.',
    )
    assert turn.status_code == 422, turn.text
    assert turn.json()['error']['code'] == 'PROTECTED_DATA_REQUIRES_DEDICATED_ROUTE'
    assert secret not in turn.text
    after = repository.get_claim(claim_id, 'cus_demo')
    assert after is not None and before is not None
    # Inbound message acceptance precedes the model call; only that checkpoint survives.
    assert after.revision == before.revision + 1
    assert after.model_dump(exclude={'revision', 'updated_at'}) == before.model_dump(
        exclude={'revision', 'updated_at'}
    )
    messages = repository.list_messages(claim_id, created['session']['session_id'], 'cus_demo')
    assert len(messages) == 1 and messages[0].actor.value == 'claimant'
    assert secret not in messages[0].model_dump_json()
    assert repository.list_agent_decisions(claim_id, 'cus_demo') == []


def test_agent_witness_uncertainty_preserves_identity_until_confirmed_absence(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    initialized = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={
            'updates': [
                {'field_code': code, 'value': value}
                for code, value in {
                    'witness.present': 'yes',
                    'witness.name': 'First Witness',
                    'witness.phone': '+64 21 555 0101',
                }.items()
            ]
        },
    )
    assert initialized.status_code == 200, initialized.text
    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    witness_id = stored.witnesses[0].witness_id
    for index, (code, value, status) in enumerate(
        [
            ('witness.present', 'no', FormStatus.PROPOSED),
            ('witness.name', 'Unknown Witness', FormStatus.DISPUTED),
            ('witness.present', 'no', FormStatus.CONFIRMED),
        ]
    ):
        app.state.agent_turn_provider = ParticipantAgent(
            [
                ProposedFormChange(
                    field_code=code, value=value, source=FormSource.CLAIMANT, status=status
                )
            ]
        )
        response = submit_message(
            client,
            auth_headers,
            claim_id,
            created['session']['session_id'],
            revision=stored.revision,
            key=f'witness-{index}',
            client_message_id=f'witness-{index}',
            text=f'Correction: {code} is {value}.',
        )
        assert response.status_code == 200, response.text
        stored = repository.get_claim(claim_id, 'cus_demo')
        assert stored is not None
        if index == 2:
            assert stored.witnesses == []
        else:
            assert stored.witnesses[0].witness_id == witness_id
            assert stored.witnesses[0].phone == '+64 21 555 0101'
            if index == 1:
                assert stored.witnesses[0].name is None


def test_protected_licence_long_value_and_same_mask_correction(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    revision = 1
    values = ['甲' * 116 + '1234', '乙' * 116 + '1234']
    for index, value in enumerate(values):
        if index:
            before = repository.get_claim(claim_id, 'cus_demo')
            silent = client.patch(
                f'/api/v1/claims/{claim_id}/form',
                headers={**auth_headers, 'If-Match': str(revision)},
                json={'updates': [{'field_code': 'driver.licence_number', 'value': value}]},
            )
            assert silent.status_code == 409, silent.text
            assert silent.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
            assert repository.get_claim(claim_id, 'cus_demo') == before
        response = client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={**auth_headers, 'If-Match': str(revision)},
            json={
                'updates': [
                    {
                        'field_code': 'driver.licence_number',
                        'value': value,
                        **({'correction_reason': 'Correct licence.'} if index else {}),
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        stored = repository.get_claim(claim_id, 'cus_demo')
        assert stored is not None and stored.driver is not None
        assert stored.driver.licence_number is not None
        assert app.state.protected_value_adapter.resolve(stored.driver.licence_number) == value
        assert stored.driver.licence_number_masked == '****1234'
        assert value not in stored.model_dump_json()
        assert value not in response.text
        assert stored.form['driver.licence_number'].value == '****1234'
        assert all(
            assertion.normalized_value == '****1234'
            for assertion in stored.form['driver.licence_number'].assertions
        )
        revision = stored.revision
    assert stored is not None
    assert len(stored.form['driver.licence_number'].assertions) == 2


@pytest.mark.parametrize('failure', ['missing', 'unavailable', 'failing'])
def test_licence_protection_failure_is_safe_and_does_not_mutate_claim(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    failure: str,
) -> None:
    secret = 'SYNTHETIC-LICENCE-1234'

    class FailingProtection(UnavailableProtectedValueAdapter):
        def seal(self, value: str) -> str:
            raise ProtectedValueError(f'Protection failed for {value}')

    app.state.protected_value_adapter = {
        'missing': None,
        'unavailable': UnavailableProtectedValueAdapter(),
        'failing': FailingProtection(),
    }[failure]
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    before = repository.get_claim(claim_id, 'cus_demo')
    response = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': 'driver.licence_number', 'value': secret}]},
    )
    assert response.status_code == 503, response.text
    assert response.json()['error']['code'] == 'PROTECTED_DATA_UNAVAILABLE'
    assert secret not in response.text
    assert repository.get_claim(claim_id, 'cus_demo') == before


@pytest.mark.parametrize(
    ('code', 'value', 'status'),
    [
        ('driver.name', 'x' * 201, 'confirmed'),
        ('driver.licence_number', 'x' * 121, 'confirmed'),
        ('driver.licence_number', 'SYNTHETIC-LICENCE-1234', 'proposed'),
    ],
)
def test_invalid_participant_patch_fails_safely_before_commit(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    code: str,
    value: str,
    status: str,
) -> None:
    created = create_claim(client, auth_headers).json()
    claim_id = created['claim']['claim_id']
    before = repository.get_claim(claim_id, 'cus_demo')
    response = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': code, 'value': value, 'status': status}]},
    )
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert value not in response.text
    assert repository.get_claim(claim_id, 'cus_demo') == before
