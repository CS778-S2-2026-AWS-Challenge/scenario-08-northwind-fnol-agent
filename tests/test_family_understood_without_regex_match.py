"""INV-14: model family judgment admits facts without a Runtime keyword match."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.branch_registry import FAMILY_FIELDS, FAMILY_RULE_IDS, BranchRuleEvaluator
from backend.domain.intake import infer_controlled_product_family
from backend.domain.models import FieldSelectionState, FormSource, FormStatus
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import ControlledAgent, InvariantGuardedAgent
from backend.services.model_request_planner import plan_model_turn
from backend.services.turn_family_resolution import resolve_turn_family
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_branch_registry import field, make_claim
from tests.test_claim_api import submit_message
from tests.test_turn_proposal_v8 import v8_context

DESCRIPTION = 'someone backed into me at the lights; the bumper is dented'
FAMILY_QUOTE = 'someone backed into me at the lights'


@pytest.mark.parametrize(
    ('message', 'stored_status', 'selected_family', 'open_other_family'),
    [
        (DESCRIPTION, None, None, True),
        ('My car was damaged.', None, None, True),
        ('My car and roof were damaged.', None, None, True),
        ('The roof was damaged.', FormStatus.PROPOSED, 'motor', True),
        ('The roof was damaged.', FormStatus.CONFIRMED, 'motor', False),
    ],
)
def test_family_hints_do_not_replace_persisted_fact_authority(
    message: str,
    stored_status: FormStatus | None,
    selected_family: str | None,
    open_other_family: bool,
) -> None:
    claim = make_claim()
    if stored_status is not None:
        claim.form['claim.product_family'] = field('motor', stored_status)
    evaluation = BranchRuleEvaluator(model_family_judgment=True).evaluate(
        claim, latest_message=message
    )
    assert evaluation.selected_family == selected_family
    fields = {item.field_code: item for item in evaluation.field_selection}
    for code in FAMILY_FIELDS['home']:
        expected = (
            FieldSelectionState.CANDIDATE_NOW if open_other_family else FieldSelectionState.INACTIVE
        )
        assert fields[code].selection_state is expected, code
        assert code not in evaluation.requirements.missing_required_now
    if selected_family is None:
        assert all(
            fields[code].selection_state is FieldSelectionState.CANDIDATE_NOW
            for code in FAMILY_FIELDS['motor']
        )
        assert not FAMILY_FIELDS['motor'].intersection(evaluation.requirements.missing_required_now)
        assert evaluation.unresolved_family_conflict == []
    else:
        assert {'vehicle.drivable', 'vehicle.damage_description'} <= set(
            evaluation.requirements.missing_required_now
        )
    if stored_status is FormStatus.PROPOSED:
        assert claim.form['claim.product_family'].status is FormStatus.PROPOSED


@pytest.mark.parametrize('policy_mode', ['disabled', 'observation'])
def test_open_family_candidates_do_not_recover_suppressed_rule_fields(policy_mode: str) -> None:
    rule_ids = frozenset({FAMILY_RULE_IDS['motor']})
    evaluator = BranchRuleEvaluator(
        model_family_judgment=True,
        disabled_rule_ids=rule_ids if policy_mode == 'disabled' else frozenset(),
        observation_rule_ids=rule_ids if policy_mode == 'observation' else frozenset(),
    )
    evaluation = evaluator.evaluate(make_claim(), latest_message='My car was damaged.')
    fields = {item.field_code: item for item in evaluation.field_selection}
    for code in FAMILY_FIELDS['motor']:
        assert fields[code].selection_state is FieldSelectionState.INACTIVE, code
        assert code not in evaluation.requirements.missing_required_now
    assert fields['property.address'].selection_state is FieldSelectionState.CANDIDATE_NOW


def test_unresolved_family_exposes_all_family_fields_without_making_them_required() -> None:
    context = v8_context(DESCRIPTION)
    claim = context.claim.model_copy(update={'incident_type': None, 'form': {}})
    assert resolve_turn_family(claim, None, DESCRIPTION).product_family is None
    assert context.runtime_policy is not None
    evaluation = context.runtime_policy.branch_evaluator(model_family_judgment=True).evaluate(
        claim, latest_message=DESCRIPTION, recomputation_reason='inv14'
    )
    assert evaluation.selected_family is None
    fields = {item.field_code: item for item in evaluation.field_selection}
    family_fields = frozenset().union(*FAMILY_FIELDS.values())
    assert family_fields
    for code in family_fields:
        assert fields[code].selection_state is FieldSelectionState.CANDIDATE_NOW, code
    assert not family_fields.intersection(evaluation.requirements.missing_required_now)
    assert not evaluation.requirements.ready
    plan = plan_model_turn(replace(context, claim=claim, branch_evaluation=evaluation))
    assert plan is not None and plan.route.model_required
    assert plan.field_contract is not None
    assert family_fields <= plan.field_contract.by_code.keys()
    assert claim.form == {} and claim.incident_type is None


@pytest.mark.parametrize('supported_quote', [True, False])
def test_model_can_save_family_and_damage_in_one_turn_but_cannot_forge_provenance(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    supported_quote: bool,
) -> None:
    provider = V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact(
                        'claim.product_family',
                        'motor',
                        FAMILY_QUOTE if supported_quote else 'I explicitly reported a motor claim',
                    ),
                    fact(
                        'vehicle.damage_description',
                        'Dented bumper',
                        'the bumper is dented' if supported_quote else 'the vehicle is destroyed',
                    ),
                ]
            )
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    created = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': 'inv14-new-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201, created.text
    initial = created.json()
    claim_id = initial['claim']['claim_id']
    assert initial['claim']['incident_type'] is None
    response = submit_message(
        client,
        CLAIMANT,
        claim_id,
        initial['session']['session_id'],
        revision=initial['claim']['revision'],
        key='inv14-message',
        text=DESCRIPTION,
    )
    assert response.status_code == 200, response.text
    assert response.json()['agent_message'] is not None, response.text
    assert response.json()['recovery'] is None
    assert len(provider.gateway.requests) == 1
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    expected_status = FormStatus.CONFIRMED if supported_quote else FormStatus.PROPOSED
    expected_source = FormSource.CLAIMANT if supported_quote else FormSource.INFERENCE
    for code, value in (
        ('claim.product_family', 'motor'),
        ('vehicle.damage_description', 'Dented bumper'),
    ):
        assert claim.form[code].value == value
        assert claim.form[code].status is expected_status
        assert claim.form[code].source is expected_source
    # The model's understood family opens the motor branch from the first turn
    # either way; the form field carries whether the claimant's words back it.
    assert claim.incident_type == 'motor'


def test_controlled_path_still_uses_its_existing_family_inference() -> None:
    context = v8_context(DESCRIPTION)
    claim = context.claim.model_copy(update={'incident_type': None, 'form': {}})
    assert infer_controlled_product_family(DESCRIPTION) is None
    evaluation = BranchRuleEvaluator().evaluate(claim, latest_message=DESCRIPTION)
    context = replace(
        context,
        claim=claim,
        branch_evaluation=evaluation,
        runtime_policy=None,
        runtime_configuration_snapshot=None,
    )
    fields = {item.field_code: item for item in evaluation.field_selection}
    assert fields['vehicle.damage_description'].selection_state is FieldSelectionState.INACTIVE
    proposal = ControlledAgent().propose_turn(context)
    assert not any(
        change.field_code in {'claim.product_family', 'vehicle.damage_description'}
        for change in proposal.form_changes
    )
    assert proposal.customer_next_step is not None
    assert proposal.customer_next_step.required_items == ['claim.product_family']
