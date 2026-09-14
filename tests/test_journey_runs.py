"""A complete-journey run record must not claim more than its own evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from journey_runs.record import (
    Arrival,
    InputMaterial,
    JourneyRunRecord,
    ResultClass,
    RunConfiguration,
    RunStep,
    SeamCheck,
    SeamVerdict,
)
from pydantic import ValidationError


def _record(**changes: Any) -> dict[str, Any]:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    base: dict[str, Any] = {
        'run_id': 'run-1',
        'scenario_id': 'motor-collision-assessor',
        'family': 'motor',
        'pack_id': 'pack',
        'rubric_refs': [],
        'configuration': RunConfiguration(
            head='abc',
            started_at=now,
            finished_at=now,
            runtime='deployed',
            provider_mode='live',
            agent_runtime_profile='controlled',
            model_profile_id='model',
            evidence_level='deployed',
        ),
        'materials': [],
        'steps': [RunStep(name='step', route='POST /x', http_status=201, outcome='succeeded')],
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
            'evidence_ids': [],
            'external_task_statuses': [],
            'handoff_status': None,
        },
        'effort': {'messages': 0, 'confirmations': 0, 'uploads': 0, 'consents': 0},
        'result_class': 'completed',
        'result_reason': 'reason',
    }
    return base | changes


_FIXTURE = RunConfiguration(
    head='abc',
    started_at=datetime(2026, 9, 15, tzinfo=UTC),
    finished_at=datetime(2026, 9, 15, tzinfo=UTC),
    runtime='fixture',
    provider_mode='simulated',
    agent_runtime_profile='controlled',
    model_profile_id='model',
    evidence_level='fixture',
)
_BLOCKED = [RunStep(name='step', route='POST /x', http_status=409, outcome='blocked')]
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


@pytest.mark.parametrize(
    ('changes', 'derived'),
    [
        ({}, ResultClass.COMPLETED),
        ({'configuration': _FIXTURE}, ResultClass.FIXTURE_ONLY),
        ({'materials': _NO_ROUTE}, ResultClass.PARTIAL),
        ({'seam_checks': _DISAGREEING, 'configuration': _FIXTURE}, ResultClass.PARTIAL),
        ({'steps': _BLOCKED, 'seam_checks': _DISAGREEING}, ResultClass.BLOCKED),
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


def test_a_disagreement_must_name_its_defect() -> None:
    with pytest.raises(ValidationError, match='must name a defect reference'):
        SeamCheck(
            seam='assessor.responsible_party',
            question='q',
            claimant='claimant',
            staff='claims_professional',
            verdict=SeamVerdict.CONTRADICTORY,
        )
