"""A complete-journey run record must not claim more than its own evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from journey_runs.record import (
    AgentTurn,
    Arrival,
    InputMaterial,
    JourneyRunRecord,
    ResultClass,
    RunConfiguration,
    SeamCheck,
    SeamVerdict,
    VisibilityCheck,
)
from pydantic import ValidationError

_NOW = datetime(2026, 9, 15, tzinfo=UTC)


def _configuration(runtime: str, provider_mode: str) -> RunConfiguration:
    return RunConfiguration.model_validate(
        {
            'head': 'abc',
            'started_at': _NOW,
            'finished_at': _NOW,
            'runtime': runtime,
            'provider_mode': provider_mode,
            'agent_runtime_profile': 'controlled',
            'model_profile_id': 'model',
            'evidence_level': runtime,
        }
    )


def _step(http_status: int | None, outcome: str, name: str = 'step') -> dict[str, Any]:
    return {
        'name': name,
        'actor': 'claimant',
        'route': 'POST /x',
        'expected_status': 201,
        'http_status': http_status,
        'outcome': outcome,
    }


def _record(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        'run_id': 'run-1',
        'scenario_id': 'motor-collision-assessor',
        'family': 'motor',
        'pack_id': 'pack',
        'rubric_refs': [],
        'configuration': _configuration('deployed', 'live'),
        'materials': [],
        'steps': [_step(201, 'succeeded')],
        'agent_turns': [],
        'consents': [],
        'visibility_checks': [],
        'seam_checks': [],
        'final_state': {
            'claim_id': 'clm_1',
            'claim_number': None,
            'expected_by': None,
            'workflow_state': None,
            'lifecycle_state': None,
            'queue_key': None,
            'customer_next_step': None,
            'next_step_responsible_party': None,
            'session_id': None,
            'session_status': None,
            'active_session_id': None,
            'evidence_ids': [],
            'external_task_statuses': [],
            'handoff_status': None,
        },
        'effort': {'messages': 0, 'confirmations': 0, 'uploads': 0, 'consents': 0},
        'result_class': 'completed',
        'result_reason': 'reason',
    }
    return base | changes


_FIXTURE = _configuration('fixture', 'simulated')
_NO_ROUTE = [
    InputMaterial(
        path='police.pdf',
        material_class='Police report',
        condition='received',
        provided_by='external_party',
        arrival=Arrival.NO_ROUTE,
    )
]
_DISAGREEING = [
    SeamCheck(
        seam='assessor.staff_has_an_action',
        question='q',
        claimant='c',
        staff='s',
        verdict=SeamVerdict.MISSING,
        defect_ref='#792 F2',
    )
]
_LEAK = [
    VisibilityCheck(
        audience='claimant', subject='internal note', expected_visible=False, observed_visible=True
    )
]


@pytest.mark.parametrize(
    ('changes', 'derived'),
    [
        ({}, ResultClass.COMPLETED),
        ({'configuration': _FIXTURE}, ResultClass.FIXTURE_ONLY),
        ({'materials': _NO_ROUTE}, ResultClass.PARTIAL),
        ({'seam_checks': _DISAGREEING, 'configuration': _FIXTURE}, ResultClass.PARTIAL),
        ({'steps': [_step(409, 'blocked')], 'seam_checks': _DISAGREEING}, ResultClass.BLOCKED),
        ({'visibility_checks': _LEAK}, ResultClass.FAILED),
    ],
)
def test_a_record_cannot_claim_more_than_its_evidence(
    changes: dict[str, Any], derived: ResultClass
) -> None:
    assert JourneyRunRecord.model_validate(_record(**changes, result_class=derived))
    for overstated in ResultClass:
        if overstated is not derived:
            with pytest.raises(ValidationError, match='contradicts the recorded evidence'):
                JourneyRunRecord.model_validate(_record(**changes, result_class=overstated))


@pytest.mark.parametrize(
    ('http_status', 'claimed'),
    [(500, 'succeeded'), (409, 'succeeded'), (None, 'succeeded'), (201, 'failed')],
)
def test_a_step_outcome_must_follow_its_status(http_status: int | None, claimed: str) -> None:
    # A deployed, live run whose only step errored cannot be recorded as completed.
    with pytest.raises(ValidationError, match='contradicts HTTP'):
        JourneyRunRecord.model_validate(
            _record(steps=[_step(http_status, claimed)], result_class='completed')
        )


def test_a_disagreement_must_name_its_defect() -> None:
    with pytest.raises(ValidationError, match='must name a defect reference'):
        SeamCheck(
            seam='assessor.responsible_party',
            question='q',
            claimant='claimant',
            staff='claims_professional',
            verdict=SeamVerdict.CONTRADICTORY,
        )


def test_an_unobserved_agent_trace_must_say_why() -> None:
    turn = {
        'step': 'step',
        'claimant_input': 'Another car hit mine.',
        'agent_reply': 'Please check the facts.',
        'proposed_action': 'CONFIRM',
        'reason_codes': ['MATERIAL_FACTS_PROPOSED'],
        'next_step': 'confirmation_required',
    }
    with pytest.raises(ValidationError, match='need a trace_limitation'):
        AgentTurn.model_validate(turn)
    limited = {**turn, 'trace_limitation': 'Not exposed by the claimant route.'}
    assert JourneyRunRecord.model_validate(_record(agent_turns=[limited]))
    with pytest.raises(ValidationError, match='is not a recorded step'):
        JourneyRunRecord.model_validate(_record(agent_turns=[{**limited, 'step': 'other'}]))
