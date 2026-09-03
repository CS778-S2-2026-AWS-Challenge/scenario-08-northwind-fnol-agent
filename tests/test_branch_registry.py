from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.branch_registry import (
    BranchRuleEvaluator,
    build_default_registry,
    claimant_projection_fields,
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
    CustomerNextStep,
    FieldSelectionState,
    FormSource,
    FormStatus,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    StructuredFormField,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
)

FIXED_TIME = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


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


def evaluation_record(
    claim: WorkingClaim,
    *,
    evaluation_id: str = 'brn_eval_1',
) -> BranchEvaluationRecord:
    result = BranchRuleEvaluator().evaluate(claim, recomputation_reason='test')
    return BranchEvaluationRecord(
        evaluation_id=evaluation_id,
        claim_id=claim.claim_id,
        session_id=claim.active_session_id,
        evaluated_against_claim_revision=claim.revision,
        resulting_claim_revision=claim.revision,
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
        status=BranchEvaluationStatus.APPLIED,
        created_at=FIXED_TIME,
    )


@pytest.mark.parametrize('family', ['motor', 'home', 'contents'])
def test_confirmed_family_activates_exactly_one_branch(family: str) -> None:
    claim = make_claim().model_copy(update={'form': {'incident.type': field(family)}})

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


def test_proposed_family_is_candidate_and_cannot_select_formal_family() -> None:
    claim = make_claim().model_copy(
        update={'form': {'incident.type': field('contents', FormStatus.PROPOSED)}}
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


def test_matching_proposed_form_keeps_inferred_claim_type_as_candidate() -> None:
    claim = make_claim(incident_type='contents').model_copy(
        update={'form': {'incident.type': field('contents', FormStatus.PROPOSED)}}
    )

    result = BranchRuleEvaluator().evaluate(claim)

    assert result.selected_family is None
    assert result.unresolved_family_conflict == []
    assert 'family.contents' in result.candidate_branches


def test_conflicting_authoritative_family_sources_require_resolution() -> None:
    claim = make_claim(incident_type='motor').model_copy(
        update={'form': {'incident.type': field('home')}}
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
                'incident.type': field('motor'),
                'parties.other_parties': field(False),
            }
        }
    )

    result = BranchRuleEvaluator().evaluate(claim)

    assert 'incident.collision' not in result.active_branches
    assert 'participant.another_party' not in result.active_branches


def test_confirm_action_uses_the_agent_action_enum_contract() -> None:
    claim = make_claim().model_copy(update={'form': {'incident.type': field('home')}})

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
    claim = make_claim().model_copy(update={'form': {'incident.type': field('motor')}})

    result = BranchRuleEvaluator().evaluate(claim)
    motor = next(item for item in result.branch_results if item.branch_id == 'family.motor')

    assert motor.rule_id == 'BR-FAMILY-MOTOR-001'
    assert motor.source_refs == ['msg_source']
    assert result.field_registry_version == FIELD_REGISTRY_VERSION
    assert result.branch_rules_version == 'vp-dynamic-form-branch-rules-v1'


def test_claimant_projection_excludes_inactive_and_system_owned_fields() -> None:
    claim = make_claim().model_copy(update={'form': {'incident.type': field('motor')}})
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
                'incident.type': field('motor'),
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
    record = evaluation_record(claim)
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
    original_evaluation = evaluation_record(claim, evaluation_id='brn_collision')
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
