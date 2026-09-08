from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.domain.models import SignalDecisionRecord, SignalDecisionValue
from backend.domain.retrieval import ReviewSignalRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario
from backend.services.handoff_context import _active_signals, build_handoff_transfer_context


SCENARIO = (
    Path(__file__).resolve().parents[1]
    / 'backend'
    / 'demo_data'
    / 'scenarios'
    / 'AT-02-coverage-ambiguity.json'
)


def test_transfer_context_uses_durable_retrieval_and_tag_coordinates() -> None:
    repository = FixtureRepository()
    scenario = load_scenario(SCENARIO)
    seed_scenario(repository, scenario)

    context = build_handoff_transfer_context(
        repository,
        scenario.claim,
        evidence=scenario.evidence,
        handoffs=scenario.handoffs,
    )

    linked = scenario.linked_records
    assert linked is not None
    assert context.policy_retrieval_refs == [linked.policy_retrieval_id]
    assert context.history_retrieval_refs == [linked.claim_history_retrieval_id]
    assert any(
        ref.startswith('tag_registry:northwind-fnol-staff-tags:')
        for ref in context.provenance_refs
    )
    assert len(context.provenance_refs) == len(set(context.provenance_refs))


def test_active_signals_follow_latest_staff_decision() -> None:
    created = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
    signal = ReviewSignalRecord(
        signal_id='sig_transfer_context',
        claim_id='clm_transfer_context',
        code='POLICY_REVIEW_REQUIRED',
        source_refs=['ret_policy_transfer'],
        reason_codes=['COVERAGE_AMBIGUOUS'],
        summary='A professional review is required.',
        created_at=created,
    )

    confirmed = SignalDecisionRecord(
        decision=SignalDecisionValue.CONFIRMED,
        reason_codes=['POLICY_SECTION_CONFIRMED'],
        summary='Keep this signal active for follow-up.',
        evidence_refs=['ret_policy_transfer'],
        signal_decision_id='sdec_confirmed',
        claim_id=signal.claim_id,
        signal_id=signal.signal_id,
        actor_id='stf_demo',
        created_at=created + timedelta(minutes=1),
    )
    dismissed = confirmed.model_copy(
        update={
            'signal_decision_id': 'sdec_dismissed',
            'decision': SignalDecisionValue.DISMISSED,
            'created_at': created + timedelta(minutes=2),
        }
    )
    overridden = confirmed.model_copy(
        update={
            'signal_decision_id': 'sdec_overridden',
            'decision': SignalDecisionValue.OVERRIDDEN,
            'created_at': created + timedelta(minutes=3),
        }
    )
    resolved = confirmed.model_copy(
        update={
            'signal_decision_id': 'sdec_resolved',
            'decision': SignalDecisionValue.RESOLVED,
            'created_at': created + timedelta(minutes=4),
        }
    )

    assert _active_signals([signal], []) == [signal]
    assert _active_signals([signal], [confirmed]) == [signal]
    assert _active_signals([signal], [confirmed, dismissed]) == []
    assert _active_signals([signal], [dismissed, overridden]) == [signal]
    assert _active_signals([signal], [overridden, resolved]) == []
