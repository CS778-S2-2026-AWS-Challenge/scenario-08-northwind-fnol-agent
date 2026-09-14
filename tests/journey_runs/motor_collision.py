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
import re
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, NamedTuple, cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.claims_service import MockAssessorServiceAdapter
from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository

from .record import (
    AgentTurn,
    Arrival,
    ClaimantEffort,
    ConsentRecord,
    FinalState,
    InputMaterial,
    JourneyRunRecord,
    RunConfiguration,
    RunStep,
    SeamCheck,
    SeamVerdict,
    StepOutcome,
    VisibilityCheck,
    classify,
    step_outcome,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
JOURNEY_PATH = REPOSITORY_ROOT / 'tests/fixtures/journeys/AT-01-clear-motor-creation.json'
MATERIAL_ROOT = REPOSITORY_ROOT / 'backend/demo_data/materials'
PRINCIPALS = {
    'claimant': {'Authorization': 'Bearer synthetic-claimant'},
    'staff': {'Authorization': 'Bearer synthetic-staff'},
    'integration': {'Authorization': 'Bearer synthetic-integration'},
}

SCENARIO_ID = 'motor-collision-assessor'
PACK_ID = 'motor-collision-provisional-2'
RUBRIC_REFS = ['full-journey completion', 'consistent shared state', 'honest third-party status']
EVIDENCE_LEVEL = 'API projections on the fixture runtime; not browser; no provider contacted'
TRACE_LIMITATION = (
    'The claimant message route returns the compatibility decision projection only; tool calls '
    'and Runtime records stay behind repository boundaries (docs/api.md).'
)
FORMS = 'docs/research/sprint4-third-party-integration-forms.md'


class PackMaterial(NamedTuple):
    """A pack entry: how the material is meant to arrive, not whether it did."""

    path: str
    material_class: str
    provided_by: str
    route: Arrival
    kind: str | None = None
    media_type: str | None = None
    note: str | None = None


# The step whose success delivers a material on each route; uploads are delivered by their own
# completion step.
_DELIVERING_STEP = {
    Arrival.CONSENT_ROUTE: 'consent to the assessor',
    Arrival.SIMULATED_PROVIDER_RESULT: 'receive the assessment',
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
    ),
    PackMaterial(
        'motor/motor-assessment-v2.pdf',
        'Assessment report',
        'external_party',
        Arrival.SIMULATED_PROVIDER_RESULT,
        note='The fixture assessor returns its own result; these bytes are not transmitted.',
    ),
)

# Disagreements already reported to their owner. Any other disagreement is `untracked`.
KNOWN_DEFECTS = {
    'assessor.staff_can_find_work': '#792 F1',
    'assessor.staff_has_an_action': '#792 F2',
}


class _Journey:
    """Issues each step once, records it, and stops at the first step that does not succeed."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.steps: list[RunStep] = []
        self.claim_id = ''
        self._placeholders: dict[str, str] = {}

    def name(self, identifier: str, placeholder: str) -> str:
        self._placeholders[identifier] = placeholder
        return identifier

    def step(
        self,
        name: str,
        method: str,
        path: str,
        expected: int,
        actor: str,
        body: Any = None,
    ) -> dict[str, Any] | None:
        if any(step.outcome is not StepOutcome.SUCCEEDED for step in self.steps):
            return None
        headers = dict(PRINCIPALS[actor])
        if method == 'POST':
            headers['Idempotency-Key'] = re.sub(r'[^a-z0-9]+', '-', name.lower())
            if self.claim_id:
                headers['If-Match'] = str(self.revision())
        response = self.client.request(method, path, headers=headers, json=body)
        payload = cast(dict[str, Any], response.json()) if response.content else {}
        outcome = step_outcome(response.status_code, expected)
        succeeded = outcome is StepOutcome.SUCCEEDED
        error = payload.get('error') or {}
        route = path.split('?')[0]
        for identifier, placeholder in self._placeholders.items():
            route = route.replace(identifier, placeholder)
        self.steps.append(
            RunStep.model_validate(
                {
                    'name': name,
                    'actor': actor,
                    'route': f'{method} {route}',
                    'expected_status': expected,
                    'http_status': response.status_code,
                    'outcome': outcome,
                    'claim_revision': (
                        self.revision()
                        if succeeded and method == 'POST' and self.claim_id
                        else None
                    ),
                    'detail': None if succeeded else f'{error.get("code")}: {error.get("message")}',
                }
            )
        )
        return payload if succeeded else None

    def succeeded(self, name: str) -> bool:
        return any(s.name == name and s.outcome is StepOutcome.SUCCEEDED for s in self.steps)

    def revision(self) -> int:
        return cast(int, self.read(f'/api/v1/claims/{self.claim_id}', 'claimant')['revision'])

    def read(self, path: str, actor: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.client.get(path, headers=PRINCIPALS[actor]).json())

    def items(self, path: str, actor: str) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.read(path, actor).get('items', []))


def current_head() -> str:
    try:
        return subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unknown'


def run_motor_collision(
    *, head: str, pack: tuple[PackMaterial, ...] = MOTOR_COLLISION_PACK
) -> JourneyRunRecord:
    """Run the motor collision journey once, on a fresh fixture runtime."""

    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    started_at = datetime.now(UTC)
    app = create_app(
        settings,
        repository=FixtureRepository(),
        assessor_service_adapter=MockAssessorServiceAdapter(),
    )
    with TestClient(app) as client:
        journey = _Journey(client)
        journey_input = json.loads(JOURNEY_PATH.read_text(encoding='utf-8'))
        turns, evidence = _drive(journey, journey_input, pack)
        materials = _materials(journey, pack, evidence)
        observed = _read_back(journey)

    configuration = RunConfiguration(
        head=head,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        runtime='fixture',
        provider_mode='simulated',
        agent_runtime_profile=settings.agent_runtime_profile.value,
        model_profile_id=settings.model_profile_id,
        evidence_level=EVIDENCE_LEVEL,
    )
    steps = journey.steps
    succeeded = [step.name for step in steps if step.outcome is StepOutcome.SUCCEEDED]
    seam_checks, visibility_checks, consents, final_state = observed
    return JourneyRunRecord(
        run_id=f'{SCENARIO_ID}-{uuid4().hex[:12]}',
        scenario_id=SCENARIO_ID,
        family='motor',
        pack_id=PACK_ID,
        rubric_refs=RUBRIC_REFS,
        configuration=configuration,
        materials=materials,
        steps=steps,
        agent_turns=turns,
        consents=consents,
        visibility_checks=visibility_checks,
        seam_checks=seam_checks,
        final_state=final_state,
        effort=ClaimantEffort(
            **{
                field: sum(name.startswith(prefix) for name in succeeded)
                for field, prefix in (
                    ('messages', 'describe'),
                    ('confirmations', 'confirm'),
                    ('uploads', 'complete upload'),
                    ('consents', 'consent'),
                )
            }
        ),
        result_class=classify(
            steps=steps,
            materials=materials,
            seam_checks=seam_checks,
            visibility_checks=visibility_checks,
            configuration=configuration,
        ),
        result_reason=_reason(steps, materials, seam_checks, visibility_checks),
    )


def _drive(
    journey: _Journey, journey_input: dict[str, Any], pack: tuple[PackMaterial, ...]
) -> tuple[list[AgentTurn], dict[str, str]]:
    motor = {'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'}
    created = journey.step('create working claim', 'POST', '/api/v1/claims', 201, 'claimant', motor)
    if created is None:
        return [], {}
    journey.claim_id = journey.name(created['claim']['claim_id'], '{id}')
    session = journey.name(created['session']['session_id'], '{session_id}')
    claim = f'/api/v1/claims/{journey.claim_id}'
    text = {'type': 'text', 'text': journey_input['input']}
    turn = journey.step(
        'describe the incident',
        'POST',
        f'{claim}/sessions/{session}/messages',
        200,
        'claimant',
        {'client_message_id': 'describe', 'content': text, 'evidence_refs': []},
    )
    turns = [_agent_turn('describe the incident', journey_input['input'], turn)] if turn else []
    evidence = {
        material.path: evidence_id
        for material in pack
        if material.route is Arrival.CLAIMANT_UPLOAD
        and (evidence_id := _upload(journey, material)) is not None
    }
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


def _agent_turn(step: str, claimant_input: str, payload: dict[str, Any]) -> AgentTurn:
    decision = payload.get('decision') or {}
    reply = ((payload.get('agent_message') or {}).get('content') or {}).get('text')
    return AgentTurn(
        step=step,
        claimant_input=claimant_input,
        agent_reply=reply,
        proposed_action=decision.get('action'),
        action_code=decision.get('action_code'),
        reason_codes=decision.get('reason_codes') or [],
        next_step=(decision.get('customer_next_step') or {}).get('status'),
        trace_limitation=TRACE_LIMITATION,
    )


def _upload(journey: _Journey, material: PackMaterial) -> str | None:
    """Request, put, and complete one claimant upload; return its evidence id if requested."""

    content = (MATERIAL_ROOT / material.path).read_bytes()
    claim = f'/api/v1/claims/{journey.claim_id}'
    upload = {
        'kind': material.kind,
        'original_filename': Path(material.path).name,
        'media_type': material.media_type,
        'size_bytes': len(content),
    }
    intent = journey.step(
        f'request upload {material.path}',
        'POST',
        f'{claim}/evidence/uploads',
        201,
        'claimant',
        upload,
    )
    if intent is None:
        return None
    evidence_id = journey.name(intent['evidence_id'], '{evidence_id}')
    app = cast(FastAPI, journey.client.app)
    storage = cast(MockEvidenceStorage, app.state.evidence_storage)
    storage.put_upload(claim_id=journey.claim_id, evidence_id=evidence_id, content=content)
    journey.step(
        f'complete upload {material.path}',
        'POST',
        f'{claim}/evidence/{evidence_id}/complete',
        202,
        'claimant',
        {'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )
    return evidence_id


def _materials(
    journey: _Journey, pack: tuple[PackMaterial, ...], evidence: dict[str, str]
) -> list[InputMaterial]:
    """Record each pack material by what the run observed, not by what the pack declares."""

    materials = []
    for material in pack:
        step = (
            f'complete upload {material.path}'
            if material.route is Arrival.CLAIMANT_UPLOAD
            else _DELIVERING_STEP.get(material.route)
        )
        delivered = step is not None and journey.succeeded(step)
        if delivered or material.route is Arrival.NO_ROUTE:
            arrival, note = material.route, material.note
        else:
            arrival = Arrival.NOT_DELIVERED
            note = f'Not delivered: "{step}" did not succeed in this run.'
        materials.append(
            InputMaterial(
                path=material.path,
                material_class=material.material_class,
                pack_condition='received',
                provided_by=material.provided_by,
                arrival=arrival,
                delivered_at_step=step if delivered else None,
                evidence_kind=material.kind,
                evidence_id=evidence.get(material.path),
                note=note,
            )
        )
    return materials


def _read_back(
    journey: _Journey,
) -> tuple[list[SeamCheck], list[VisibilityCheck], list[ConsentRecord], FinalState]:
    claim_id = journey.claim_id
    claimant = journey.read(f'/api/v1/claims/{claim_id}', 'claimant') if claim_id else {}
    detail = journey.read(f'/api/v1/workbench/claims/{claim_id}', 'staff') if claim_id else {}
    step = claimant.get('customer_next_step') or {}
    party = step.get('responsible_party')
    queue = (detail.get('work_summary') or {}).get('queue_key')
    routed = journey.succeeded('route the assessor')
    checks: list[SeamCheck] = []
    visibility: list[VisibilityCheck] = []
    consents: list[ConsentRecord] = []
    if claim_id:
        claimant_evidence = journey.items(f'/api/v1/claims/{claim_id}/evidence', 'claimant')
        staff_evidence = journey.items(f'/api/v1/workbench/claims/{claim_id}/evidence', 'staff')
        uploaded = {item['evidence_id'] for item in claimant_evidence}
        seen = {item['evidence_id'] for item in staff_evidence}
        external = {
            item['evidence_id']
            for item in staff_evidence
            if item.get('source') == 'external_system'
        }
        requests = journey.items(f'/api/v1/workbench/claims/{claim_id}/external-requests', 'staff')
        request = (requests[0].get('request') or {}) if requests else {}
        owner = (requests[0].get('lifecycle') or {}).get('pending_owner') if requests else None
        listed = {
            item['claim_id']
            for item in journey.items('/api/v1/workbench/claims?view=all&limit=100', 'staff')
        }
        actions = [item['action_code'] for item in detail.get('allowed_actions', [])]
        staff_owned = party == 'claims_professional'

        checks.append(
            _check(
                'evidence.visibility',
                'Does staff see every evidence item the claimant uploaded?',
                f'{len(uploaded)} uploaded',
                f'{len(uploaded & seen)} of them visible',
                SeamVerdict.CONSISTENT if uploaded <= seen else SeamVerdict.CONTRADICTORY,
            )
        )
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
                checks.append(_check(seam, question, claimant_said, staff_said, verdict))
            else:
                checks.append(
                    _check(seam, question, 'not reached', 'not reached', SeamVerdict.UNAVAILABLE)
                )

        staff_only = [
            key for key in ('work_summary', 'allowed_actions', 'ownership') if key in claimant
        ]
        visibility = [
            VisibilityCheck(
                audience='claimant',
                subject=f'staff-only Claim projection fields {staff_only or "none"}',
                expected_visible=False,
                observed_visible=bool(staff_only),
            ),
            VisibilityCheck(
                audience='staff',
                subject='every claimant upload',
                expected_visible=True,
                observed_visible=uploaded <= seen,
            ),
            VisibilityCheck(
                audience='claimant',
                subject='the returned assessment evidence',
                expected_visible=False,
                observed_visible=bool(external & uploaded),
            ),
        ]
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

    sessions = (
        journey.items(f'/api/v1/workbench/claims/{claim_id}/sessions', 'staff') if claim_id else []
    )
    tasks = (
        journey.items(f'/internal/v1/claims/{claim_id}/external-tasks', 'integration')
        if claim_id
        else []
    )
    external_claim = claimant.get('external_claim') or {}
    final_state = FinalState(
        claim_id=claim_id or 'not created',
        claim_number=external_claim.get('claim_number'),
        expected_by=external_claim.get('expected_by'),
        workflow_state=claimant.get('workflow_state'),
        lifecycle_state=detail.get('lifecycle_state'),
        queue_key=queue,
        customer_next_step=step.get('status'),
        next_step_responsible_party=party,
        session_id=sessions[0]['session_id'] if sessions else None,
        session_status=sessions[0].get('status') if sessions else None,
        active_session_id=detail.get('active_session_id'),
        evidence_ids=sorted(
            item['evidence_id']
            for item in (
                journey.items(f'/api/v1/claims/{claim_id}/evidence', 'claimant') if claim_id else []
            )
        ),
        external_task_statuses=[item['task']['status'] for item in tasks],
        handoff_status=(claimant.get('handoff') or {}).get('status'),
    )
    return checks, visibility, consents, final_state


def _check(seam: str, question: str, claimant: str, staff: str, verdict: SeamVerdict) -> SeamCheck:
    disagrees = verdict in {SeamVerdict.CONTRADICTORY, SeamVerdict.MISSING}
    return SeamCheck(
        seam=seam,
        question=question,
        claimant=claimant,
        staff=staff,
        verdict=verdict,
        defect_ref=KNOWN_DEFECTS.get(seam, 'untracked') if disagrees else None,
    )


def _reason(
    steps: list[RunStep],
    materials: list[InputMaterial],
    checks: list[SeamCheck],
    visibility: list[VisibilityCheck],
) -> str:
    stopped = next((step for step in steps if step.outcome is not StepOutcome.SUCCEEDED), None)
    if stopped is not None:
        return f'Stopped at "{stopped.name}" ({stopped.http_status} {stopped.detail}).'
    parts = [f'All {len(steps)} steps succeeded.']
    broken = [check.subject for check in visibility if not check.holds]
    if broken:
        parts.append(f'Visibility does not hold for: {"; ".join(broken)}.')
    for arrival, label in (
        (Arrival.NO_ROUTE, 'No route in'),
        (Arrival.NOT_DELIVERED, 'Not delivered'),
    ):
        paths = [material.path for material in materials if material.arrival is arrival]
        if paths:
            parts.append(f'{label} for {", ".join(paths)}.')
    reported = [
        f'{c.seam} {c.verdict} ({c.defect_ref})' for c in checks if c.defect_ref is not None
    ]
    if reported:
        parts.append(f'Claimant and staff disagree: {"; ".join(reported)}.')
    return ' '.join(parts)
