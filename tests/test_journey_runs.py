"""A complete-journey run must reach its end, and its record must not overstate it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from journey_runs.motor_collision import MOTOR_COLLISION_PACK, run_motor_collision
from journey_runs.record import (
    AgentTurn,
    Arrival,
    InputMaterial,
    JourneyRunRecord,
    ResultClass,
    RunConfiguration,
    SeamCheck,
    SeamVerdict,
    StepOutcome,
    VisibilityCheck,
)
from pydantic import ValidationError

_NOW = datetime(2026, 9, 15, tzinfo=UTC)


def test_the_motor_collision_journey_reaches_its_end_and_reports_every_disagreement() -> None:
    record = run_motor_collision(head='test')

    assert {step.outcome for step in record.steps} == {StepOutcome.SUCCEEDED}
    assert record.final_state.claim_number is not None
    assert record.final_state.customer_next_step == 'assessor_result_under_review'
    assert record.effort.uploads == 3
    assert [consent.granted for consent in record.consents] == [True]
    assert all(check.holds for check in record.visibility_checks)
    # A disagreement nobody has reported must fail here, so it reaches its owner.
    assert [check.seam for check in record.seam_checks if check.defect_ref == 'untracked'] == []
    # The fixture runtime can never produce a completed run.
    assert record.result_class is not ResultClass.COMPLETED
    assert JourneyRunRecord.model_validate_json(record.model_dump_json()) == record


def test_a_run_that_stops_early_records_no_later_material_as_delivered() -> None:
    first, *rest = MOTOR_COLLISION_PACK
    # The upload API refuses this media type, so the run stops at the first upload request.
    pack = (first._replace(media_type='text/plain'), *rest)

    record = run_motor_collision(head='test', pack=pack)

    stopped = [step for step in record.steps if step.outcome is not StepOutcome.SUCCEEDED]
    assert [(step.name, step.http_status) for step in stopped] == [
        (f'request upload {first.path}', 415)
    ]
    assert record.steps[-1] == stopped[0]
    assert [material.arrival for material in record.materials] == [Arrival.NOT_DELIVERED] * 5
    assert [material.delivered_at_step for material in record.materials] == [None] * 5
    assert record.consents == []
    assert record.result_class is ResultClass.FAILED


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
        pack_condition='received',
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


def _material(arrival: str, delivered_at_step: str | None) -> dict[str, Any]:
    return {
        'path': 'photo.jpg',
        'material_class': 'Incident evidence',
        'pack_condition': 'received',
        'provided_by': 'claimant',
        'arrival': arrival,
        'delivered_at_step': delivered_at_step,
        'evidence_id': 'evd_1',
    }


@pytest.mark.parametrize(
    ('material', 'steps', 'message'),
    [
        (_material('claimant_upload', None), [_step(201, 'succeeded')], 'must name the step'),
        (_material('not_delivered', 'step'), [_step(201, 'succeeded')], 'cannot name the step'),
        (
            _material('claimant_upload', 'step'),
            [_step(500, 'failed')],
            'not a step that succeeded',
        ),
    ],
)
def test_a_material_is_delivered_only_by_a_step_that_succeeded(
    material: dict[str, Any], steps: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        JourneyRunRecord.model_validate(
            _record(materials=[material], steps=steps, result_class='failed')
        )
