"""Registry leaves, deadlines and cross-turn correction acceptance for v8."""

import pytest

from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.field_registry import needs_confirmation
from backend.domain.models import AgentAction, FieldSelectionState, FormSource, FormStatus
from backend.services.branching import build_applied_branch_evaluation
from backend.services.turn_field_contract import compile_turn_field_contract
from tests.test_branch_registry import contents_item, field, make_claim


def test_injury_leaves_have_distinct_collection_deadlines() -> None:
    claim = make_claim(incident_type='motor').model_copy(
        update={
            'form': {
                'incident.injury_or_danger': field(True),
                'incident.description': field('A crash'),
            }
        }
    )
    evaluator = BranchRuleEvaluator()
    result = evaluator.evaluate(claim)
    assert result.requirements.next_required_item == 'injury.persons_affected'
    assert result.requirements.missing_by_branch[0] == {
        'branch': 'injury.details',
        'fields': ['injury.persons_affected', 'injury.severity_reported'],
    }
    assert {'injury.persons_affected', 'injury.severity_reported'} <= set(
        result.requirements.missing_required_now
    )
    assert 'injury.medical_attention' not in result.requirements.missing_required_now
    assert evaluator._required_set('motor', result.active_branches, 'before_creation') == {
        'injury.medical_attention'
    }
    inactive = evaluator.evaluate(make_claim(incident_type='motor'))
    assert all(
        item.selection_state is FieldSelectionState.INACTIVE
        for item in inactive.field_selection
        if item.field_code.startswith('injury.')
    )


@pytest.mark.parametrize('policy', ['enabled', 'disabled', 'observation'])
def test_weak_injury_prepares_candidate_fields_without_requiring_or_authorising_them(
    policy: str,
) -> None:
    rule_id = 'BR-INJURY-DETAILS-001'
    evaluator = BranchRuleEvaluator(
        disabled_rule_ids=frozenset({rule_id}) if policy == 'disabled' else frozenset(),
        observation_rule_ids=frozenset({rule_id}) if policy == 'observation' else frozenset(),
    )
    claim = make_claim(incident_type='motor')
    result = evaluator.evaluate(claim, latest_message='Possible injury details are not clear yet.')
    injury = next(item for item in result.branch_results if item.branch_id == 'injury.details')
    codes = {'injury.persons_affected', 'injury.severity_reported', 'injury.medical_attention'}
    contract = compile_turn_field_contract(result, evaluator.registry)
    selections = {item.field_code: item.selection_state for item in result.field_selection}
    assert not codes.intersection(result.requirements.missing_required_now)
    assert not codes.intersection(result.requirements.recorded)
    assert 'injury.details' not in result.active_branches
    assert claim.form == {}
    if policy == 'enabled':
        assert set(injury.registered_fields) == codes
        assert codes <= set(contract.by_code)
        assert all(selections[code] is FieldSelectionState.CANDIDATE_NOW for code in codes)
    else:
        assert injury.registered_fields == []
        assert not codes.intersection(contract.by_code)
        assert all(selections[code] is FieldSelectionState.INACTIVE for code in codes)


def test_required_selection_matches_requirements_with_rule_disabled() -> None:
    claim = make_claim(incident_type='home').model_copy(
        update={
            'form': {
                'incident.type': field('collision'),
            }
        }
    )
    for disabled in (frozenset(), frozenset({'BR-COLLISION-001'})):
        result = BranchRuleEvaluator(disabled_rule_ids=disabled).evaluate(claim)
        selected = {
            item.field_code
            for item in result.field_selection
            if item.selection_state is FieldSelectionState.REQUIRED_NOW
        }
        assert selected == set(result.requirements.missing_required_now)
        assert ('parties.other_parties' in selected) == (not disabled)


def test_recorded_theft_leaf_survives_silent_turn_but_not_correction_or_old_rules() -> None:
    original = make_claim(incident_type='contents').model_copy(
        update={
            'form': {
                'incident.type': field('theft'),
                'theft.entry_context': field('unknown', FormStatus.PROPOSED),
            }
        }
    )
    previous = build_applied_branch_evaluation(original, recomputation_reason='test')
    silent = original.model_copy(
        update={'form': {'theft.entry_context': original.form['theft.entry_context']}}
    )
    evaluator = BranchRuleEvaluator()
    retained = evaluator.evaluate(silent, previous_evaluation=previous)
    assert 'contents.theft' in retained.active_branches
    assert 'theft.entry_context' in retained.requirements.recorded
    renewed_candidate = evaluator.evaluate(
        silent, latest_message='the theft', previous_evaluation=previous
    )
    assert 'contents.theft' in renewed_candidate.active_branches
    corrected = silent.model_copy(update={'form': {**silent.form, 'incident.type': field('water')}})
    assert (
        'contents.theft'
        in evaluator.evaluate(corrected, previous_evaluation=previous).suspended_branches
    )
    old = previous.model_copy(update={'branch_rules_version': 'vp-dynamic-form-branch-rules-v1'})
    assert (
        'contents.theft' not in evaluator.evaluate(silent, previous_evaluation=old).active_branches
    )


def test_proposed_contents_are_recorded_not_missing() -> None:
    claim = make_claim(incident_type='contents').model_copy(
        update={'contents_items': [contents_item()]}
    )
    result = BranchRuleEvaluator().evaluate(claim)
    assert 'contents.items' in result.requirements.recorded
    assert 'contents.items' not in result.requirements.missing_required_now


def test_confirmation_depends_on_source_and_authority_not_normalisation() -> None:
    accepted = field('2026-09-20')
    assert not needs_confirmation(accepted, 'incident.occurred_at')
    assert needs_confirmation(
        accepted.model_copy(update={'source': FormSource.INFERENCE}), 'incident.occurred_at'
    )
    assert needs_confirmation(
        accepted.model_copy(update={'status': FormStatus.DISPUTED}), 'incident.occurred_at'
    )
    assert not needs_confirmation(field(True), 'incident.injury_or_danger')


def test_before_creation_leaves_become_next_question_after_current_collection() -> None:
    claim = make_claim(incident_type='motor').model_copy(
        update={
            'form': {
                'incident.description': field('A collision injured my passenger'),
                'incident.injury_or_danger': field(True),
                'injury.persons_affected': field(['passenger']),
                'injury.severity_reported': field('minor'),
                'incident.occurred_at': field('this morning'),
                'incident.location': field('Auckland'),
                'loss.description': field('bumper damage'),
                'vehicle.damage_description': field('bumper damage'),
                'vehicle.drivable': field(True),
            }
        }
    )
    evaluator = BranchRuleEvaluator()
    result = evaluator.evaluate(claim)
    assert result.requirements.next_required_item == 'injury.medical_attention'
    assert not result.requirements.ready
    creating = evaluator.evaluate(claim, current_action=AgentAction.CREATE_CLAIM)
    assert 'injury.medical_attention' in creating.requirements.missing_required_now
    completed = claim.model_copy(
        update={'form': {**claim.form, 'injury.medical_attention': field('none')}}
    )
    assert evaluator.evaluate(completed).requirements.ready


def test_question_groups_prioritise_new_fact_branch_then_family_then_common() -> None:
    claim = make_claim(incident_type='home').model_copy(
        update={'form': {'incident.type': field('theft')}}
    )
    evaluation = BranchRuleEvaluator().evaluate(claim)
    assert [item['branch'] for item in evaluation.requirements.missing_by_branch] == [
        'contents.theft',
        'family.home',
        'common',
    ]
    assert evaluation.requirements.missing_by_branch[0]['fields'] == ['theft.entry_context']
    previous = build_applied_branch_evaluation(claim, recomputation_reason='test')
    later = BranchRuleEvaluator().evaluate(claim, previous_evaluation=previous)
    assert [item['branch'] for item in later.requirements.missing_by_branch] == [
        'family.home',
        'contents.theft',
        'common',
    ]
