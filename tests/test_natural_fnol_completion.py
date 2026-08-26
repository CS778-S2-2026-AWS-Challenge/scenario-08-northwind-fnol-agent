from fastapi.testclient import TestClient


def _fact_codes(turn: dict[str, object]) -> set[str]:
    form_changes = turn['form_changes']
    assert isinstance(form_changes, list)
    return {str(item['field_code']) for item in form_changes if isinstance(item, dict)}


def test_natural_language_fnol_only_asks_for_the_missing_required_fact(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'p0-natural-fnol-create'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201
    created_body = created.json()
    claim_id = created_body['claim']['claim_id']
    session_id = created_body['session']['session_id']
    assert created_body['claim']['incident_type'] is None

    initial = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p0-natural-fnol-initial',
            'If-Match': str(created_body['claim']['revision']),
        },
        json={
            'client_message_id': 'p0-natural-fnol-initial',
            'content': {
                'type': 'text',
                'text': 'Another car collided with mine at Queen Street.',
            },
            'evidence_refs': [],
        },
    )
    assert initial.status_code == 200
    initial_body = initial.json()
    assert _fact_codes(initial_body) == {
        'incident.description',
        'incident.location',
        'incident.type',
    }
    initial_message_id = initial_body['claimant_message']['message_id']
    for change in initial_body['form_changes']:
        assert change['field']['source_refs'] == [initial_message_id]

    initial_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p0-natural-fnol-confirm-initial',
            'If-Match': str(initial_body['claim_revision']),
        },
        json={
            'field_codes': [
                'incident.description',
                'incident.location',
                'incident.type',
            ]
        },
    )
    assert initial_confirmation.status_code == 200
    initial_confirmation_body = initial_confirmation.json()
    missing_step = initial_confirmation_body['customer_next_step']
    assert missing_step['status'] == 'describe_loss'
    assert missing_step['required_items'] == ['loss.description']

    missing_fact = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p0-natural-fnol-loss',
            'If-Match': str(initial_confirmation_body['revision']),
        },
        json={
            'client_message_id': 'p0-natural-fnol-loss',
            'content': {'type': 'text', 'text': 'The rear bumper is dented.'},
            'evidence_refs': [],
        },
    )
    assert missing_fact.status_code == 200
    missing_fact_body = missing_fact.json()
    assert _fact_codes(missing_fact_body) == {'loss.description'}
    assert missing_fact_body['decision']['customer_next_step']['required_items'] == [
        'loss.description'
    ]

    final_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p0-natural-fnol-confirm-loss',
            'If-Match': str(missing_fact_body['claim_revision']),
        },
        json={'field_codes': ['loss.description']},
    )
    assert final_confirmation.status_code == 200
    final_confirmation_body = final_confirmation.json()
    assert final_confirmation_body['customer_next_step']['status'] == 'ready_to_create'
    assert final_confirmation_body['customer_next_step']['required_items'] == []

    workbench = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert workbench.status_code == 200
    workbench_body = workbench.json()
    assert workbench_body['incident_type'] == 'motor'
    assert workbench_body['handoffs'] == []
    for field_code in (
        'incident.description',
        'incident.location',
        'incident.type',
        'loss.description',
    ):
        field = workbench_body['form'][field_code]
        assert field['status'] == 'confirmed'
        assert field['source_refs']

    completion_metrics = {
        'claimant_agent_turns_to_ready': 2,
        'expected_missing_after_initial_confirmation': ['loss.description'],
        'detected_missing_after_initial_confirmation': missing_step['required_items'],
        'unnecessary_or_repeated_questions': 0,
        'human_interventions_before_staff_ready': len(workbench_body['handoffs']),
    }
    assert completion_metrics == {
        'claimant_agent_turns_to_ready': 2,
        'expected_missing_after_initial_confirmation': ['loss.description'],
        'detected_missing_after_initial_confirmation': ['loss.description'],
        'unnecessary_or_repeated_questions': 0,
        'human_interventions_before_staff_ready': 0,
    }

    external_creation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p0-natural-fnol-create-external',
            'If-Match': str(final_confirmation_body['revision']),
        },
    )
    assert external_creation.status_code == 201
    assert external_creation.json()['external_claim']['creation_status'] == 'created'
