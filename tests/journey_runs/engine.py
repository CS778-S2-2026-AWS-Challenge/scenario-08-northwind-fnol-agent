"""Shared mechanics for complete-journey runners.

A runner owns its scenario: the steps, the pack, and the seam checks that belong to its
journey. This module owns what every runner does the same way:

- issuing and recording route calls;
- uploading claimant materials;
- recording materials by observed delivery;
- reading back the claimant and staff projections both ends share;
- assembling the record.

Route outcomes are classified by `record.classify`. Scenario runners may additionally attach
fixture-oracle comparisons to successful steps and stop when an observable contradicts its fixture.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.core.config import Settings

from .record import (
    ORACLE_FAILURE,
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
    UnavailableCapability,
    VisibilityCheck,
    classify,
    step_outcome,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MATERIAL_ROOT = REPOSITORY_ROOT / 'backend/demo_data/materials'
FORMS = 'docs/research/sprint4-third-party-integration-forms.md'
EVIDENCE_LEVEL = 'API projections on the fixture runtime; not browser; no provider contacted'
TRACE_LIMITATION = (
    'The claimant message route returns the compatibility decision projection only; tool calls '
    'and Runtime records stay behind repository boundaries (docs/api.md).'
)
PRINCIPALS = {
    'claimant': {'Authorization': 'Bearer synthetic-claimant'},
    'staff': {'Authorization': 'Bearer synthetic-staff'},
    'integration': {'Authorization': 'Bearer synthetic-integration'},
}


class PackMaterial(NamedTuple):
    """A pack entry: how the material is meant to arrive, not whether it did.

    `delivered_by` names the step whose success delivers a material that is not a claimant
    upload; an upload is delivered by its own completion step.

    `condition` is the declared material condition (received, invalid, expired, disputed,
    unavailable, superseded). It survives into the record's `pack_condition` so variant
    coverage is distinguishable from ordinary uploads.
    """

    path: str
    material_class: str
    provided_by: str
    route: Arrival
    kind: str | None = None
    media_type: str | None = None
    note: str | None = None
    delivered_by: str | None = None
    condition: Literal[
        'received', 'invalid', 'expired', 'disputed', 'unavailable', 'superseded'
    ] = 'received'


class Journey:
    """Issue and record each step, stopping on route failure or oracle disagreement."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.steps: list[RunStep] = []
        self.claim_id = ''
        self._placeholders: dict[str, str] = {}

    @property
    def stopped(self) -> bool:
        return any(
            step.outcome is not StepOutcome.SUCCEEDED
            or (step.detail is not None and ORACLE_FAILURE in step.detail)
            for step in self.steps
        )

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
        if self.stopped:
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

    def record_oracle(
        self,
        step_name: str,
        expected: Mapping[str, object],
        actual: Mapping[str, object],
        *,
        defect_ref: str = 'untracked',
    ) -> None:
        """Attach a fixture-oracle comparison to a completed route step.

        Args:
            step_name: Name of the route step whose response was checked.
            expected: Observable values declared by the fixture.
            actual: Values read from the route response or subsequent API readback.
            defect_ref: Issue reference for a mismatch, or `untracked` until one is assigned.

        Returns:
            None.

        Raises:
            AssertionError: If the named route step does not exist.
        """

        matched = expected == actual
        if matched:
            detail = f'Fixture oracle passed: expected={dict(expected)!r}; actual={dict(actual)!r}'
        else:
            detail = (
                f'{ORACLE_FAILURE} (defect_ref={defect_ref}): '
                f'expected={dict(expected)!r}; actual={dict(actual)!r}'
            )
        for index in range(len(self.steps) - 1, -1, -1):
            if self.steps[index].name == step_name:
                previous = self.steps[index].detail
                combined = f'{previous}\n{detail}' if previous else detail
                self.steps[index] = self.steps[index].model_copy(update={'detail': combined})
                break
        else:
            raise AssertionError(f'Fixture oracle references missing step {step_name!r}.')

    def revision(self) -> int:
        return cast(int, self.read(f'/api/v1/claims/{self.claim_id}', 'claimant')['revision'])

    def read(self, path: str, actor: str) -> dict[str, Any]:
        return cast(dict[str, Any], self.client.get(path, headers=PRINCIPALS[actor]).json())

    def items(self, path: str, actor: str) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self.read(path, actor).get('items', []))

    def create_working_claim(self, family: str | None) -> str | None:
        body = {'channel': 'web_agent', 'locale': 'en-NZ'}
        if family is not None:
            body['incident_type'] = family
        created = self.step('create working claim', 'POST', '/api/v1/claims', 201, 'claimant', body)
        if created is None:
            return None
        self.claim_id = self.name(created['claim']['claim_id'], '{id}')
        return self.name(created['session']['session_id'], '{session_id}')

    def say(self, name: str, session: str, text: str) -> dict[str, Any] | None:
        return self.step(
            name,
            'POST',
            f'/api/v1/claims/{self.claim_id}/sessions/{session}/messages',
            200,
            'claimant',
            {
                'client_message_id': re.sub(r'[^a-z0-9]+', '-', name.lower()),
                'content': {'type': 'text', 'text': text},
                'evidence_refs': [],
            },
        )


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


def agent_turn(step: str, claimant_input: str, payload: dict[str, Any]) -> AgentTurn:
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


def upload_pack(journey: Journey, pack: Sequence[PackMaterial]) -> dict[str, str]:
    """Upload every claimant material in order; return the evidence id of each requested."""

    return {
        material.path: evidence_id
        for material in pack
        if material.route is Arrival.CLAIMANT_UPLOAD
        and (evidence_id := _upload(journey, material)) is not None
    }


def _upload(journey: Journey, material: PackMaterial) -> str | None:
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


def delivered_materials(
    journey: Journey, pack: Sequence[PackMaterial], evidence: Mapping[str, str]
) -> list[InputMaterial]:
    """Record each pack material by what the run observed, not by what the pack declares."""

    materials = []
    for material in pack:
        step = (
            f'complete upload {material.path}'
            if material.route is Arrival.CLAIMANT_UPLOAD
            else material.delivered_by
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
                pack_condition=material.condition,
                provided_by=material.provided_by,
                arrival=arrival,
                delivered_at_step=step if delivered else None,
                evidence_kind=material.kind,
                evidence_id=evidence.get(material.path),
                note=note,
            )
        )
    return materials


class SharedReadBack(NamedTuple):
    claimant: dict[str, Any]
    detail: dict[str, Any]
    uploaded: set[str]
    staff_evidence: list[dict[str, Any]]
    evidence_check: SeamCheck | None
    visibility: list[VisibilityCheck]


def read_both_ends(journey: Journey, known_defects: Mapping[str, str]) -> SharedReadBack:
    """Read what every journey shares: both projections, evidence, and base visibility."""

    claim_id = journey.claim_id
    if not claim_id:
        return SharedReadBack({}, {}, set(), [], None, [])
    claimant = journey.read(f'/api/v1/claims/{claim_id}', 'claimant')
    detail = journey.read(f'/api/v1/workbench/claims/{claim_id}', 'staff')
    uploaded = {
        item['evidence_id']
        for item in journey.items(f'/api/v1/claims/{claim_id}/evidence', 'claimant')
    }
    staff_evidence = journey.items(f'/api/v1/workbench/claims/{claim_id}/evidence', 'staff')
    seen = {item['evidence_id'] for item in staff_evidence}
    evidence_check = seam_check(
        'evidence.visibility',
        'Does staff see every evidence item the claimant uploaded?',
        f'{len(uploaded)} uploaded',
        f'{len(uploaded & seen)} of them visible',
        SeamVerdict.CONSISTENT if uploaded <= seen else SeamVerdict.CONTRADICTORY,
        known_defects,
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
    ]
    return SharedReadBack(claimant, detail, uploaded, staff_evidence, evidence_check, visibility)


def seam_check(
    seam: str,
    question: str,
    claimant: str,
    staff: str,
    verdict: SeamVerdict,
    known_defects: Mapping[str, str],
) -> SeamCheck:
    disagrees = verdict in {SeamVerdict.CONTRADICTORY, SeamVerdict.MISSING}
    return SeamCheck(
        seam=seam,
        question=question,
        claimant=claimant,
        staff=staff,
        verdict=verdict,
        defect_ref=known_defects.get(seam, 'untracked') if disagrees else None,
    )


def final_state(journey: Journey, shared: SharedReadBack) -> FinalState:
    claim_id = journey.claim_id
    claimant, detail = shared.claimant, shared.detail
    step = claimant.get('customer_next_step') or {}
    sessions = (
        journey.items(f'/api/v1/workbench/claims/{claim_id}/sessions', 'staff') if claim_id else []
    )
    tasks = (
        journey.items(f'/internal/v1/claims/{claim_id}/external-tasks', 'integration')
        if claim_id
        else []
    )
    external_claim = claimant.get('external_claim') or {}
    return FinalState(
        claim_id=claim_id or 'not created',
        claim_number=external_claim.get('claim_number'),
        expected_by=external_claim.get('expected_by'),
        workflow_state=claimant.get('workflow_state'),
        lifecycle_state=detail.get('lifecycle_state'),
        queue_key=(detail.get('work_summary') or {}).get('queue_key'),
        customer_next_step=step.get('status'),
        next_step_responsible_party=step.get('responsible_party'),
        session_id=sessions[0]['session_id'] if sessions else None,
        session_status=sessions[0].get('status') if sessions else None,
        active_session_id=detail.get('active_session_id'),
        evidence_ids=sorted(shared.uploaded),
        external_task_statuses=[item['task']['status'] for item in tasks],
        handoff_status=(claimant.get('handoff') or {}).get('status'),
    )


def build_record(
    *,
    scenario_id: str,
    family: Literal['motor', 'home', 'contents'],
    pack_id: str,
    rubric_refs: list[str],
    settings: Settings,
    head: str,
    started_at: datetime,
    finished_at: datetime,
    journey: Journey,
    materials: list[InputMaterial],
    turns: list[AgentTurn],
    consents: list[ConsentRecord],
    seam_checks: list[SeamCheck],
    visibility_checks: list[VisibilityCheck],
    state: FinalState,
    unavailable_capabilities: list[UnavailableCapability] | None = None,
    stop_note: str | None = None,
) -> JourneyRunRecord:
    configuration = RunConfiguration(
        head=head,
        started_at=started_at,
        finished_at=finished_at,
        runtime='fixture',
        provider_mode='simulated',
        agent_runtime_profile=settings.agent_runtime_profile.value,
        model_profile_id=settings.model_profile_id,
        evidence_level=EVIDENCE_LEVEL,
    )
    steps = journey.steps
    capabilities = unavailable_capabilities or []
    succeeded = [step.name for step in steps if step.outcome is StepOutcome.SUCCEEDED]
    return JourneyRunRecord(
        run_id=f'{scenario_id}-{uuid4().hex[:12]}',
        scenario_id=scenario_id,
        family=family,
        pack_id=pack_id,
        rubric_refs=rubric_refs,
        configuration=configuration,
        materials=materials,
        steps=steps,
        agent_turns=turns,
        consents=consents,
        visibility_checks=visibility_checks,
        seam_checks=seam_checks,
        unavailable_capabilities=capabilities,
        final_state=state,
        effort=ClaimantEffort(
            messages=sum(name.startswith(('describe', 'answer')) for name in succeeded),
            confirmations=sum(name.startswith('confirm') for name in succeeded),
            uploads=sum(name.startswith('complete upload') for name in succeeded),
            consents=sum(name.startswith('consent') for name in succeeded),
        ),
        result_class=classify(
            steps=steps,
            materials=materials,
            seam_checks=seam_checks,
            visibility_checks=visibility_checks,
            configuration=configuration,
            unavailable_capabilities=capabilities,
        ),
        result_reason=_reason(
            steps, materials, seam_checks, visibility_checks, capabilities, stop_note
        ),
    )


def _reason(
    steps: list[RunStep],
    materials: list[InputMaterial],
    checks: list[SeamCheck],
    visibility: list[VisibilityCheck],
    capabilities: list[UnavailableCapability],
    stop_note: str | None,
) -> str:
    oracle_failure = next(
        (step for step in steps if step.detail is not None and ORACLE_FAILURE in step.detail), None
    )
    if oracle_failure is not None:
        return f'Fixture oracle mismatch at "{oracle_failure.name}" ({oracle_failure.detail}).'
    stopped = next((step for step in steps if step.outcome is not StepOutcome.SUCCEEDED), None)
    if stopped is not None:
        reason = f'Stopped at "{stopped.name}" ({stopped.http_status} {stopped.detail}).'
        return f'{reason} {stop_note}' if stop_note else reason
    parts = [f'All {len(steps)} steps succeeded.']
    if capabilities:
        parts.append(
            'Unavailable: '
            + '; '.join(f'{c.capability}, needed for "{c.needed_for}"' for c in capabilities)
            + '.'
        )
    if stop_note:
        parts.append(stop_note)
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
