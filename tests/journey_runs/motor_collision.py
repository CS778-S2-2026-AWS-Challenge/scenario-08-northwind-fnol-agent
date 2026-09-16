"""Drive the motor collision journey end to end and record the run.

The runner acts only through HTTP routes: the claimant's, the Workbench's, and the
integration service's. The one exception is the upload bytes. The API hands the claimant a
signed upload capability; on the fixture runtime that capability is the in-memory evidence
storage, so the runner puts the material there and then completes the upload through the
route, as a browser would after a PUT to a signed URL.

Nothing is asserted here. The run is recorded as it happened and classified by
`record.classify`; `tests/test_journey_runs.py` decides what a run must satisfy.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

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
# in order; the runner records what actually happens and never asserts.
MOTOR_JOURNEY_FIXTURES: dict[str, Path] = {
    'AT-01': JOURNEY_PATH,
    'PRES-01': REPOSITORY_ROOT / 'tests/fixtures/journeys/PRES-01-rear-end-handoff.json',
    'PRES-02': REPOSITORY_ROOT / 'tests/fixtures/journeys/PRES-02-guided-rear-end-review.json',
}

# Provisional until an owner freezes the rubric anchors. Every material is `received`; the
# deliberately defective variants (unreadable, conflicting, superseded, not obtainable) belong
# to failure-path runs.
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
        str(field.get('field_code'))
        for field in fields
        if field.get('value_state') == 'proposed'
    ]


def _drive_multi_turn(
    journey: Journey, journey_input: dict[str, object], pack: tuple[PackMaterial, ...]
) -> tuple[list[AgentTurn], dict[str, str]]:
    """Replay a fixture's `turns` list through the claimant API.

    Each turn either carries an `input` (a claimant message) or an `operation`
    (currently only `confirm_proposed_fields`). The claimant pack is uploaded after
    the first input turn, matching the AT-01 flow (describe -> upload -> confirm).
    Nothing is asserted: the run records what happened and stops at the first step
    that does not succeed.
    """
    session = journey.create_working_claim('motor')
    if session is None:
        return [], {}
    turns: list[AgentTurn] = []
    evidence: dict[str, str] = {}
    claim = f'/api/v1/claims/{journey.claim_id}'
    uploaded = False

    for index, turn in enumerate(journey_input.get('turns', []), start=1):
        if journey.stopped:
            break
        if not uploaded and turn.get('input'):
            evidence = upload_pack(journey, pack)
            uploaded = True
        if turn.get('operation') == 'confirm_proposed_fields':
            proposed = _proposed_field_codes(journey)
            if proposed:
                journey.step(
                    f'confirm proposed fields (turn {index})',
                    'POST',
                    f'{claim}/form/confirmations',
                    200,
                    'claimant',
                    {'field_codes': proposed},
                )
        elif turn.get('input'):
            name = f"turn {index}: {str(turn.get('expected_action', 'input')).lower()}"
            payload = journey.say(name, session, str(turn['input']))
            if payload:
                turns.append(agent_turn(name, str(turn['input']), payload))

    if not uploaded:
        # A fixture with no input turn still gets its pack recorded as not delivered.
        evidence = {}
    return turns, evidence


def run_motor_journey(
    fixture_name: str, *, head: str, pack: tuple[PackMaterial, ...] = MOTOR_COLLISION_PACK
) -> JourneyRunRecord:
    """Run one motor journey from a named fixture (AT-01 / PRES-01 / PRES-02)."""
    if fixture_name not in MOTOR_JOURNEY_FIXTURES:
        raise ValueError(f'Unknown motor fixture: {fixture_name!r}; choose from {sorted(MOTOR_JOURNEY_FIXTURES)}')
    journey_input = json.loads(MOTOR_JOURNEY_FIXTURES[fixture_name].read_text(encoding='utf-8'))
    scenario_id = str(
        journey_input.get('scenario_id')
        or journey_input.get('journey_id')
        or f'motor-{fixture_name.lower()}'
    )
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
        pack_id=PACK_ID,
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
    session = journey.create_working_claim('motor')
    if session is None:
        return [], {}
    text = str(journey_input['input'])
    turn = journey.say('describe the incident', session, text)
    turns = [agent_turn('describe the incident', text, turn)] if turn else []
    evidence = upload_pack(journey, pack)
    claim = f'/api/v1/claims/{journey.claim_id}'
    confirm = {'field_codes': journey_input['expected_proposed_fields']}
    journey.step(
        'confirm the proposed facts',
        'POST',
        f'{claim}/form/confirmations',
        200,
        'claimant',
        confirm,
    )
    journey.step('create the claim', 'POST', f'{claim}/creation', 201, 'claimant')
    consent = {'consent': True}
    journey.step(
        'consent to the assessor',
        'POST',
        f'{claim}/assessor-routing/consent',
        201,
        'claimant',
        consent,
    )
    journey.step('route the assessor', 'POST', f'{claim}/assessor-routing', 201, 'claimant')
    internal = f'/internal/v1/claims/{journey.claim_id}/external-tasks'
    tasks = journey.step('look up the assessor task', 'GET', internal, 200, 'integration')
    if tasks and tasks['items']:
        task = journey.name(tasks['items'][0]['task']['task_id'], '{task_id}')
        journey.step(
            'receive the assessment', 'POST', f'{internal}/{task}/result', 201, 'integration'
        )
    return turns, evidence


def _assessor_read_back(
    journey: Journey, shared: SharedReadBack
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
                seam_check(seam, question, claimant_said, staff_said, verdict, KNOWN_DEFECTS)
            )
        else:
            checks.append(
                seam_check(
                    seam,
                    question,
                    'not reached',
                    'not reached',
                    SeamVerdict.UNAVAILABLE,
                    KNOWN_DEFECTS,
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
