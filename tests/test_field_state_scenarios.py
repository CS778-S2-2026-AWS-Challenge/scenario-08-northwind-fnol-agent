"""Contract checks for the Week 6 three-family field-state examples."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.branch_registry import (
    BranchRuleEvaluator,
    validate_registered_field_value,
)
from backend.domain.models import FieldSelectionState, FormSource, FormStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import ScenarioFixture, load_scenario, seed_scenario

SCENARIO_DIRECTORY = Path(__file__).parents[1] / 'backend' / 'demo_data' / 'scenarios'
SCENARIOS = (
    'AT-14-field-states-motor',
    'AT-15-field-states-home',
    'AT-16-field-states-contents',
)


def _scenario(name: str) -> ScenarioFixture:
    return load_scenario(SCENARIO_DIRECTORY / f'{name}.json')


@pytest.mark.parametrize('scenario_id', SCENARIOS)
def test_three_path_field_state_fixtures_validate_registered_values(scenario_id: str) -> None:
    scenario = _scenario(scenario_id)
    expected = scenario.expected['field_states']

    assert scenario.expected['family'] == scenario.claim.form['claim.product_family'].value
    for field_code, stored in scenario.claim.form.items():
        validate_registered_field_value(field_code, stored.value, status=stored.status)

    for field_code in expected['confirmed']:
        assert scenario.claim.form[field_code].status is FormStatus.CONFIRMED
    for field_code in expected['inferred']:
        if field_code.startswith('contents_items['):
            item_id = field_code.removeprefix('contents_items[').removesuffix(']')
            item = next(item for item in scenario.claim.contents_items if item.item_id == item_id)
            assert item.source is FormSource.INFERENCE
            assert item.status is FormStatus.PROPOSED
        else:
            stored = scenario.claim.form[field_code]
            assert stored.source is FormSource.INFERENCE
            assert stored.status is FormStatus.PROPOSED
    for field_code in expected['missing']:
        stored = scenario.claim.form[field_code]
        assert stored.value is None
        assert stored.status is FormStatus.MISSING
    for field_code in expected['conflicting']:
        stored = scenario.claim.form[field_code]
        assert stored.status is FormStatus.DISPUTED
        assert len(stored.source_refs) >= 2
        assert len(stored.assertions) >= 2
    for field_code in expected['not_applicable']:
        if field_code == 'contents.items':
            assert scenario.claim.contents_items == []
            continue
        assert field_code not in scenario.claim.form


@pytest.mark.parametrize(
    ('scenario_id', 'inactive_fields'),
    [
        ('AT-14-field-states-motor', {'property.address', 'contents.items'}),
        ('AT-15-field-states-home', {'vehicle.registration', 'contents.items'}),
        ('AT-16-field-states-contents', {'vehicle.registration', 'property.address'}),
    ],
)
def test_three_path_field_state_fixtures_use_inactive_projection_for_other_families(
    scenario_id: str,
    inactive_fields: set[str],
) -> None:
    scenario = _scenario(scenario_id)
    evaluation = BranchRuleEvaluator().evaluate(scenario.claim)
    selected = {item.field_code: item.selection_state for item in evaluation.field_selection}

    assert evaluation.selected_family == scenario.expected['family']
    expected_not_applicable = set(scenario.expected['field_states']['not_applicable'])
    assert expected_not_applicable == inactive_fields
    for field_code in inactive_fields:
        if field_code == 'contents.items':
            assert scenario.claim.contents_items == []
        else:
            assert field_code in selected
            assert selected[field_code] is FieldSelectionState.INACTIVE
    assert not any(field_code.startswith('contents.') for field_code in scenario.claim.form)


@pytest.mark.parametrize('scenario_id', SCENARIOS)
def test_each_family_is_projected_through_claimant_and_workbench_apis(scenario_id: str) -> None:
    scenario = _scenario(scenario_id)
    repository = FixtureRepository()
    seed_scenario(repository, scenario)
    app = create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), repository)

    with TestClient(app) as client:
        claimant = client.get(
            f'/api/v1/claims/{scenario.claim.claim_id}',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )
        workbench = client.get(
            f'/api/v1/workbench/claims/{scenario.claim.claim_id}',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        workbench_fields = client.get(
            f'/api/v1/workbench/claims/{scenario.claim.claim_id}/fields',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )

    assert claimant.status_code == 200, claimant.text
    assert workbench.status_code == 200, workbench.text
    assert workbench_fields.status_code == 200, workbench_fields.text
    claimant_body = claimant.json()
    workbench_body = workbench.json()
    assert claimant_body['incident_type'] == scenario.expected['family']
    assert workbench_body['incident']['family'] == scenario.expected['family']
    for field_code, stored in scenario.claim.form.items():
        assert claimant_body['form'][field_code]['status'] == stored.status.value
    staff_fields = {item['code']: item['field'] for item in workbench_fields.json()['items']}
    assert set(staff_fields) == set(scenario.claim.form)
    for field_code, stored in scenario.claim.form.items():
        assert staff_fields[field_code]['status'] == stored.status.value

    if scenario_id != 'AT-16-field-states-contents':
        assert claimant_body['contents_items'] == []
        assert workbench_body['contents_items'] == []
        return

    claimant_items = claimant.json()['contents_items']
    workbench_items = workbench.json()['contents_items']
    assert {item['item_id'] for item in claimant_items} == {
        'contents_at16_laptop',
        'contents_at16_camera',
    }
    assert {item['item_id'] for item in workbench_items} == {
        'contents_at16_laptop',
        'contents_at16_camera',
    }
    assert all('confidence' not in item and 'updated_by' not in item for item in claimant_items)
    assert all('confidence' in item and 'updated_by' in item for item in workbench_items)


def test_branch_incompatible_form_update_is_rejected_without_claim_mutation(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'field-state-incompatible'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201, created.text
    claim_id = created.json()['claim']['claim_id']
    before = repository.get_claim(claim_id, 'cus_demo')
    assert before is not None
    evaluations_before = repository.list_branch_evaluations(claim_id, 'cus_demo')

    response = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(before.revision)},
        json={'updates': [{'field_code': 'property.address', 'value': '14 Synthetic Lane'}]},
    )

    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert 'inactive' in response.json()['error']['details'][0]['reason']
    assert repository.get_claim(claim_id, 'cus_demo') == before
    assert repository.list_branch_evaluations(claim_id, 'cus_demo') == evaluations_before


def test_field_state_examples_reject_unknown_and_invalid_values() -> None:
    with pytest.raises(ValueError, match='Unknown registered field'):
        validate_registered_field_value('contents.items', 'flattened')
    with pytest.raises(ValueError, match='Allowed values'):
        validate_registered_field_value('claim.product_family', 'unknown')
    with pytest.raises(ValueError, match='boolean value'):
        validate_registered_field_value('property.habitable', 'yes')
