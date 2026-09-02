from datetime import UTC, datetime

from backend.domain.branch_registry import BranchRuleEvaluator, build_default_registry
from backend.domain.models import (
    BranchEvaluationRecord,
    BranchEvaluationStatus,
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    ResponsibleParty,
    SessionRecord,
    StructuredFormField,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository


def make_claim() -> WorkingClaim:
    timestamp = datetime.now(UTC)
    return WorkingClaim(
        claim_id='clm_branch',
        customer_id='cus_branch',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def field(value: object, status: FormStatus = FormStatus.CONFIRMED) -> StructuredFormField:
    timestamp = datetime.now(UTC)
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        status=status,
        needed_for='current_action',
        updated_at=timestamp,
        updated_by={'actor_type': 'claimant', 'actor_id': 'cus_branch'},
    )


def test_registry_keeps_family_exclusive_and_shared_fields_single() -> None:
    claim = make_claim().model_copy(
        update={
            'form': {
                'incident.type': field('motor'),
                'incident.description': field('A car hit my vehicle.'),
            }
        }
    )
    result = BranchRuleEvaluator().evaluate(claim, latest_message='A car hit my vehicle.')

    assert result.selected_family == 'motor'
    assert result.unresolved_family_conflict == []
    assert result.active_branches[0] == 'family.motor'
    assert 'family.home' in result.exited_branches
    assert 'family.contents' in result.exited_branches
    assert sum(item.field_code == 'incident.description' for item in result.field_selection) == 1


def test_conflicting_family_candidates_are_not_activated() -> None:
    claim = make_claim()
    result = BranchRuleEvaluator().evaluate(
        claim,
        latest_message='My car was damaged and my laptop was stolen.',
    )

    assert result.selected_family is None
    assert set(result.unresolved_family_conflict) == {'motor', 'contents'}
    assert result.active_branches == []


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
        latest_message='The police report is pending and will be provided later.',
        current_action='create_claim',
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


def test_evaluation_record_is_claim_scoped_and_status_can_advance() -> None:
    repository = FixtureRepository()
    claim = make_claim()
    timestamp = datetime.now(UTC)
    repository.create_claim(
        claim,
        SessionRecord(
            session_id='ses_branch',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            started_at=timestamp,
            last_active_at=timestamp,
        ),
    )
    evaluated = BranchRuleEvaluator().evaluate(claim, latest_message='A car was damaged.')
    record = BranchEvaluationRecord(
        evaluation_id='brn_eval_1',
        claim_id=claim.claim_id,
        session_id='ses_branch',
        evaluated_against_claim_revision=evaluated.evaluated_against_claim_revision,
        resulting_claim_revision=claim.revision,
        registry_version=evaluated.registry_version,
        selected_family=evaluated.selected_family,
        branch_results=evaluated.branch_results,
        field_selection_results=evaluated.field_selection,
        recomputation_reason='test',
        status=BranchEvaluationStatus.EVALUATED,
        created_at=timestamp,
    )
    repository.save_branch_evaluation(record, claim.customer_id)
    applied = record.model_copy(update={'status': BranchEvaluationStatus.APPLIED})
    repository.save_branch_evaluation(applied, claim.customer_id)

    stored = repository.list_branch_evaluations(claim.claim_id, claim.customer_id)
    assert stored == [applied]
    assert build_default_registry().version == evaluated.registry_version
