"""Drive the home and contents journeys to claim creation, and record where they stop.

Unlike the motor journey, a home or contents report cannot supply every required fact in one
message. The runner therefore follows the server's own requirement projection. After each
turn it confirms what the Agent proposed, reads `dynamic_form.requirements`, and answers the
`next_required_item` with a scripted claimant answer. It creates the claim once the
requirements are `ready`, and it stops when:

- a step fails or is refused, which the record classifies from that step;
- the item is a capability this runtime does not provide, which is recorded as unavailable
  after one answer shows it is not captured;
- the same item is asked for again after its answer, where creation is then attempted so the
  refusal itself is the evidence; or
- the turn budget is spent.

`KNOWN_STOPS` names every stop point already reported to its owner. The test suite fails on
any other, so a new stall reaches its owner rather than becoming an accepted baseline.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository

from .engine import (
    FORMS,
    Journey,
    PackMaterial,
    agent_turn,
    build_record,
    delivered_materials,
    final_state,
    read_both_ends,
    upload_pack,
)
from .record import AgentTurn, Arrival, JourneyRunRecord, UnavailableCapability

RUBRIC_REFS = ['full-journey completion', 'claimant effort', 'consistent shared state']
MAX_TURNS = 12
CREATE = 'create the claim'
CONTROLLED_FIXTURE = (
    'docs/model-gateway.md describes the default controlled profile as the controlled fixture; '
    'Discussion #847'
)

# Stop points already reported to their owner: required item -> tracking reference.
KNOWN_STOPS: dict[str, str] = {}


@dataclass(frozen=True)
class HouseholdScenario:
    scenario_id: str
    family: Literal['home', 'contents']
    pack_id: str
    opening: str
    answers: Mapping[str, str]
    pack: tuple[PackMaterial, ...]
    # Required item -> capability name, for items this runtime is documented not to capture.
    unavailable: Mapping[str, str]


@dataclass(frozen=True)
class HouseholdRun:
    record: JourneyRunRecord
    stopped_at: str | None


_SHARED_ANSWERS = {
    'incident.description': 'Water came in and damaged things at home yesterday morning.',
    'incident.occurred_at': 'It happened yesterday morning.',
    'incident.injury_or_danger': 'Nobody was hurt and there is no danger now.',
    'incident.location': 'It happened at my home at 12 Queen Street, Auckland 1010.',
}

HOME = HouseholdScenario(
    scenario_id='home-water-ingress',
    family='home',
    pack_id='home-water-ingress-provisional-1',
    opening=(
        'Rain came in through the roof valley yesterday morning and water damaged the lounge '
        'ceiling and the wall of the room next door.'
    ),
    answers={
        **_SHARED_ANSWERS,
        'loss.description': 'The lounge ceiling plaster and the next-door wall are water damaged.',
        'property.address': 'The property address is 12 Queen Street, Auckland 1010.',
        'property.affected_areas': 'The lounge ceiling and the wall of the room next door.',
        'property.ongoing_risk': 'Water still gets in when it rains, so there is an active leak.',
        'property.habitable': 'We can still live in the house.',
    },
    pack=(
        PackMaterial(
            'home/home-incident-ceiling.jpg',
            'Incident evidence',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'incident_image',
            'image/jpeg',
        ),
        PackMaterial(
            'home/home-incident-wall-second-room.jpg',
            'Incident evidence',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'incident_image',
            'image/jpeg',
        ),
        PackMaterial(
            'home/home-repair-assessment.pdf',
            'Assessment report',
            'external_party',
            Arrival.CLAIMANT_UPLOAD,
            'assessment_report',
            'application/pdf',
            'Supplied by the claimant after claimant-led repairer contact '
            f'(P3-REPAIRER, manual, {FORMS}).',
        ),
        PackMaterial(
            'home/home-consent-record.pdf',
            'Consent record',
            'northwind_staff',
            Arrival.NO_ROUTE,
            note='No home external request route records a disclosure authorisation '
            f'(P3-REPAIRER, manual, {FORMS}).',
        ),
    ),
    unavailable={},
)

CONTENTS = HouseholdScenario(
    scenario_id='contents-damaged-item',
    family='contents',
    pack_id='contents-damaged-item-provisional-1',
    opening=(
        'My laptop fell off the desk at home yesterday morning and the casing and screen were '
        'damaged.'
    ),
    answers={
        **_SHARED_ANSWERS,
        'loss.description': 'The laptop casing is cracked and the screen is broken.',
        'contents.items': (
            'The damaged item is a Dell XPS 13 laptop I bought in 2024 for 2400 dollars.'
        ),
    },
    pack=(
        PackMaterial(
            'contents/contents-item-damaged.jpg',
            'Incident evidence',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'incident_image',
            'image/jpeg',
        ),
        PackMaterial(
            'contents/contents-item-in-situ.jpg',
            'Incident evidence',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'incident_image',
            'image/jpeg',
        ),
        PackMaterial(
            'contents/contents-purchase-receipt.pdf',
            'Proof of ownership',
            'claimant',
            Arrival.CLAIMANT_UPLOAD,
            'proof_of_ownership',
            'application/pdf',
        ),
        PackMaterial(
            'contents/contents-replacement-assessment.pdf',
            'Assessment report',
            'external_party',
            Arrival.CLAIMANT_UPLOAD,
            'assessment_report',
            'application/pdf',
            f'Retrieved and supplied by the claimant (P3-CONTENTS-EVIDENCE, manual, {FORMS}).',
        ),
        PackMaterial(
            'contents/contents-consent-record.pdf',
            'Consent record',
            'northwind_staff',
            Arrival.NO_ROUTE,
            note='No contents external request route records a disclosure authorisation '
            f'(P3-CONTENTS-EVIDENCE, manual, {FORMS}).',
        ),
    ),
    unavailable={'contents.items': 'contents item capture'},
)

SCENARIOS = {scenario.family: scenario for scenario in (HOME, CONTENTS)}


def run_household(scenario: HouseholdScenario, *, head: str) -> HouseholdRun:
    """Run one home or contents journey on a fresh fixture runtime."""

    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    started_at = datetime.now(UTC)
    with TestClient(create_app(settings, repository=FixtureRepository())) as client:
        journey = Journey(client)
        turns, evidence, stopped_at, capabilities = _drive(journey, scenario)
        materials = delivered_materials(journey, scenario.pack, evidence)
        shared = read_both_ends(journey, {})
        state = final_state(journey, shared)

    note = None
    if stopped_at is not None:
        if stopped_at in scenario.unavailable:
            why = 'not captured at this runtime'
        else:
            why = KNOWN_STOPS.get(stopped_at, 'untracked')
        note = f'Intake stopped at {stopped_at} ({why}).'
    record = build_record(
        scenario_id=scenario.scenario_id,
        family=scenario.family,
        pack_id=scenario.pack_id,
        rubric_refs=RUBRIC_REFS,
        settings=settings,
        head=head,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        journey=journey,
        materials=materials,
        turns=turns,
        consents=[],
        seam_checks=[shared.evidence_check] if shared.evidence_check else [],
        visibility_checks=shared.visibility,
        state=state,
        unavailable_capabilities=capabilities,
        stop_note=note,
    )
    return HouseholdRun(record=record, stopped_at=stopped_at)


def _drive(
    journey: Journey, scenario: HouseholdScenario
) -> tuple[list[AgentTurn], dict[str, str], str | None, list[UnavailableCapability]]:
    session = journey.create_working_claim(scenario.family)
    if session is None:
        return [], {}, None, []
    turns: list[AgentTurn] = []
    payload = journey.say('describe the incident', session, scenario.opening)
    if payload is None:
        return turns, {}, None, []
    turns.append(agent_turn('describe the incident', scenario.opening, payload))
    evidence = upload_pack(journey, scenario.pack)
    claim = f'/api/v1/claims/{journey.claim_id}'
    asked: Counter[str] = Counter()

    for turn in range(1, MAX_TURNS + 1):
        proposed = _proposed_fields(payload)
        if proposed:
            confirmed = journey.step(
                f'confirm the proposed facts ({turn})',
                'POST',
                f'{claim}/form/confirmations',
                200,
                'claimant',
                {'field_codes': proposed},
            )
            if confirmed is None:
                return turns, evidence, None, []
        requirements = _requirements(journey)
        if requirements.get('ready'):
            journey.step(CREATE, 'POST', f'{claim}/creation', 201, 'claimant')
            return turns, evidence, None, []
        item = str(requirements.get('next_required_item'))
        if item in scenario.unavailable and asked[item]:
            capability = UnavailableCapability(
                capability=scenario.unavailable[item],
                needed_for=CREATE,
                evidence=(
                    f'{item} was still the next required item after answering it; '
                    f'{CONTROLLED_FIXTURE}.'
                ),
            )
            return turns, evidence, item, [capability]
        answer = scenario.answers.get(item)
        if answer is None or asked[item]:
            journey.step(CREATE, 'POST', f'{claim}/creation', 201, 'claimant')
            return turns, evidence, item, []
        asked[item] += 1
        name = f'answer {item}'
        payload = journey.say(name, session, answer)
        if payload is None:
            return turns, evidence, item, []
        turns.append(agent_turn(name, answer, payload))

    journey.step(CREATE, 'POST', f'{claim}/creation', 201, 'claimant')
    return turns, evidence, 'turn budget', []


def _proposed_fields(payload: dict[str, Any]) -> list[str]:
    return [
        change['field_code']
        for change in payload.get('form_changes', [])
        if (change.get('field') or {}).get('status') == 'proposed'
    ]


def _requirements(journey: Journey) -> dict[str, Any]:
    claim = journey.read(f'/api/v1/claims/{journey.claim_id}', 'claimant')
    return dict((claim.get('dynamic_form') or {}).get('requirements') or {})
