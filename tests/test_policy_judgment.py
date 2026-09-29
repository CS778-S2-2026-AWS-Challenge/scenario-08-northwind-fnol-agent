from datetime import UTC, datetime

from backend.domain.agent_v8 import V8PolicyJudgmentProposal
from backend.services.policy_judgment import (
    policy_judgment_signals,
    validate_policy_judgment_proposals,
)


def proposal(kind: str, *refs: str) -> V8PolicyJudgmentProposal:
    return V8PolicyJudgmentProposal(
        kind=kind,
        assessment='Advisory assessment for staff review.',
        rationale='The supplied facts match a policy judgment point.',
        source_refs=list(refs or ('turn:1',)),
    )


def test_judgment_proposal_requires_family_and_minimum_facts() -> None:
    valid, rejected = validate_policy_judgment_proposals(
        [proposal('liability_split'), proposal('gradual_damage_discoverability')],
        product_family='motor',
        present_fields={'parties.other_parties'},
    )
    assert [item.kind for item in valid] == ['liability_split']
    assert rejected == [{'kind': 'gradual_damage_discoverability', 'reason': 'family_not_eligible'}]

    _, missing = validate_policy_judgment_proposals(
        [proposal('liability_split')], product_family='motor', present_fields=set()
    )
    assert missing == [{'kind': 'liability_split', 'reason': 'required_facts_missing'}]


def test_handoff_suppresses_and_duplicate_kinds_are_rejected() -> None:
    proposals = [proposal('excess_multiplicity'), proposal('excess_multiplicity')]
    valid, rejected = validate_policy_judgment_proposals(
        proposals,
        product_family='home',
        present_fields={'claim.product_family'},
        handoff_active=True,
    )
    assert valid == []
    assert rejected == [
        {'kind': 'excess_multiplicity', 'reason': 'suppressed_during_handoff'},
        {'kind': 'excess_multiplicity', 'reason': 'suppressed_during_handoff'},
    ]

    valid, rejected = validate_policy_judgment_proposals(
        proposals,
        product_family='home',
        present_fields={'claim.product_family'},
    )
    assert len(valid) == 1
    assert rejected == [{'kind': 'excess_multiplicity', 'reason': 'duplicate_kind'}]


def test_policy_judgment_becomes_existing_staff_signal_without_deciding() -> None:
    signals, rejected = policy_judgment_signals(
        'clm_1',
        [proposal('theft_circumstance', 'turn:42', 'policy:CON-COV-02')],
        product_family='contents',
        present_fields={'incident.description'},
        created_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    assert rejected == []
    signal = signals[0]
    assert signal.code == 'POLICY_JUDGMENT_PROPOSAL'
    assert signal.judgment_point_kind == 'theft_circumstance'
    assert signal.proposed_assessment is not None
    assert signal.source_refs == ['turn:42', 'policy:CON-COV-02']
