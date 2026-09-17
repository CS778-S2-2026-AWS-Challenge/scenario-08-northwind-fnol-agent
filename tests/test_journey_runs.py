"""A complete-journey run must reach its end, and its record must not overstate it."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from journey_runs import motor_collision
from journey_runs.__main__ import main as journey_main
from journey_runs.assessor_failures import FAILURE_CASES, run_assessor_failure
from journey_runs.engine import REPOSITORY_ROOT, PackMaterial
from journey_runs.household import (
    CONTENTS,
    CONTENTS_CONFLICTING_OWNERSHIP,
    CONTENTS_EXPIRED_VALUATION,
    CONTENTS_ILLEGIBLE_RECEIPT,
    CONTENTS_NOT_HELD,
    CONTENTS_THEFT,
    HOME,
    HOME_ILLEGIBLE,
    KNOWN_STOPS,
    SCENARIOS,
    HouseholdRun,
    HouseholdScenario,
    household_run_cases,
    run_household,
)
from journey_runs.motor_collision import (
    MOTOR_COLLISION_PACK,
    MOTOR_PACKS,
    motor_run_cases,
    run_motor_collision,
    run_motor_journey,
)
from journey_runs.record import (
    AgentTurn,
    Arrival,
    InputMaterial,
    JourneyRunRecord,
    ResultClass,
    RunConfiguration,
    RunStep,
    SeamCheck,
    SeamVerdict,
    StepOutcome,
    UnavailableCapability,
    VisibilityCheck,
    cited_authority,
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


@pytest.mark.parametrize('scenario', [HOME, CONTENTS], ids=['home', 'contents'])
def test_a_household_journey_stops_only_where_the_stop_is_reported_or_documented(
    scenario: HouseholdScenario,
) -> None:
    _assert_household_run(run_household(scenario, head='test'), scenario)


def test_a_home_household_journey_reaches_creation() -> None:
    run = run_household(HOME, head='test')
    record = run.record

    _assert_household_run(run, HOME)
    assert run.stopped_at is None
    assert (record.steps[-1].name, record.steps[-1].http_status) == ('create the claim', 201)
    assert record.final_state.claim_number is not None
    assert record.unavailable_capabilities == []
    # The selected repair form discloses nothing, so the disclosure authorisation is not
    # applicable rather than missing; a fixture run is still at most fixture-only.
    assert [
        m.path for m in record.materials if m.arrival in {Arrival.NO_ROUTE, Arrival.NOT_DELIVERED}
    ] == []
    assert [
        (m.path, 'P3-REPAIRER' in (m.not_applicable_authority or ''))
        for m in record.materials
        if m.arrival is Arrival.NOT_APPLICABLE
    ] == [('home/home-consent-record.pdf', True)]
    assert record.result_class is ResultClass.FIXTURE_ONLY


def test_the_contents_consent_record_is_not_applicable_under_its_selected_form() -> None:
    record = run_household(CONTENTS, head='test').record

    assert [
        (m.path, 'P3-CONTENTS-EVIDENCE' in (m.not_applicable_authority or ''))
        for m in record.materials
        if m.arrival is Arrival.NOT_APPLICABLE
    ] == [('contents/contents-consent-record.pdf', True)]
    # Contents still stops where item capture is missing; the consent change does not move it.
    assert record.result_class is ResultClass.UNAVAILABLE


def _every_pack_material() -> list[PackMaterial]:
    packs = [MOTOR_COLLISION_PACK, *MOTOR_PACKS.values()]
    packs += [scenario.pack for scenario in SCENARIOS.values()]
    return [material for pack in packs for material in pack]


def test_only_the_manual_form_consent_records_are_not_applicable() -> None:
    not_applicable = {
        material.path
        for material in _every_pack_material()
        if material.route is Arrival.NOT_APPLICABLE
    }

    assert not_applicable == {
        'home/home-consent-record.pdf',
        'contents/contents-consent-record.pdf',
    }
    # The motor assessor path does disclose fields, so its authorisation still has to arrive.
    assert {
        material.route
        for pack in (MOTOR_COLLISION_PACK, *MOTOR_PACKS.values())
        for material in pack
        if material.path == 'motor/motor-consent-record.pdf'
    } == {Arrival.CONSENT_ROUTE}


def test_every_not_applicable_authority_quotes_a_real_document() -> None:
    authorities = {m.authority for m in _every_pack_material() if m.authority is not None}

    assert authorities
    for authority in authorities:
        cited = cited_authority(authority)
        assert cited is not None, authority
        document, passages = cited
        text = ' '.join((REPOSITORY_ROOT / document).read_text(encoding='utf-8').split())
        for passage in passages:
            assert ' '.join(passage.split()) in text, (document, passage)


_FAILURE_SEAMS = {
    'failure.responsible_party',
    'failure.staff_can_find_work',
    'failure.staff_has_a_recovery_action',
    'failure.request_matches_resend',
}


@pytest.mark.parametrize(
    ('case_id', 'result_class'),
    [
        ('retryable-unavailable', ResultClass.FIXTURE_ONLY),
        ('terminal-access-denied', ResultClass.PARTIAL),
        ('terminal-not-required', ResultClass.PARTIAL),
        ('unknown-outcome', ResultClass.FIXTURE_ONLY),
        ('interrupted-dispatch', ResultClass.FIXTURE_ONLY),
    ],
)
def test_an_assessor_failure_recovers_only_through_a_projected_action(
    case_id: str, result_class: ResultClass
) -> None:
    case = FAILURE_CASES[case_id]
    record = run_assessor_failure(case, head='test')

    assert JourneyRunRecord.model_validate_json(record.model_dump_json()) == record
    assert all(check.holds for check in record.visibility_checks)
    # Every recovery step went through an offered action; a refused one would not succeed.
    assert {step.outcome for step in record.steps} == {StepOutcome.SUCCEEDED}
    route = next(step for step in record.steps if step.name == 'route the assessor')
    assert route.http_status == case.route_status
    assert route.detail is not None and route.detail.startswith('Fixture oracle passed')
    assert {check.seam for check in record.seam_checks} >= _FAILURE_SEAMS
    # Both ends agree at every seam; any disagreement fails here, so it reaches its owner.
    assert [check.seam for check in record.seam_checks if check.defect_ref] == []
    assert record.result_class is result_class
    # The reason says where the trajectory ends, not only how many steps succeeded.
    ending = record.final_state.customer_next_step
    assert ending is not None and f'Ends at {ending}' in record.result_reason


def _assert_household_run(run: HouseholdRun, scenario: HouseholdScenario) -> None:
    record = run.record
    assert JourneyRunRecord.model_validate_json(record.model_dump_json()) == record
    assert all(check.holds for check in record.visibility_checks)
    assert [check.seam for check in record.seam_checks if check.defect_ref == 'untracked'] == []
    # The fixture runtime can never produce a completed run, whether or not it reaches creation.
    assert record.result_class is not ResultClass.COMPLETED
    if run.stopped_at is None:
        assert record.steps[-1].name == 'create the claim'
        assert record.steps[-1].outcome is StepOutcome.SUCCEEDED
    elif run.stopped_at in scenario.unavailable:
        assert record.result_class is ResultClass.UNAVAILABLE
        assert [capability.capability for capability in record.unavailable_capabilities] == [
            scenario.unavailable[run.stopped_at]
        ]
    else:
        # A stall nobody has reported must fail here, so it reaches its owner.
        assert run.stopped_at in KNOWN_STOPS
        assert record.result_class in {ResultClass.FAILED, ResultClass.BLOCKED}


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
        'response_body_valid': True,
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
_NOT_APPLICABLE = [
    InputMaterial(
        path='consent.pdf',
        material_class='Consent record',
        pack_condition='received',
        provided_by='northwind_staff',
        arrival=Arrival.NOT_APPLICABLE,
        not_applicable_authority='docs/research/forms.md: "Northwind sends nothing."',
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
_NO_ITEM_CAPTURE = [
    UnavailableCapability(
        capability='contents item capture',
        needed_for='create the claim',
        evidence='The controlled Agent proposed no item; docs/model-gateway.md.',
    )
]


@pytest.mark.parametrize(
    ('changes', 'derived'),
    [
        ({}, ResultClass.COMPLETED),
        ({'configuration': _FIXTURE}, ResultClass.FIXTURE_ONLY),
        ({'materials': _NO_ROUTE}, ResultClass.PARTIAL),
        ({'materials': _NOT_APPLICABLE}, ResultClass.COMPLETED),
        ({'materials': _NOT_APPLICABLE, 'configuration': _FIXTURE}, ResultClass.FIXTURE_ONLY),
        ({'materials': [*_NOT_APPLICABLE, *_NO_ROUTE]}, ResultClass.PARTIAL),
        ({'seam_checks': _DISAGREEING, 'configuration': _FIXTURE}, ResultClass.PARTIAL),
        ({'steps': [_step(409, 'blocked')], 'seam_checks': _DISAGREEING}, ResultClass.BLOCKED),
        ({'visibility_checks': _LEAK}, ResultClass.FAILED),
        (
            {'unavailable_capabilities': _NO_ITEM_CAPTURE, 'configuration': _FIXTURE},
            ResultClass.UNAVAILABLE,
        ),
        (
            {'unavailable_capabilities': _NO_ITEM_CAPTURE, 'steps': [_step(409, 'blocked')]},
            ResultClass.BLOCKED,
        ),
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


@pytest.mark.parametrize(
    'authority',
    [
        None,
        'Northwind sends nothing.',
        'docs/',
        'SPEC/',
        'see docs/research/forms.md: "Northwind sends nothing."',
        'docs/research/forms.md',
        'docs/research/forms.md: "too short"',
    ],
    ids=['missing', 'no-path', 'docs-dir', 'spec-dir', 'embedded', 'no-quote', 'short-quote'],
)
def test_a_not_applicable_authority_must_start_with_a_document_and_quote_it(
    authority: str | None,
) -> None:
    material = _NOT_APPLICABLE[0].model_dump() | {'not_applicable_authority': authority}
    with pytest.raises(ValidationError, match='must start with a repository document path'):
        JourneyRunRecord.model_validate(_record(materials=[material], result_class='completed'))


@pytest.mark.parametrize(
    ('changes', 'message'),
    [
        ({'delivered_at_step': 'step'}, 'cannot name the step'),
        ({'evidence_id': 'evd_1'}, 'cannot name evidence'),
        (
            {'arrival': 'no_route', 'not_applicable_authority': 'docs/x.md'},
            'only a not_applicable material',
        ),
    ],
)
def test_a_material_is_not_applicable_only_with_a_cited_document_and_no_delivery(
    changes: dict[str, Any], message: str
) -> None:
    material = _NOT_APPLICABLE[0].model_dump() | changes
    with pytest.raises(ValidationError, match=message):
        JourneyRunRecord.model_validate(_record(materials=[material], result_class='completed'))


def test_a_capability_is_unavailable_only_for_a_step_the_run_did_not_attempt() -> None:
    attempted = [{**_NO_ITEM_CAPTURE[0].model_dump(), 'needed_for': 'step'}]
    with pytest.raises(ValidationError, match='did attempt'):
        JourneyRunRecord.model_validate(
            _record(unavailable_capabilities=attempted, result_class='unavailable')
        )


def test_a_step_must_carry_response_body_validity_evidence() -> None:
    """The /5 contract requires every step to declare whether its body decoded."""
    step = _step(201, 'succeeded')
    del step['response_body_valid']
    with pytest.raises(ValidationError, match='response_body_valid'):
        JourneyRunRecord.model_validate(_record(steps=[step], result_class='completed'))


def test_the_run_step_schema_lists_response_body_valid_as_required() -> None:
    required = RunStep.model_json_schema().get('required', [])
    assert 'response_body_valid' in required


# --- Multi-turn motor journey fixtures (PRES-01 / PRES-02) -------------------------------


@pytest.mark.parametrize(
    ('fixture_name', 'expected_messages'),
    [('PRES-01', 3), ('PRES-02', 4)],
    ids=['pres01', 'pres02'],
)
def test_a_multi_turn_motor_journey_runs_end_to_end_and_records_honestly(
    fixture_name: str, expected_messages: int
) -> None:
    record = run_motor_journey(fixture_name, head='test')

    assert JourneyRunRecord.model_validate_json(record.model_dump_json()) == record
    # Every step the runner attempted must succeed; a failure would be a new defect to report.
    assert {step.outcome for step in record.steps} == {StepOutcome.SUCCEEDED}
    # Multi-turn journeys replay more than one claimant message.
    assert len(record.agent_turns) >= 3
    assert record.effort.messages == expected_messages == len(record.agent_turns)
    # The handoff / review fixtures do not reach consent or assessor routing, so those
    # pack materials are honestly recorded as not delivered and the run is `partial`.
    assert record.result_class is ResultClass.PARTIAL
    not_delivered = [m.path for m in record.materials if m.arrival is Arrival.NOT_DELIVERED]
    assert 'motor/motor-consent-record.pdf' in not_delivered
    assert 'motor/motor-assessment-v2.pdf' in not_delivered
    # No untracked disagreement.
    assert [check.seam for check in record.seam_checks if check.defect_ref == 'untracked'] == []
    assert all(check.holds for check in record.visibility_checks)
    oracle_steps = [step for step in record.steps if step.detail]
    assert oracle_steps
    assert all(
        step.detail is not None and step.detail.startswith('Fixture oracle passed:')
        for step in oracle_steps
    )
    if fixture_name == 'PRES-02':
        assert record.steps[-2].name == 'staff accept review'
        assert record.steps[-1].name == 'staff resolve review'


def test_the_at01_motor_journey_is_unchanged_after_multi_turn_support() -> None:
    record = run_motor_journey('AT-01', head='test')
    assert len(record.steps) == 14
    assert record.final_state.claim_number is not None
    assert record.result_class is not ResultClass.COMPLETED


def test_the_sprint4_baseline_contains_100_independent_input_pack_pairs() -> None:
    motor = motor_run_cases()
    home = household_run_cases('home')
    contents = household_run_cases('contents')

    assert (len(motor), len(home), len(contents)) == (50, 30, 20)
    assert len({(case.input_payload, case.pack) for case in motor}) == 50
    assert len({case.input_payload for case in motor}) == 50
    assert {case.fixture_name for case in motor} == {'AT-01', 'PRES-01', 'PRES-02'}
    assert {case.input_variant for case in motor} == set(range(50))
    assert {case.pack_id for case in motor} == set(MOTOR_PACKS)
    assert len({(case.scenario_id, case.pack_id) for case in home}) == 30
    assert len({(case.scenario_id, case.pack_id) for case in contents}) == 20


def test_an_oracle_mismatch_returns_a_serializable_failed_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = motor_collision._motor_input

    def mismatching_input(fixture_name: str, variant: int) -> dict[str, Any]:
        journey_input = original(fixture_name, variant)
        first_turn = journey_input['turns'][0]
        first_turn['expected_action'] = 'HANDOFF'
        return journey_input

    monkeypatch.setattr(motor_collision, '_motor_input', mismatching_input)

    result = journey_main(['--scenario', 'motor:PRES-01', '--runs', '1', '--out', str(tmp_path)])
    record_paths = list(tmp_path.glob('*.json'))

    assert result == 0
    assert len(record_paths) == 1
    record = JourneyRunRecord.model_validate_json(record_paths[0].read_text(encoding='utf-8'))
    assert record.result_class is ResultClass.FAILED
    assert 'defect_ref=untracked' in record.result_reason
    assert len(record.steps) == 2
    assert record.steps[-1].outcome is StepOutcome.SUCCEEDED
    assert record.steps[-1].detail is not None
    assert record.steps[-1].detail.startswith('Fixture oracle failed')


@pytest.mark.parametrize(
    ('pack_id', 'condition'),
    [
        ('motor-collision-unreadable-v1', 'invalid'),
        ('motor-collision-conflicting-v1', 'disputed'),
        ('motor-collision-superseded-v1', 'superseded'),
        ('motor-collision-unavailable-v1', 'unavailable'),
    ],
)
def test_motor_material_variants_keep_their_typed_conditions_in_the_record(
    pack_id: str, condition: str
) -> None:
    record = run_motor_journey('AT-01', head='test', pack=MOTOR_PACKS[pack_id], pack_id=pack_id)

    assert condition in {material.pack_condition for material in record.materials}


# --- Household material-variant scenarios ---------------------------------------------------


@pytest.mark.parametrize(
    'scenario',
    [
        HOME_ILLEGIBLE,
        CONTENTS_THEFT,
        CONTENTS_ILLEGIBLE_RECEIPT,
        CONTENTS_EXPIRED_VALUATION,
        CONTENTS_CONFLICTING_OWNERSHIP,
        CONTENTS_NOT_HELD,
    ],
    ids=[
        'home_illegible',
        'contents_theft',
        'contents_illegible_receipt',
        'contents_expired_valuation',
        'contents_conflicting_ownership',
        'contents_not_held',
    ],
)
def test_a_household_material_variant_runs_and_records_its_pack(
    scenario: HouseholdScenario,
) -> None:
    run = run_household(scenario, head='test')
    record = run.record

    assert JourneyRunRecord.model_validate_json(record.model_dump_json()) == record
    assert all(check.holds for check in record.visibility_checks)
    assert [check.seam for check in record.seam_checks if check.defect_ref == 'untracked'] == []
    assert record.result_class is not ResultClass.COMPLETED
    # The variant pack must be reflected in the record's materials.
    pack_paths = {m.path for m in scenario.pack}
    record_paths = {m.path for m in record.materials}
    assert pack_paths == record_paths
    assert {m.path: m.pack_condition for m in record.materials} == {
        m.path: m.condition for m in scenario.pack
    }
    # A variant that adds a NO_ROUTE material must record it as such.
    if scenario.scenario_id == 'contents-damaged-item-authority-not-held':
        assert any(
            m.path == 'contents/contents-authority-outcome-not-held'
            and m.arrival is Arrival.NO_ROUTE
            for m in record.materials
        )
    # A variant that replaces a material must not carry the original.
    if scenario.scenario_id == 'home-water-ingress-illegible-note':
        assert not any(m.path == 'home/home-repair-assessment.pdf' for m in record.materials)
        assert any(m.path == 'home/home-attendance-note-illegible.pdf' for m in record.materials)
