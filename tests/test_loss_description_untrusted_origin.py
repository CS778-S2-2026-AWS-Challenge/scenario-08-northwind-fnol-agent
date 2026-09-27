"""A confirmed vehicle-damage or contents-item record without a trustworthy current
assertion must not silently drop the loss.description requirement.

trusted_origin_assertion is the one predicate both branch_registry._required_set and
turn_reducer's derivation share. Runtime never derives loss.description without a
current assertion carrying its own source refs -- but before this fix, _required_set
stopped requiring the field from status alone, so a legacy/source-less confirmed
record left it neither derived nor required. These tests cover exactly that gap: no
current assertion at all, and a current assertion recorded with an empty source_refs.
"""

from datetime import UTC, datetime

import pytest

from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.field_registry import trusted_origin_assertion
from backend.domain.models import (
    AssertionRelation,
    ContentsItemAssertion,
    FactAssertion,
    FormStatus,
)
from tests.test_branch_registry import contents_item, field, make_claim

FIXED_TIME = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def test_trusted_origin_assertion_rejects_missing_or_source_less_current_assertion() -> None:
    assert trusted_origin_assertion(None, []) is None
    assert trusted_origin_assertion('ast_missing', []) is None
    source_less = FactAssertion(
        assertion_id='ast_1',
        normalized_value='x',
        source_refs=[],
        status=FormStatus.CONFIRMED,
        created_at=FIXED_TIME,
    )
    assert trusted_origin_assertion('ast_1', [source_less]) is None
    sourced = source_less.model_copy(update={'source_refs': ['msg_1']})
    assert trusted_origin_assertion('ast_1', [sourced]) is sourced


@pytest.mark.parametrize('has_current_assertion', [False, True])
def test_motor_still_requires_loss_description_without_a_trusted_vehicle_damage_origin(
    has_current_assertion: bool,
) -> None:
    # field() (the shared test helper) produces exactly the legacy shape: confirmed,
    # but current_assertion_id is None and assertions is empty -- no current assertion.
    vehicle_damage = field('Bumper damaged')
    if has_current_assertion:
        # A current assertion that itself carries no source refs -- still not trustworthy.
        assertion = FactAssertion(
            assertion_id='ast_damage',
            normalized_value='Bumper damaged',
            source_refs=[],
            status=FormStatus.CONFIRMED,
            relation=AssertionRelation.INITIAL,
            created_at=FIXED_TIME,
        )
        vehicle_damage = vehicle_damage.model_copy(
            update={'assertions': [assertion], 'current_assertion_id': assertion.assertion_id}
        )
    claim = make_claim(incident_type='motor').model_copy(
        update={
            'form': {
                'claim.product_family': field('motor'),
                'incident.description': field('A crash'),
                'vehicle.damage_description': vehicle_damage,
            }
        }
    )
    result = BranchRuleEvaluator().evaluate(claim)
    assert 'loss.description' in result.requirements.missing_required_now


def test_motor_stops_requiring_loss_description_once_the_vehicle_damage_origin_is_trusted() -> None:
    assertion = FactAssertion(
        assertion_id='ast_damage',
        normalized_value='Bumper damaged',
        source_refs=['msg_damage'],
        status=FormStatus.CONFIRMED,
        relation=AssertionRelation.INITIAL,
        created_at=FIXED_TIME,
    )
    vehicle_damage = field('Bumper damaged').model_copy(
        update={'assertions': [assertion], 'current_assertion_id': assertion.assertion_id}
    )
    claim = make_claim(incident_type='motor').model_copy(
        update={
            'form': {
                'claim.product_family': field('motor'),
                'incident.description': field('A crash'),
                'vehicle.damage_description': vehicle_damage,
            }
        }
    )
    result = BranchRuleEvaluator().evaluate(claim)
    assert 'loss.description' not in result.requirements.missing_required_now


@pytest.mark.parametrize('has_current_assertion', [False, True])
def test_contents_still_requires_loss_description_without_a_trusted_item_origin(
    has_current_assertion: bool,
) -> None:
    # contents_item() defaults to PROPOSED; confirm it here without giving it a current
    # assertion, reproducing the same legacy shape as the motor case above.
    item = contents_item().model_copy(update={'status': FormStatus.CONFIRMED})
    if has_current_assertion:
        assertion = ContentsItemAssertion(
            assertion_id='ast_item',
            description=item.description,
            source_refs=[],
            status=FormStatus.CONFIRMED,
            relation=AssertionRelation.INITIAL,
            created_at=FIXED_TIME,
        )
        item = item.model_copy(
            update={'assertions': [assertion], 'current_assertion_id': assertion.assertion_id}
        )
    claim = make_claim(incident_type='contents').model_copy(
        update={
            'form': {
                'claim.product_family': field('contents'),
                'incident.description': field('A theft'),
            },
            'contents_items': [item],
        }
    )
    result = BranchRuleEvaluator().evaluate(claim)
    assert 'loss.description' in result.requirements.missing_required_now


def test_contents_stops_requiring_loss_description_once_an_item_origin_is_trusted() -> None:
    assertion = ContentsItemAssertion(
        assertion_id='ast_item',
        description='Synthetic laptop',
        source_refs=['msg_item'],
        status=FormStatus.CONFIRMED,
        relation=AssertionRelation.INITIAL,
        created_at=FIXED_TIME,
    )
    item = contents_item().model_copy(
        update={
            'status': FormStatus.CONFIRMED,
            'assertions': [assertion],
            'current_assertion_id': assertion.assertion_id,
        }
    )
    claim = make_claim(incident_type='contents').model_copy(
        update={
            'form': {
                'claim.product_family': field('contents'),
                'incident.description': field('A theft'),
            },
            'contents_items': [item],
        }
    )
    result = BranchRuleEvaluator().evaluate(claim)
    assert 'loss.description' not in result.requirements.missing_required_now
