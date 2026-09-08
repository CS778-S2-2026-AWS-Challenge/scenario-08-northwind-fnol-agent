from datetime import UTC, datetime
from pathlib import Path

import mongomock
import pytest

from backend.domain.branch_registry import (
    COMMON_FIELDS,
    FAMILY_FIELDS,
    BranchRuleEvaluator,
    build_default_registry,
    claimant_projection_fields,
    validate_registered_field_value,
)
from backend.domain.field_registry import FIELD_REGISTRY_VERSION, REGISTERED_FIELD_CODES
from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    BranchEvaluationRecord,
    BranchEvaluationStatus,
    Channel,
    ContentsItem,
    ContentsLossType,
    ContentsOwnership,
    Coverage,
    CustomerNextStep,
    CustomerSupport,
    FieldSelectionState,
    FormSource,
    FormStatus,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    StructuredFormField,
    Urgency,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.claims import _claimant_form

FIXED_TIME = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
MAPPING_DOCUMENT = Path(__file__).parents[1] / 'docs' / 'vp-field-branch-mapping.md'


def make_claim(*, revision: int = 1, incident_type: str | None = None) -> WorkingClaim:
    return WorkingClaim(
        claim_id='clm_branch',
        customer_id='cus_branch',
        revision=revision,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type=incident_type,
        active_session_id='ses_branch',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def field(value: object, status: FormStatus = FormStatus.CONFIRMED) -> StructuredFormField:
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        source_refs=['msg_source'],
        status=status,
        needed_for='current_action',
        updated_at=FIXED_TIME,
        updated_by={'actor_type': 'claimant', 'actor_id': 'cus_branch'},
    )


def contents_item(item_id: str = 'item_1') -> ContentsItem:
    return ContentsItem(
        item_id=item_id,
        description='Synthetic laptop',
        category='electronics',
        loss_type=ContentsLossType.DAMAGED,
        ownership=ContentsOwnership.OWNED,
        estimated_value={'amount': 1200.0, 'currency': 'NZD'},
        source=FormSource.CLAIMANT,
        source_refs=['msg_source'],
        status=FormStatus.PROPOSED,
        needed_for='later_action',
        confidence=0.8,
        updated_at=FIXED_TIME,
        updated_by={'actor_type': 'claimant', 'actor_id': 'cus_branch'},
    )


def test_registry_includes_minimum_home_fields_and_contents_is_a_separate_record() -> None:
    registry = build_default_registry()

    assert registry.field_registry_version == '5'
    assert registry.field_by_code['property.ongoing_risk'].value_type == 'enum'
    assert registry.field_by_code['property.habitable'].value_type == 'boolean'
    assert registry.branch_by_id['family.home'].fields >= {
        'property.ongoing_risk',
        'property.habitable',
    }
    assert registry.branch_by_id['family.contents'].fields == registry.branch_by_id[
        'family.motor'
    ].fields - {
        'authorities.police_report_reference',
        'authorities.emergency_services_notified',
        'vehicle.registration',
        'vehicle.damage_description',
        'vehicle.drivable',
    }


def test_working_claim_rejects_duplicate_contents_item_ids() -> None:
    with pytest.raises(ValueError, match='Contents item identifiers'):
        WorkingClaim.model_validate(
            make_claim().model_dump() | {'contents_items': [contents_item(), contents_item()]}
        )


def test_claimant_form_hides_system_owned_client_number() -> None:
    claim = make_claim().model_copy(
        update={
            'form': {
                'claimant.client_number': field('internal-123'),
                'incident.description': field('A synthetic loss.'),
            }
        }
    )

    projected = _claimant_form(FixtureRepository(), claim)

    assert 'claimant.client_number' not in projected
    assert 'incident.description' in projected


def test_claimant_contents_projection_hides_internal_assessment_metadata() -> None:
    from backend.services.claims import _claimant_contents_items

    claim = make_claim().model_copy(update={'contents_items': [contents_item()]})
    projected = _claimant_contents_items(FixtureRepository(), claim)

    assert projected[0].item_id == 'item_1'
    assert projected[0].source_refs == ['msg_source']
    assert not hasattr(projected[0], 'confidence')
    assert not hasattr(projected[0], 'updated_by')


def test_claimant_contents_projection_drops_non_public_source_references() -> None:
    from backend.services.claims import _claimant_contents_items

    item = contents_item().model_copy(
        update={'source_refs': ['msg_public', 'staff_action_1', 'ret_policy_1', 'field:secret']}
    )
    claim = make_claim().model_copy(update={'contents_items': [item]})

    projected = _claimant_contents_items(FixtureRepository(), claim)

    assert projected[0].source_refs == ['msg_public']


def test_contents_items_round_trip_through_fixture_and_mongo_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = make_claim().model_copy(update={'contents_items': [contents_item()]})
    session = SessionRecord(
        session_id='ses_branch',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    fixture_repository = FixtureRepository()
    mongo_repository = MongoDBRepository(mongomock.MongoClient(), 'contents_round_trip')
    # mongomock intentionally has no session/transaction implementation.  Keep
    # the repository's normal create_claim path and execute its atomic callback
    # without a session so this test still verifies Mongo document mapping and
    # model round-trip rather than silently dropping the persistence contract.
    monkeypatch.setattr(mongo_repository, '_atomic', lambda operation: operation(None))
    for repository in (fixture_repository, mongo_repository):
        repository.create_claim(claim, session)
        restored = repository.get_claim(claim.claim_id, claim.customer_id)
        assert restored is not None
        assert restored.revision == claim.revision
        assert restored.contents_items == claim.contents_items
        assert restored.contents_items[0].estimated_value is not None
        assert restored.contents_items[0].estimated_value.currency == 'NZD'


def evaluation_record(
    claim: WorkingClaim,
    *,
    evaluation_id: str = 'brn_eval_1',
    status: BranchEvaluationStatus = BranchEvaluationStatus.APPLIED,
) -> BranchEvaluationRecord:
    result = BranchRuleEvaluator().evaluate(claim, recomputation_reason='test')
    return BranchEvaluationRecord(
        evaluation_id=evaluation_id,
        claim_id=claim.claim_id,
        session_id=claim.active_session_id,
        evaluated_against_claim_revision=claim.revision,
        resulting_claim_revision=(
            claim.revision if status is BranchEvaluationStatus.APPLIED else None
        ),
        field_registry_version=result.field_registry_version,
        branch_rules_version=result.branch_rules_version,
        selected_family=result.selected_family,
        unresolved_family_conflict=result.unresolved_family_conflict,
        branch_results=result.branch_results,
        field_selection_results=result.field_selection,
        work_item_intents=result.work_item_intents,
        handoff_intents=result.handoff_intents,
        evidence_intents=result.evidence_intents,
        interruption_result=result.interruption_result,
        permitted_actions=result.permitted_actions,
        permitted_tools=result.permitted_tools,
        recomputation_reason=result.recomputation_reason,
        status=status,
        created_at=FIXED_TIME,
    )


@pytest.mark.parametrize('family', ['motor', 'home', 'contents'])
def test_confirmed_family_activates_exactly_one_branch(family: str) -> None:
    claim = make_claim().model_copy(update={'form': {'claim.product_family': field(family)}})

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family == family
    assert [item for item in result.active_branches if item.startswith('family.')] == [
        f'family.{family}'
    ]
    assert result.unresolved_family_conflict == []
    incident_type = next(
        item for item in result.field_selection if item.field_code == 'incident.type'
    )
    assert incident_type.selection_state.value == 'candidate_now'


def test_vp_mapping_document_covers_every_executable_field_once() -> None:
    text = MAPPING_DOCUMENT.read_text(encoding='utf-8')
    registry = build_default_registry()
    mapped_codes = [
        line.split('|')[1].strip().strip('`')
        for line in text.splitlines()
        if line.startswith('| `') and line.count('|') >= 8
    ]

    assert registry.field_codes == REGISTERED_FIELD_CODES
    assert len(mapped_codes) == len(REGISTERED_FIELD_CODES)
    assert set(mapped_codes) == REGISTERED_FIELD_CODES
    assert COMMON_FIELDS | FAMILY_FIELDS['motor'] | FAMILY_FIELDS['home'] == REGISTERED_FIELD_CODES
    assert FAMILY_FIELDS['contents'] == frozenset()


def test_contents_mapping_declares_independent_record_boundary() -> None:
    text = MAPPING_DOCUMENT.read_text(encoding='utf-8')

    assert '`WorkingClaim.contents_items`' in text
    assert 'not by flattened form fields' in text
    assert 'ClaimantContentsItem' in text


def test_proposed_family_is_candidate_and_cannot_select_formal_family() -> None:
    claim = make_claim().model_copy(
        update={'form': {'claim.product_family': field('contents', FormStatus.PROPOSED)}}
    )

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family is None
    assert 'family.contents' in result.candidate_branches
    assert 'family.contents' not in result.active_branches


@pytest.mark.parametrize('family', ['motor', 'home', 'contents'])
def test_canonical_claim_type_selects_family_when_form_is_empty(family: str) -> None:
    claim = make_claim(incident_type=family)

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family == family
    selected = next(item for item in result.branch_results if item.branch_id == f'family.{family}')
    assert selected.source_refs == [f'claim:{claim.claim_id}:incident_type']


@pytest.mark.parametrize(
    ('family', 'subtype', 'branch_id', 'rule_id'),
    [
        ('motor', 'collision', 'incident.collision', 'BR-COLLISION-001'),
        ('home', 'fire', 'mitigation.emergency', 'BR-MITIGATION-001'),
        ('home', 'water', 'mitigation.emergency', 'BR-MITIGATION-001'),
        ('contents', 'theft', 'contents.theft', 'BR-THEFT-001'),
    ],
)
def test_confirmed_incident_subtype_activates_its_additive_branch(
    family: str,
    subtype: str,
    branch_id: str,
    rule_id: str,
) -> None:
    claim = make_claim(incident_type=family).model_copy(
        update={'form': {'incident.type': field(subtype)}}
    )

    result = BranchRuleEvaluator().evaluate(claim)
    branch = next(item for item in result.branch_results if item.branch_id == branch_id)

    assert result.selected_family == family
    assert branch.status == 'active'
    assert branch.rule_id == rule_id
    assert branch.source_refs == ['msg_source']


def test_incident_subtype_cannot_select_a_product_family() -> None:
    claim = make_claim().model_copy(update={'form': {'incident.type': field('collision')}})

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family is None
    assert 'family.motor' not in result.active_branches
    assert 'incident.collision' in result.active_branches


def test_canonical_family_remains_authoritative_with_matching_proposal() -> None:
    claim = make_claim(incident_type='contents').model_copy(
        update={'form': {'claim.product_family': field('contents', FormStatus.PROPOSED)}}
    )

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family == 'contents'
    assert result.unresolved_family_conflict == []
    assert 'family.contents' not in result.candidate_branches


def test_conflicting_authoritative_family_sources_require_resolution() -> None:
    claim = make_claim(incident_type='motor').model_copy(
        update={'form': {'claim.product_family': field('home')}}
    )

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family is None
    assert result.unresolved_family_conflict == ['home', 'motor']


def test_conflicting_family_candidates_use_shared_fields_only() -> None:
    result = BranchRuleEvaluator().evaluate(
        make_claim(),
        latest_message='My car was damaged and my laptop was stolen.',
        trigger_source_refs=['msg_conflict'],
    )

    assert result.selected_family is None
    assert set(result.unresolved_family_conflict) == {'motor', 'contents'}
    assert result.active_branches == []
    vehicle = next(
        item for item in result.field_selection if item.field_code == 'vehicle.registration'
    )
    assert vehicle.selection_state.value == 'inactive'


def test_false_other_party_value_does_not_activate_collision_branches() -> None:
    claim = make_claim().model_copy(
        update={
            'form': {
                'claim.product_family': field('motor'),
                'parties.other_parties': field(False),
            }
        }
    )

    result = BranchRuleEvaluator().evaluate(claim)

    assert 'incident.collision' not in result.active_branches
    assert 'participant.another_party' not in result.active_branches


def test_confirm_action_uses_the_agent_action_enum_contract() -> None:
    claim = make_claim().model_copy(update={'form': {'claim.product_family': field('home')}})

    result = BranchRuleEvaluator().evaluate(claim, current_action=AgentAction.CONFIRM)

    required = {
        item.field_code
        for item in result.field_selection
        if item.selection_state.value == 'required_now'
    }
    assert required == {'incident.description', 'incident.location', 'incident.occurred_at'}


def test_runtime_registry_excludes_design_only_and_separate_record_codes() -> None:
    registry = build_default_registry()

    assert registry.field_codes == REGISTERED_FIELD_CODES
    assert registry.field_registry_version == FIELD_REGISTRY_VERSION
    assert 'contents.items' not in registry.field_codes
    assert 'other_party.contact' not in registry.field_codes
    assert 'motor.evidence_refs' not in registry.field_codes


def test_branch_results_retain_rule_and_source_coordinates() -> None:
    claim = make_claim().model_copy(update={'form': {'claim.product_family': field('motor')}})

    result = BranchRuleEvaluator().evaluate(claim)
    motor = next(item for item in result.branch_results if item.branch_id == 'family.motor')

    assert motor.rule_id == 'BR-FAMILY-MOTOR-001'
    assert motor.source_refs == ['msg_source']
    assert result.field_registry_version == FIELD_REGISTRY_VERSION
    assert result.branch_rules_version == 'vp-dynamic-form-branch-rules-v1'


def test_collision_correction_suspends_previous_branch_with_both_sources() -> None:
    previous_claim = make_claim(incident_type='motor').model_copy(
        update={'form': {'incident.type': field('collision')}}
    )
    previous = evaluation_record(previous_claim)
    corrected_subtype = field('other').model_copy(update={'source_refs': ['msg_correction']})
    corrected_claim = previous_claim.model_copy(
        update={'revision': 2, 'form': {'incident.type': corrected_subtype}}
    )

    result = BranchRuleEvaluator().evaluate(
        corrected_claim,
        previous_evaluation=previous,
        trigger_source_refs=['msg_correction'],
        recomputation_reason='form_updated',
    )
    collision = next(
        item for item in result.branch_results if item.branch_id == 'incident.collision'
    )

    assert collision.status == 'suspended'
    assert collision.rule_id == 'BR-COLLISION-001'
    assert collision.source_refs == ['msg_correction', 'msg_source']
    assert 'incident.collision' in result.suspended_branches
    assert 'incident.collision' not in (
        result.active_branches + result.candidate_branches + result.exited_branches
    )
    assert (
        next(
            item for item in previous.branch_results if item.branch_id == 'incident.collision'
        ).status
        == 'active'
    )


def test_other_party_correction_exits_previous_branch_without_rewriting_history() -> None:
    previous_claim = make_claim(incident_type='motor').model_copy(
        update={'form': {'parties.other_parties': field(True)}}
    )
    previous = evaluation_record(previous_claim)
    corrected_party = field(False).model_copy(update={'source_refs': ['msg_party_correction']})
    corrected_claim = previous_claim.model_copy(
        update={'revision': 2, 'form': {'parties.other_parties': corrected_party}}
    )

    result = BranchRuleEvaluator().evaluate(
        corrected_claim,
        previous_evaluation=previous,
        trigger_source_refs=['msg_party_correction'],
        recomputation_reason='form_updated',
    )
    participant = next(
        item for item in result.branch_results if item.branch_id == 'participant.another_party'
    )

    assert participant.status == 'exited'
    assert participant.rule_id == 'BR-PARTICIPANT-OTHER-001'
    assert participant.source_refs == ['msg_party_correction', 'msg_source']
    assert 'participant.another_party' in result.exited_branches
    assert (
        next(
            item
            for item in previous.branch_results
            if item.branch_id == 'participant.another_party'
        ).status
        == 'active'
    )


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_repository_history_reconciles_branch_corrections_for_both_profiles(
    repository_kind: str,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(mongomock.MongoClient(), 'branch_transitions')
        mongo_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo_repository
    base = make_claim()
    session = SessionRecord(
        session_id='ses_branch',
        claim_id=base.claim_id,
        customer_id=base.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(base, session)
    collision_claim = base.model_copy(
        update={
            'revision': 2,
            'form': {'incident.type': field('collision')},
        }
    )
    first_evaluation = build_applied_branch_evaluation(
        collision_claim,
        repository=repository,
        recomputation_reason='form_updated',
        trigger_source_refs=['msg_source'],
        created_at=FIXED_TIME,
    )
    repository.save_claim(collision_claim, 1, first_evaluation)
    corrected_claim = collision_claim.model_copy(
        update={
            'revision': 3,
            'form': {
                'incident.type': field('other').model_copy(
                    update={'source_refs': ['msg_correction']}
                )
            },
        }
    )
    second_evaluation = build_applied_branch_evaluation(
        corrected_claim,
        repository=repository,
        recomputation_reason='form_updated',
        trigger_source_refs=['msg_correction'],
        created_at=FIXED_TIME,
    )
    repository.save_claim(corrected_claim, 2, second_evaluation)

    history = sorted(
        repository.list_branch_evaluations(base.claim_id, base.customer_id),
        key=lambda record: record.resulting_claim_revision or 0,
    )
    first_collision = next(
        item for item in history[0].branch_results if item.branch_id == 'incident.collision'
    )
    current_collision = next(
        item for item in history[1].branch_results if item.branch_id == 'incident.collision'
    )
    assert first_collision.status == 'active'
    assert current_collision.status == 'suspended'
    assert current_collision.source_refs == ['msg_correction', 'msg_source']
    assert history[0].resulting_claim_revision == 2
    assert history[1].resulting_claim_revision == 3


@pytest.mark.parametrize(
    ('message', 'support_need', 'reason'),
    [
        ('I need to speak to a person.', 'human_requested', 'explicit_human_request'),
        ('I need an interpreter to continue.', 'accessibility_required', 'accessibility_need'),
        ('I am overwhelmed and cannot cope.', 'distress', 'distress'),
    ],
)
def test_claimant_support_message_enters_deterministic_branch_boundary(
    message: str,
    support_need: str,
    reason: str,
) -> None:
    result = BranchRuleEvaluator().evaluate(
        make_claim(incident_type='motor'),
        latest_message=message,
        trigger_source_refs=['msg_support'],
    )
    support = next(item for item in result.branch_results if item.branch_id == 'human_support')

    assert support.status == 'candidate'
    assert support.source_refs == ['msg_support']
    assert result.handoff_intents == [
        {
            'type': 'human_support',
            'support_need': support_need,
            'required': True,
            'source_refs': ['msg_support'],
        }
    ]
    assert result.interruption_result == {'control': 'handoff', 'reason': reason}


@pytest.mark.parametrize(
    'message',
    [
        'I do not need to speak to a person.',
        'Another person saw the collision.',
        'I am not distressed and can continue.',
    ],
)
def test_non_support_wording_does_not_enter_handoff_boundary(message: str) -> None:
    result = BranchRuleEvaluator().evaluate(
        make_claim(incident_type='motor'),
        latest_message=message,
        trigger_source_refs=['msg_no_support'],
    )

    assert all(item.branch_id != 'human_support' for item in result.branch_results)
    assert result.handoff_intents == []
    assert result.interruption_result == {'control': 'continue'}


def test_claimant_projection_excludes_inactive_and_system_owned_fields() -> None:
    claim = make_claim().model_copy(update={'form': {'claim.product_family': field('motor')}})
    evaluation = evaluation_record(claim)

    projected = claimant_projection_fields(evaluation)
    projected_codes = {item.field_code for item in projected}
    client_number = next(
        item
        for item in evaluation.field_selection_results
        if item.field_code == 'claimant.client_number'
    )

    assert client_number.selection_state is FieldSelectionState.SYSTEM_OWNED
    assert (
        build_default_registry().field_by_code['claimant.client_number'].claimant_visible is False
    )
    assert 'vehicle.registration' in projected_codes
    assert 'property.address' not in projected_codes
    assert 'claimant.client_number' not in projected_codes


def test_selection_state_is_separate_from_value_state_and_pending_evidence() -> None:
    claim = make_claim().model_copy(
        update={
            'form': {
                'incident.type': field('collision'),
                'claim.product_family': field('motor'),
                'incident.description': field('A rear-end collision.'),
                'authorities.police_report_reference': field(None, FormStatus.PENDING_GENERATION),
            }
        }
    )
    result = BranchRuleEvaluator().evaluate(
        claim,
        current_action=AgentAction.CREATE_CLAIM,
    )

    police = next(
        item
        for item in result.field_selection
        if item.field_code == 'authorities.police_report_reference'
    )
    assert police.selection_state.value == 'pending_later'
    assert police.value_state is FormStatus.PENDING_GENERATION

    description = next(
        item for item in result.field_selection if item.field_code == 'incident.description'
    )
    assert description.value_state is FormStatus.CONFIRMED
    assert description.selection_state.value == 'candidate_now'


def test_registered_field_value_contracts_reject_incompatible_shapes() -> None:
    validate_registered_field_value('parties.other_parties', True)
    validate_registered_field_value('incident.type', 'collision')
    validate_registered_field_value('claim.product_family', 'motor')

    with pytest.raises(ValueError, match='boolean'):
        validate_registered_field_value('parties.other_parties', ['driver'])
    with pytest.raises(ValueError, match='Allowed values'):
        validate_registered_field_value('incident.type', 'motor')
    with pytest.raises(ValueError, match='Allowed values'):
        validate_registered_field_value('claim.product_family', 'collision')


def test_safety_human_and_review_state_emit_registered_branch_results() -> None:
    claim = make_claim(incident_type='motor').model_copy(
        update={
            'claim_state': make_claim().claim_state.model_copy(
                update={
                    'urgency': Urgency.IMMEDIATE_SAFETY_RISK,
                    'customer_support': CustomerSupport.HUMAN_REQUESTED,
                    'coverage': Coverage.REVIEW_REQUIRED,
                    'workflow_state': WorkflowState.PROFESSIONAL_REVIEW,
                }
            )
        }
    )

    result = BranchRuleEvaluator().evaluate(claim)
    branches = {item.branch_id: item for item in result.branch_results}

    assert branches['safety.injury_or_danger'].rule_id == 'BR-SAFETY-001'
    assert branches['safety.injury_or_danger'].status == 'active'
    assert branches['human_support'].rule_id == 'BR-HUMAN-SUPPORT-001'
    assert branches['human_support'].status == 'active'
    assert branches['professional_review'].rule_id == 'BR-REVIEW-001'
    assert branches['professional_review'].status == 'active'
    assert all(
        branches[branch_id].source_refs
        for branch_id in (
            'safety.injury_or_danger',
            'human_support',
            'professional_review',
        )
    )
    assert {intent['type'] for intent in result.handoff_intents} == {
        'urgent_support',
        'human_support',
        'professional_review',
    }


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_evaluation_payload_is_immutable_in_both_repositories(repository_kind: str) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(mongomock.MongoClient(), 'branch_immutable')
        mongo_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo_repository
    claim = make_claim()
    session = SessionRecord(
        session_id='ses_branch',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    record = evaluation_record(claim, status=BranchEvaluationStatus.EVALUATED)
    repository.save_branch_evaluation(record, claim.customer_id)

    rewritten = record.model_copy(
        update={
            'selected_family': 'home',
            'branch_results': [],
            'field_selection_results': [],
        }
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_branch_evaluation(rewritten, claim.customer_id)

    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == [record]


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
@pytest.mark.parametrize('evaluation_revision', [1, 99])
def test_standalone_repository_rejects_applied_evaluation(
    repository_kind: str,
    evaluation_revision: int,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(mongomock.MongoClient(), 'branch_unattached')
        mongo_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo_repository
    claim = make_claim()
    session = SessionRecord(
        session_id='ses_branch',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    record = evaluation_record(claim.model_copy(update={'revision': evaluation_revision}))

    with pytest.raises(
        ValueError,
        match='must be persisted with their Claim mutation',
    ):
        repository.save_branch_evaluation(record, claim.customer_id)

    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == []


def test_mongodb_agent_turn_persists_evaluation_with_resulting_claim_atomically() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'branch_agent_turn')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    claim = make_claim()
    session = SessionRecord(
        session_id='ses_branch',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    updated_claim = claim.model_copy(update={'revision': 2})
    updated_session = session.model_copy(update={'context_revision': 2})
    claimant_message = MessageRecord(
        message_id='msg_claimant',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={'type': 'text', 'text': 'My home was damaged.'},
        created_at=FIXED_TIME,
    )
    agent_message = claimant_message.model_copy(
        update={
            'message_id': 'msg_agent',
            'actor': ActorType.AGENT,
            'in_reply_to': claimant_message.message_id,
        }
    )
    decision = AgentDecisionRecord(
        decision_id='dec_branch',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        trigger_message_id=claimant_message.message_id,
        action=AgentAction.ASK,
        reason_codes=['TEST'],
        customer_reason='Continue.',
        customer_response='Continue.',
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='agent',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        resulting_revision=2,
        created_at=FIXED_TIME,
    )
    record = evaluation_record(updated_claim)
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/agent-turn',
        key='branch-agent-turn',
        request_fingerprint='branch-agent-turn-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=claimant_message.message_id,
        agent_message_id=agent_message.message_id,
        decision_id=decision.decision_id,
    )

    repository.save_agent_turn(
        updated_claim,
        1,
        updated_session,
        claimant_message,
        agent_message,
        decision,
        idempotency,
        branch_evaluation=record,
    )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == [record]


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_evaluation_identity_conflict_cannot_partially_advance_claim(
    repository_kind: str,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(mongomock.MongoClient(), 'branch_atomic_conflict')
        mongo_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo_repository
    claim = make_claim()
    session = SessionRecord(
        session_id='ses_branch',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    original_evaluation = evaluation_record(
        claim,
        evaluation_id='brn_collision',
        status=BranchEvaluationStatus.EVALUATED,
    )
    repository.save_branch_evaluation(original_evaluation, claim.customer_id)
    updated_claim = claim.model_copy(update={'revision': 2})
    colliding_evaluation = evaluation_record(updated_claim, evaluation_id='brn_collision')

    with pytest.raises(IdempotencyConflict):
        repository.save_claim(
            updated_claim,
            expected_revision=1,
            branch_evaluation=colliding_evaluation,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == [
        original_evaluation
    ]
