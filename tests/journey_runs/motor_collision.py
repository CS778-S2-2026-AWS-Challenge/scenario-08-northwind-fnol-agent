"""Drive the motor collision journey end to end and record the run.

The runner acts only through HTTP routes: the claimant's, the Workbench's, and the
integration service's. The one exception is the upload bytes. The API hands the claimant a
signed upload capability; on the fixture runtime that capability is the in-memory evidence
storage, so the runner puts the material there and then completes the upload through the
route, as a browser would after a PUT to a signed URL.

The run is recorded as it happened and classified by `record.classify`. Expectations declared by
the selected fixture are executable oracles: every comparison is recorded on its route step and a
contradiction fails the run instead of becoming false-positive evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.adapters.claims_service import MockAssessorServiceAdapter
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository

from .engine import (
    FORMS,
    REPOSITORY_ROOT,
    Journey,
    PackMaterial,
    SharedReadBack,
    agent_turn,
    build_record,
    delivered_materials,
    final_state,
    read_both_ends,
    seam_check,
    upload_pack,
)
from .record import (
    AgentTurn,
    Arrival,
    ConsentRecord,
    JourneyRunRecord,
    SeamCheck,
    SeamVerdict,
    StepOutcome,
    VisibilityCheck,
)

JOURNEY_PATH = REPOSITORY_ROOT / 'tests/fixtures/journeys/AT-01-clear-motor-creation.json'
SCENARIO_ID = 'motor-collision-assessor'
PACK_ID = 'motor-collision-provisional-2'
RUBRIC_REFS = ['full-journey completion', 'consistent shared state', 'honest third-party status']

# Multi-turn motor journey fixtures. AT-01 is the single-turn clear-creation path;
# PRES-01 replays a rear-end report through a human handoff; PRES-02 replays a guided
# rear-end review that queues professional review. Each fixture's `turns` list is replayed
# in order and its declared observable expectations are validated.
MOTOR_JOURNEY_FIXTURES: dict[str, Path] = {
    'AT-01': JOURNEY_PATH,
    'PRES-01': REPOSITORY_ROOT / 'tests/fixtures/journeys/PRES-01-rear-end-handoff.json',
    'PRES-02': REPOSITORY_ROOT / 'tests/fixtures/journeys/PRES-02-guided-rear-end-review.json',
}

MOTOR_COLLISION_PACK = (
    PackMaterial(
        'motor/motor-incident-rear-bumper.jpg',
        'Incident evidence',
        'claimant',
        Arrival.CLAIMANT_UPLOAD,
        'incident_image',
        'image/jpeg',
    ),
    PackMaterial(
        'motor/motor-incident-scene-wide.jpg',
        'Incident evidence',
        'claimant',
        Arrival.CLAIMANT_UPLOAD,
        'incident_image',
        'image/jpeg',
    ),
    PackMaterial(
        'motor/motor-police-event-report.pdf',
        'Police report',
        'external_party',
        Arrival.CLAIMANT_UPLOAD,
        'police_report',
        'application/pdf',
        f'Issued by Police and supplied by the claimant (P3-NZP-REPORT, manual, {FORMS}).',
    ),
    PackMaterial(
        'motor/motor-consent-record.pdf',
        'Consent record',
        'northwind_staff',
        Arrival.CONSENT_ROUTE,
        note='Recorded by Northwind when the claimant consents; the document is not uploaded.',
        delivered_by='consent to the assessor',
    ),
    PackMaterial(
        'motor/motor-assessment-v2.pdf',
        'Assessment report',
        'external_party',
        Arrival.SIMULATED_PROVIDER_RESULT,
        note='The fixture assessor returns its own result; these bytes are not transmitted.',
        delivered_by='receive the assessment',
    ),
)


@dataclass(frozen=True)
class MotorRunCase:
    """One independently identified motor input/material combination."""

    fixture_name: str
    input_variant: int
    pack_id: str
    pack: tuple[PackMaterial, ...]
    input_payload: str


def _replace_pack_material(path: str, replacement: PackMaterial) -> tuple[PackMaterial, ...]:
    return tuple(
        replacement if material.path == path else material for material in MOTOR_COLLISION_PACK
    )


MOTOR_PACKS: dict[str, tuple[PackMaterial, ...]] = {
    PACK_ID: MOTOR_COLLISION_PACK,
    'motor-collision-unreadable-v1': _replace_pack_material(
        'motor/motor-incident-rear-bumper.jpg',
        PackMaterial(
            'motor/motor-incident-unreadable.jpg',
            'Incident evidence',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'incident_image',
            'image/jpeg',
            'The incident image cannot be read (invalid material condition).',
            condition='invalid',
        ),
    ),
    'motor-collision-conflicting-v1': _replace_pack_material(
        'motor/motor-incident-rear-bumper.jpg',
        PackMaterial(
            'motor/motor-incident-conflicting-panel.jpg',
            'Incident evidence',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'incident_image',
            'image/jpeg',
            'The photographed panel conflicts with the reported damage (disputed condition).',
            condition='disputed',
        ),
    ),
    'motor-collision-superseded-v1': (
        *MOTOR_COLLISION_PACK,
        PackMaterial(
            'motor/motor-assessment-v1.pdf',
            'Assessment report',
            'external_party',
            Arrival.NO_ROUTE,
            note='Assessment version 1 was superseded by the current simulated result.',
            condition='superseded',
        ),
    ),
    'motor-collision-unavailable-v1': _replace_pack_material(
        'motor/motor-assessment-v2.pdf',
        PackMaterial(
            'motor/motor-assessment-unavailable-notice.pdf',
            'Assessment report',
            'external_party',
            Arrival.NO_ROUTE,
            note='The assessment could not be obtained from the provider.',
            condition='unavailable',
        ),
    ),
}

_MOTOR_LOCATIONS = (
    'Queen Street',
    'Lake Road',
    'Dominion Road',
    'Lincoln Road',
    'Ti Rakau Drive',
    'Great South Road',
    'New North Road',
    'Manukau Road',
    'Hobsonville Road',
    'East Coast Road',
)
_MOTOR_TIMES = (
    ('this morning', '9:15 am today'),
    ('this afternoon', '2:40 pm today'),
    ('this evening', '6:20 pm today'),
    ('last night', '8:05 pm yesterday'),
    ('yesterday morning', '10:30 am yesterday'),
)
_MOTOR_INPUT_VARIANTS = tuple(
    (location, *times) for location, times in product(_MOTOR_LOCATIONS, _MOTOR_TIMES)
)


def motor_run_cases(fixture_name: str | None = None) -> tuple[MotorRunCase, ...]:
    """Return the bounded motor matrix with no duplicate input/material pair.

    Args:
        fixture_name: Optional fixture restriction. Without one, return the fifty-run baseline.

    Returns:
        Twenty-five cases for one fixture, or the interleaved fifty-case Sprint 4 baseline.

    Raises:
        ValueError: If the requested fixture is unknown.
    """

    if fixture_name is not None and fixture_name not in MOTOR_JOURNEY_FIXTURES:
        raise ValueError(f'Unknown motor fixture: {fixture_name!r}')
    combinations = tuple(MOTOR_PACKS.items()) * 5
    if fixture_name:
        return tuple(
            MotorRunCase(
                fixture_name,
                variant,
                pack_id,
                pack,
                _motor_input_payload(fixture_name, variant),
            )
            for variant, (pack_id, pack) in enumerate(combinations)
        )
    fixture_pairs = (
        ('AT-01', 'PRES-01'),
        ('PRES-02', 'AT-01'),
        ('PRES-01', 'PRES-02'),
    )
    scheduled: list[tuple[str, str, tuple[PackMaterial, ...]]] = []
    for index, (pack_id, pack) in enumerate(combinations):
        for fixture in fixture_pairs[index % len(fixture_pairs)]:
            scheduled.append((fixture, pack_id, pack))
    return tuple(
        MotorRunCase(
            fixture,
            variant,
            pack_id,
            pack,
            _motor_input_payload(fixture, variant),
        )
        for variant, (fixture, pack_id, pack) in enumerate(scheduled)
    )


def _motor_input(fixture_name: str, variant: int) -> dict[str, Any]:
    loaded = cast(
        dict[str, Any],
        json.loads(MOTOR_JOURNEY_FIXTURES[fixture_name].read_text(encoding='utf-8')),
    )
    journey_input = deepcopy(loaded)
    location, initial_time, guided_time = _MOTOR_INPUT_VARIANTS[variant]

    def vary(value: object) -> object:
        if isinstance(value, str):
            return (
                value.replace('Queen Street', location)
                .replace('this morning', initial_time)
                .replace('5:30 pm today', guided_time)
            )
        if isinstance(value, list):
            return [vary(item) for item in value]
        if isinstance(value, dict):
            return {key: vary(item) for key, item in value.items()}
        return value

    return cast(dict[str, Any], vary(journey_input))


def _motor_input_payload(fixture_name: str, variant: int) -> str:
    journey_input = _motor_input(fixture_name, variant)
    turns = journey_input.get('turns') or []
    claimant_inputs = [str(turn['input']) for turn in turns if turn.get('input')]
    if not claimant_inputs:
        claimant_inputs = [str(journey_input['input'])]
    return json.dumps(
        {
            'claimant_inputs': claimant_inputs,
            'staff_resolution': journey_input.get('staff_resolution'),
        },
        sort_keys=True,
        separators=(',', ':'),
    )


# Disagreements already reported to their owner. Any other disagreement is `untracked`.
KNOWN_DEFECTS = {
    'assessor.staff_can_find_work': '#792 F1',
    'assessor.staff_has_an_action': '#792 F2',
}


def _proposed_field_codes(journey: Journey) -> list[str]:
    """Read every field the dynamic form currently lists as `proposed`."""
    claim = journey.read(f'/api/v1/claims/{journey.claim_id}', 'claimant')
    fields = ((claim.get('dynamic_form') or {}).get('fields')) or []
    return [
        str(field.get('field_code')) for field in fields if field.get('value_state') == 'proposed'
    ]


def _record_message_oracle(
    journey: Journey, step_name: str, spec: dict[str, Any], payload: dict[str, Any]
) -> None:
    decision = payload.get('decision') or {}
    next_step = decision.get('customer_next_step') or {}
    expected: dict[str, object] = {}
    actual: dict[str, object] = {}
    if 'expected_action' in spec:
        expected['action'] = spec['expected_action']
        actual['action'] = decision.get('action')
    if 'expected_form_fields' in spec:
        expected['form_fields'] = sorted(spec['expected_form_fields'])
        actual['form_fields'] = sorted(
            str(item.get('field_code')) for item in payload.get('form_changes') or []
        )
    if 'next_step_status' in spec:
        expected['next_step_status'] = spec['next_step_status']
        actual['next_step_status'] = next_step.get('status')
    if 'required_item' in spec:
        expected['required_items'] = [spec['required_item']]
        actual['required_items'] = next_step.get('required_items') or []
    fragments = [str(item).lower() for item in spec.get('response_contains') or []]
    if fragments:
        response = str(
            ((payload.get('agent_message') or {}).get('content') or {}).get('text', '')
        ).lower()
        expected['response_contains'] = {fragment: True for fragment in fragments}
        actual['response_contains'] = {fragment: fragment in response for fragment in fragments}
    if 'expected_evidence_status' in spec:
        statuses = [
            str(item.get('status'))
            for item in journey.items(f'/api/v1/claims/{journey.claim_id}/evidence', 'claimant')
        ]
        wanted = str(spec['expected_evidence_status'])
        expected['evidence_status'] = wanted
        actual['evidence_status'] = wanted if wanted in statuses else sorted(statuses)
    journey.record_oracle(step_name, expected, actual)


def _record_handoff_oracle(
    journey: Journey, spec: dict[str, Any], step_name: str
) -> dict[str, Any]:
    handoffs = journey.items(f'/api/v1/workbench/claims/{journey.claim_id}/handoffs', 'staff')
    handoff = handoffs[0] if len(handoffs) == 1 else {}
    packet = handoff.get('packet') or {}
    pending_ids = set(packet.get('pending_items') or [])
    evidence = journey.items(f'/api/v1/claims/{journey.claim_id}/evidence', 'claimant')
    pending_kinds = {
        str(item.get('kind')) for item in evidence if item.get('evidence_id') in pending_ids
    }
    expected = {
        'priority': spec['priority'],
        'support_need': spec['support_need'],
        'pending_evidence_kind': spec['pending_evidence_kind'],
        'requested_action_contains': True,
        'minimum_prior_customer_updates': True,
    }
    actual = {
        'priority': handoff.get('priority'),
        'support_need': handoff.get('support_need'),
        'pending_evidence_kind': (
            spec['pending_evidence_kind']
            if spec['pending_evidence_kind'] in pending_kinds
            else sorted(pending_kinds)
        ),
        'requested_action_contains': str(spec['requested_action_contains']).lower()
        in str(handoff.get('requested_action', '')).lower(),
        'minimum_prior_customer_updates': len(packet.get('prior_customer_updates') or [])
        >= int(spec['minimum_prior_customer_updates']),
    }
    journey.record_oracle(step_name, expected, actual)
    return handoff


def _execute_staff_resolution(journey: Journey, spec: dict[str, Any]) -> None:
    handoffs = journey.items(f'/api/v1/workbench/claims/{journey.claim_id}/handoffs', 'staff')
    if len(handoffs) != 1:
        raise AssertionError(f'Expected one staff handoff, found {len(handoffs)}.')
    handoff = handoffs[0]
    handoff_id = journey.name(str(handoff['handoff_id']), '{handoff_id}')
    base = f'/api/v1/workbench/claims/{journey.claim_id}/handoffs/{handoff_id}'
    accepted = journey.step('staff accept review', 'POST', f'{base}/accept', 200, 'staff', {})
    if accepted is None:
        return
    journey.record_oracle(
        'staff accept review',
        {'handoff_status': 'accepted'},
        {'handoff_status': (accepted.get('handoff') or {}).get('status')},
    )
    resolved = journey.step(
        'staff resolve review',
        'POST',
        f'{base}/resolve',
        200,
        'staff',
        {
            'result': {
                'outcome': 'professional_review_completed',
                'summary': 'The cited collision wording permits the report to continue.',
                'reason_codes': ['POLICY_SECTION_CONFIRMED'],
                'source_refs': (handoff.get('packet') or {}).get('source_refs') or [],
            },
            'state_changes': [
                {'path': 'claim_state.coverage', 'to': spec['coverage']},
                {'path': 'claim_state.workflow_state', 'to': spec['workflow_state']},
            ],
            'customer_update': {
                'summary': spec['customer_update'],
                'responsible_party': 'claims_professional',
                'related_refs': [handoff['handoff_id']],
            },
        },
    )
    if resolved is None:
        return
    claimant = journey.read(f'/api/v1/claims/{journey.claim_id}', 'claimant')
    detail = journey.read(f'/api/v1/workbench/claims/{journey.claim_id}', 'staff')
    journey.record_oracle(
        'staff resolve review',
        {
            'handoff_status': 'resolved',
            'coverage': spec['coverage'],
            'workflow_state': spec['workflow_state'],
            'customer_update': spec['customer_update'],
        },
        {
            'handoff_status': (resolved.get('handoff') or {}).get('status'),
            'coverage': (detail.get('claim_state') or {}).get('coverage'),
            'workflow_state': (detail.get('claim_state') or {}).get('workflow_state'),
            'customer_update': (claimant.get('customer_next_step') or {}).get('summary'),
        },
    )


def _drive_multi_turn(
    journey: Journey, journey_input: dict[str, Any], pack: tuple[PackMaterial, ...]
) -> tuple[list[AgentTurn], dict[str, str]]:
    """Replay a fixture's `turns` list through the claimant API.

    Each turn either carries an `input` (a claimant message) or an `operation`
    (currently only `confirm_proposed_fields`). Every declared fixture expectation is
    compared with the route response and stored on the corresponding run step.
    """
    fixture_claim = journey_input.get('claim') or {}
    session = journey.create_working_claim(fixture_claim.get('incident_type'))
    if session is None:
        return [], {}
    turns: list[AgentTurn] = []
    evidence: dict[str, str] = {}
    claim = f'/api/v1/claims/{journey.claim_id}'

    for index, turn in enumerate(journey_input.get('turns', []), start=1):
        if journey.stopped:
            break
        if turn.get('operation') == 'confirm_proposed_fields':
            proposed = _proposed_field_codes(journey)
            if proposed:
                name = f'confirm proposed fields (turn {index})'
                confirmed = journey.step(
                    name,
                    'POST',
                    f'{claim}/form/confirmations',
                    200,
                    'claimant',
                    {'field_codes': proposed},
                )
                if confirmed is not None:
                    journey.record_oracle(
                        name,
                        {'next_step_status': turn['expected_next_step_status']},
                        {
                            'next_step_status': (confirmed.get('customer_next_step') or {}).get(
                                'status'
                            )
                        },
                    )
        elif turn.get('input'):
            name = f'turn {index}: {str(turn.get("expected_action", "input")).lower()}'
            payload = journey.say(name, session, str(turn['input']))
            if payload:
                turns.append(agent_turn(name, str(turn['input']), payload))
                _record_message_oracle(journey, name, turn, payload)

    if not journey.stopped:
        # Keep the fixture's declared conversation oracle independent from evidence-upload
        # side effects, then attach the material pack before staff readback and resolution.
        evidence = upload_pack(journey, pack)
    if journey_input.get('expected_handoff') and journey.steps and not journey.stopped:
        _record_handoff_oracle(journey, journey_input['expected_handoff'], journey.steps[-1].name)
    if journey_input.get('staff_resolution') and not journey.stopped:
        _execute_staff_resolution(journey, journey_input['staff_resolution'])
    return turns, evidence


def run_motor_journey(
    fixture_name: str,
    *,
    head: str,
    pack: tuple[PackMaterial, ...] = MOTOR_COLLISION_PACK,
    pack_id: str = PACK_ID,
    input_variant: int = 0,
) -> JourneyRunRecord:
    """Run and validate one independently identified motor case.

    Args:
        fixture_name: AT-01, PRES-01, or PRES-02 fixture name.
        head: Exact repository commit recorded as run evidence.
        pack: Material pack presented to the runner.
        pack_id: Stable identifier for that material pack.
        input_variant: Zero-based meaningful input variation.

    Returns:
        The schema-v3 evidence record for the observed journey.

    Raises:
        ValueError: If the fixture or input variant is unknown.
    """
    if fixture_name not in MOTOR_JOURNEY_FIXTURES:
        raise ValueError(
            f'Unknown motor fixture: {fixture_name!r}; choose from {sorted(MOTOR_JOURNEY_FIXTURES)}'
        )
    if not 0 <= input_variant < len(_MOTOR_INPUT_VARIANTS):
        raise ValueError(f'Unknown motor input variant: {input_variant}')
    journey_input = _motor_input(fixture_name, input_variant)
    scenario_id = str(
        journey_input.get('scenario_id')
        or journey_input.get('journey_id')
        or f'motor-{fixture_name.lower()}'
    )
    scenario_id = f'{scenario_id}-input-{input_variant + 1:02d}'
    is_multi_turn = bool(journey_input.get('turns'))

    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    started_at = datetime.now(UTC)
    app = create_app(
        settings,
        repository=FixtureRepository(),
        assessor_service_adapter=MockAssessorServiceAdapter(),
    )
    with TestClient(app) as client:
        journey = Journey(client)
        if is_multi_turn:
            turns, evidence = _drive_multi_turn(journey, journey_input, pack)
        else:
            turns, evidence = _drive(journey, journey_input, pack)
        materials = delivered_materials(journey, pack, evidence)
        shared = read_both_ends(journey, KNOWN_DEFECTS)
        seam_checks, visibility, consents = _assessor_read_back(journey, shared)
        state = final_state(journey, shared)

    return build_record(
        scenario_id=scenario_id,
        family='motor',
        pack_id=pack_id,
        rubric_refs=RUBRIC_REFS,
        settings=settings,
        head=head,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        journey=journey,
        materials=materials,
        turns=turns,
        consents=consents,
        seam_checks=seam_checks,
        visibility_checks=visibility,
        state=state,
    )


def run_motor_collision(
    *, head: str, pack: tuple[PackMaterial, ...] = MOTOR_COLLISION_PACK
) -> JourneyRunRecord:
    """Run the motor collision journey once, on a fresh fixture runtime."""
    return run_motor_journey('AT-01', head=head, pack=pack)


def _drive(
    journey: Journey, journey_input: dict[str, object], pack: tuple[PackMaterial, ...]
) -> tuple[list[AgentTurn], dict[str, str]]:
    turns, evidence = _drive_to_assessor_consent(journey, journey_input, pack)
    claim = f'/api/v1/claims/{journey.claim_id}'
    journey.step('route the assessor', 'POST', f'{claim}/assessor-routing', 201, 'claimant')
    _receive_assessment(journey, _look_up_assessor_task(journey), pack)
    return turns, evidence


def _look_up_assessor_task(journey: Journey) -> str | None:
    internal = f'/internal/v1/claims/{journey.claim_id}/external-tasks'
    tasks = journey.step('look up the assessor task', 'GET', internal, 200, 'integration')
    if not tasks or not tasks['items']:
        return None
    return journey.name(tasks['items'][0]['task']['task_id'], '{task_id}')


def _receive_assessment(journey: Journey, task: str | None, pack: tuple[PackMaterial, ...]) -> None:
    if task is None or not any(m.route is Arrival.SIMULATED_PROVIDER_RESULT for m in pack):
        return
    internal = f'/internal/v1/claims/{journey.claim_id}/external-tasks'
    journey.step('receive the assessment', 'POST', f'{internal}/{task}/result', 201, 'integration')


def _drive_to_assessor_consent(
    journey: Journey, journey_input: dict[str, object], pack: tuple[PackMaterial, ...]
) -> tuple[list[AgentTurn], dict[str, str]]:
    session = journey.create_working_claim('motor')
    if session is None:
        return [], {}
    text = str(journey_input['input'])
    turn = journey.say('describe the incident', session, text)
    turns = [agent_turn('describe the incident', text, turn)] if turn else []
    if turn:
        baseline = cast(list[dict[str, Any]], journey_input['baseline_states'])[0]
        _record_message_oracle(
            journey,
            'describe the incident',
            {
                'expected_action': baseline['action'],
                'expected_form_fields': journey_input['expected_proposed_fields'],
                'next_step_status': baseline['next_step']['status'],
            },
            turn,
        )
    evidence = upload_pack(journey, pack)
    claim = f'/api/v1/claims/{journey.claim_id}'
    confirm = {'field_codes': journey_input['expected_proposed_fields']}
    confirmed = journey.step(
        'confirm the proposed facts',
        'POST',
        f'{claim}/form/confirmations',
        200,
        'claimant',
        confirm,
    )
    if confirmed:
        expected_confirm = cast(list[dict[str, Any]], journey_input['baseline_states'])[1]
        journey.record_oracle(
            'confirm the proposed facts',
            {'next_step_status': expected_confirm['next_step']['status']},
            {'next_step_status': (confirmed.get('customer_next_step') or {}).get('status')},
        )
    created = journey.step('create the claim', 'POST', f'{claim}/creation', 201, 'claimant')
    if created:
        external_claim = created.get('external_claim') or {}
        journey.record_oracle(
            'create the claim',
            {
                'creation_status': journey_input['expected_creation_status'],
                'source': journey_input['expected_source'],
            },
            {
                'creation_status': external_claim.get('creation_status'),
                'source': external_claim.get('source'),
            },
        )
    consent = {'consent': True}
    journey.step(
        'consent to the assessor',
        'POST',
        f'{claim}/assessor-routing/consent',
        201,
        'claimant',
        consent,
    )
    return turns, evidence


def _assessor_read_back(
    journey: Journey,
    shared: SharedReadBack,
    known_defects: Mapping[str, str] = KNOWN_DEFECTS,
) -> tuple[list[SeamCheck], list[VisibilityCheck], list[ConsentRecord]]:
    claim_id = journey.claim_id
    if not claim_id or shared.evidence_check is None:
        return [], [], []
    claimant, detail = shared.claimant, shared.detail
    party = (claimant.get('customer_next_step') or {}).get('responsible_party')
    queue = (detail.get('work_summary') or {}).get('queue_key')
    requests = journey.items(f'/api/v1/workbench/claims/{claim_id}/external-requests', 'staff')
    request = (requests[0].get('request') or {}) if requests else {}
    owner = (requests[0].get('lifecycle') or {}).get('pending_owner') if requests else None
    listed = {
        item['claim_id']
        for item in journey.items('/api/v1/workbench/claims?view=all&limit=100', 'staff')
    }
    actions = [item['action_code'] for item in detail.get('allowed_actions', [])]
    staff_owned = party == 'claims_professional'
    routed = journey.succeeded('route the assessor')

    checks = [shared.evidence_check]
    for seam, question, claimant_said, staff_said, agrees, disagreement in (
        (
            'assessor.responsible_party',
            'Who acts next on the assessor request?',
            str(party),
            str(owner),
            party is not None and party == owner,
            SeamVerdict.CONTRADICTORY,
        ),
        (
            'assessor.staff_can_find_work',
            'When the claimant is told staff act next, is the claim in an active queue?',
            f'next step owned by {party}',
            f"queue {queue}; in 'all': {claim_id in listed}",
            claim_id in listed or not staff_owned,
            SeamVerdict.MISSING,
        ),
        (
            'assessor.staff_has_an_action',
            'When the claimant is told staff act next, does staff have an action to take?',
            f'next step owned by {party}',
            f'allowed actions: {actions or "none"}',
            bool(actions) or not staff_owned,
            SeamVerdict.MISSING,
        ),
    ):
        if routed:
            verdict = SeamVerdict.CONSISTENT if agrees else disagreement
            checks.append(
                seam_check(seam, question, claimant_said, staff_said, verdict, known_defects)
            )
        else:
            checks.append(
                seam_check(
                    seam,
                    question,
                    'not reached',
                    'not reached',
                    SeamVerdict.UNAVAILABLE,
                    known_defects,
                )
            )

    external = {
        item['evidence_id']
        for item in shared.staff_evidence
        if item.get('source') == 'external_system'
    }
    visibility = [
        *shared.visibility,
        VisibilityCheck(
            audience='claimant',
            subject='the returned assessment evidence',
            expected_visible=False,
            observed_visible=bool(external & shared.uploaded),
        ),
    ]
    consents = []
    consent_step = next((s for s in journey.steps if s.name == 'consent to the assessor'), None)
    if consent_step is not None and consent_step.outcome is StepOutcome.SUCCEEDED:
        action = claimant.get('external_service_action') or {}
        consents.append(
            ConsentRecord(
                purpose='assessor routing',
                granted=action.get('consent_status') == 'granted',
                step=consent_step.name,
                claim_revision=consent_step.claim_revision,
                disclosed_fields=request.get('disclosed_fields'),
            )
        )
    return checks, visibility, consents
