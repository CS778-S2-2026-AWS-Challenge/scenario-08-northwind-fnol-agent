"""Intake triage rules (#1136): every reason, its class, and the boundaries."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.domain.branch_registry import build_default_registry
from backend.domain.models import (
    ActorReference,
    ActorType,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    ClaimCreationStatus,
    ContentsItem,
    ContentsLossType,
    ContentsOwnership,
    Coverage,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    ExternalClaimResult,
    FormSource,
    FormStatus,
    FraudSignal,
    HandoffRecord,
    HandoffStatus,
    HandoffType,
    IntegrationSource,
    MoneyAmount,
    NeededFor,
    RequirementResolution,
    Severity,
    StaffActionStatus,
    StateChange,
    StructuredFormField,
    SupportNeed,
    TriageSource,
    UpdateStaffActionRequest,
    Urgency,
    WorkingClaim,
)
from backend.domain.retrieval import (
    PolicyFacts,
    PolicyRetrievalRecord,
    RetrievalSource,
    RetrievalUncertainty,
)
from backend.domain.triage import DEFAULT_AMOUNT_THRESHOLD, TRIAGE_RULES_VERSION, triage_claim
from backend.repositories.fixture import FixtureRepository
from backend.services import workbench
from backend.services.staff_actions import _apply_state_changes
from tests.issue_928_support import prepare_claim_submission

NOW = datetime(2026, 9, 30, tzinfo=UTC)
POLICY = 'POL-MOTOR-1850'
REGISTRY = build_default_registry()


def _field(value: object, status: FormStatus = FormStatus.CONFIRMED) -> StructuredFormField:
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        status=status,
        needed_for=NeededFor.CURRENT_ACTION,
        updated_at=NOW,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
    )


def _claim(form: dict[str, object] | None = None, **updates: Any) -> WorkingClaim:
    """A created motor Claim that meets every fast-track condition."""
    facts: dict[str, object] = {
        'policy.policy_number': POLICY,
        'claim.product_family': 'motor',
        'incident.injury_or_danger': False,
        'parties.other_parties': False,
        'vehicle.drivable': True,
        'loss.estimated_amount': 1850.0,
    }
    facts.update(form or {})
    claim = WorkingClaim(
        claim_id='clm_triage',
        customer_id='cus_demo',
        channel='web_agent',
        locale='en-NZ',
        incident_type='motor',
        form={code: _field(value) for code, value in facts.items()},
        external_claim=ExternalClaimResult(
            claim_number='NWF-2026-000001',
            creation_status=ClaimCreationStatus.CREATED,
            route='standard_motor_intake',
            next_step='Northwind will contact you.',
            source=IntegrationSource.FIXTURE,
            created_at=NOW,
        ),
        customer_next_step={
            'status': 'created',
            'summary': 'Created.',
            'responsible_party': 'claims_professional',
        },
        created_at=NOW,
        updated_at=NOW,
    )
    return claim.model_copy(update=updates) if updates else claim


def _evidence(kind: str, status: EvidenceStatus = EvidenceStatus.RECEIVED) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f'evd_{kind}',
        claim_id='clm_triage',
        kind=kind,
        status=status,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=NOW,
        updated_at=NOW,
    )


def _policy(uncertain: bool = False) -> PolicyRetrievalRecord:
    return PolicyRetrievalRecord(
        retrieval_id='rtr_policy',
        claim_id='clm_triage',
        source=RetrievalSource(system='fixture', reference=POLICY, retrieved_at=NOW),
        facts=PolicyFacts(policy_reference=POLICY, product='motor', status='active'),
        uncertainty=(
            [RetrievalUncertainty(code='COVERAGE_SECTION_INCOMPLETE', detail='Not stated.')]
            if uncertain
            else []
        ),
    )


def _handoff(status: HandoffStatus = HandoffStatus.RESOLVED) -> HandoffRecord:
    # Triage reads only the handoff type, support need and status.
    return cast(
        HandoffRecord,
        SimpleNamespace(
            type=HandoffType.URGENT_SUPPORT, support_need=SupportNeed.URGENT, status=status
        ),
    )


def _triage(
    claim: WorkingClaim,
    *,
    evidence: list[EvidenceRecord] | None = None,
    handoffs: list[HandoffRecord] | None = None,
    policy_records: list[PolicyRetrievalRecord] | None = None,
    requirements: RequirementResolution | None = None,
) -> Any:
    return triage_claim(
        claim,
        evidence=(
            evidence
            if evidence is not None
            else [_evidence('incident_photo'), _evidence('repair_quote')]
        ),
        handoffs=handoffs or [],
        policy_records=policy_records if policy_records is not None else [_policy()],
        active_branches=['family.motor'],
        requirements=requirements or RequirementResolution(),
        registry=REGISTRY,
    )


def test_a_clear_single_party_claim_is_fast_track() -> None:
    triage = _triage(_claim())

    assert triage.severity is Severity.FAST_TRACK
    assert triage.system_severity is Severity.FAST_TRACK
    assert triage.source is TriageSource.SYSTEM
    assert triage.reasons == []
    assert triage.rules_version == TRIAGE_RULES_VERSION
    assert triage.amount_threshold == DEFAULT_AMOUNT_THRESHOLD == 5000.0


@pytest.mark.parametrize(
    ('change', 'reason', 'severity'),
    [
        ({'form': {'incident.injury_or_danger': True}}, 'injury_or_danger', Severity.COMPLEX),
        (
            {'form': {'parties.other_parties': True, 'incident.liability_position': 'disputed'}},
            'liability_unresolved',
            Severity.COMPLEX,
        ),
        ({'form': {'claim.cover_disagreement': 'excess'}}, 'cover_disagreement', Severity.COMPLEX),
        (
            {'form': {'property.habitable': False}},
            'home_uninhabitable_or_ongoing',
            Severity.COMPLEX,
        ),
        (
            {'form': {'property.ongoing_risk': 'active_leak'}},
            'home_uninhabitable_or_ongoing',
            Severity.COMPLEX,
        ),
        ({'form': {'vehicle.drivable': False}}, 'vehicle_not_drivable', Severity.STANDARD),
        (
            {'form': {'vehicle.towing_required': 'required'}},
            'vehicle_not_drivable',
            Severity.STANDARD,
        ),
        ({'form': {'loss.estimated_amount': 7200.0}}, 'amount_over_threshold', Severity.STANDARD),
        (
            {
                'form': {
                    'parties.other_parties': True,
                    'incident.liability_position': 'other_party_accepts',
                }
            },
            'third_party_recovery',
            Severity.STANDARD,
        ),
    ],
)
def test_each_fact_reason_sets_its_class(
    change: dict[str, Any], reason: str, severity: Severity
) -> None:
    triage = _triage(_claim(change['form']))

    assert reason in triage.reasons
    assert triage.severity is severity


@pytest.mark.parametrize(
    ('claim_update', 'reason', 'severity'),
    [
        ({'claim_state': {'urgency': Urgency.URGENT}}, 'injury_or_danger', Severity.COMPLEX),
        (
            {'claim_state': {'fraud_signal': FraudSignal.REVIEW_REQUIRED}},
            'fraud_review_required',
            Severity.COMPLEX,
        ),
        (
            {'claim_state': {'coverage': Coverage.AMBIGUOUS}},
            'coverage_uncertain',
            Severity.COMPLEX,
        ),
    ],
)
def test_state_reasons_set_their_class(
    claim_update: dict[str, dict[str, object]], reason: str, severity: Severity
) -> None:
    claim = _claim()
    claim = claim.model_copy(
        update={'claim_state': claim.claim_state.model_copy(update=claim_update['claim_state'])}
    )

    triage = _triage(claim)

    assert reason in triage.reasons
    assert triage.severity is severity


def test_record_reasons_come_from_handoffs_lookups_documents_and_requirements() -> None:
    assert 'injury_or_danger' in _triage(_claim(), handoffs=[_handoff()]).reasons
    assert (
        'injury_or_danger'
        not in _triage(_claim(), handoffs=[_handoff(HandoffStatus.CANCELLED)]).reasons
    )
    uncertain = _triage(_claim(), policy_records=[_policy(uncertain=True)])
    assert uncertain.reasons == ['coverage_uncertain']
    assert uncertain.severity is Severity.COMPLEX
    missing_quote = _triage(_claim(), evidence=[_evidence('incident_photo')])
    assert missing_quote.reasons == ['document_outstanding']
    pending_quote = _triage(
        _claim(),
        evidence=[_evidence('incident_photo'), _evidence('repair_quote', EvidenceStatus.PENDING)],
    )
    assert pending_quote.reasons == ['document_outstanding']
    unconfirmed = _triage(
        _claim(), requirements=RequirementResolution(by_state={'proposed': ['incident.location']})
    )
    assert unconfirmed.reasons == ['fact_unresolved']
    routed = _triage(
        _claim(
            assessor_routing=AssessorRoutingResult(
                routing_status=AssessorRoutingStatus.QUEUED,
                queue_reference='asq_1',
                next_step='An assessor will contact you.',
            )
        )
    )
    assert routed.reasons == ['vehicle_not_drivable']


def test_unknown_or_unchecked_never_yields_fast_track() -> None:
    no_amount = _claim()
    no_amount = no_amount.model_copy(
        update={'form': {k: v for k, v in no_amount.form.items() if k != 'loss.estimated_amount'}}
    )
    assert _triage(no_amount).reasons == ['amount_unknown']
    missing_liability = _triage(_claim({'parties.other_parties': True}))
    assert 'liability_unresolved' in missing_liability.reasons
    unknown_liability = _triage(
        _claim({'parties.other_parties': True, 'incident.liability_position': 'unknown'})
    )
    assert unknown_liability.severity is Severity.COMPLEX
    not_looked_up = _triage(_claim(), policy_records=[])
    assert not_looked_up.reasons == ['policy_not_verified']
    assert not_looked_up.severity is Severity.STANDARD
    unconfirmed_amount = _claim()
    unconfirmed_amount = unconfirmed_amount.model_copy(
        update={
            'form': {
                **unconfirmed_amount.form,
                'loss.estimated_amount': _field(1850.0, FormStatus.PROPOSED),
            }
        }
    )
    assert _triage(unconfirmed_amount).reasons == ['amount_unknown']


def test_amount_threshold_boundary_and_contents_total() -> None:
    assert _triage(_claim({'loss.estimated_amount': 5000})).severity is Severity.FAST_TRACK
    assert 'amount_over_threshold' in _triage(_claim({'loss.estimated_amount': 5000.01})).reasons
    items = [
        ContentsItem(
            item_id=f'itm_{index}',
            description=description,
            category='electronics',
            loss_type=ContentsLossType.STOLEN,
            ownership=ContentsOwnership.OWNED,
            estimated_value=MoneyAmount(amount=amount, currency='NZD'),
            source=FormSource.CLAIMANT,
            status=FormStatus.CONFIRMED,
            needed_for=NeededFor.CURRENT_ACTION,
            updated_at=NOW,
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
        )
        for index, (description, amount) in enumerate([('Laptop', 2199.0), ('Headphones', 349.0)])
    ]
    contents = _claim({'loss.estimated_amount': 100}, contents_items=items)
    assert _triage(contents).severity is Severity.FAST_TRACK
    over = _claim({'loss.estimated_amount': 100}, contents_items=[*items, *items[:1]])
    assert 'amount_over_threshold' not in _triage(over).reasons
    assert (
        'amount_over_threshold'
        in _triage(
            _claim({'loss.estimated_amount': 100}, contents_items=[*items, *items, *items])
        ).reasons
    )


def test_a_found_policy_without_uncertainty_is_not_complex() -> None:
    claim = _claim()
    claim = claim.model_copy(
        update={
            'claim_state': claim.claim_state.model_copy(
                update={'coverage': Coverage.REVIEW_REQUIRED}
            )
        }
    )

    assert _triage(claim).severity is Severity.FAST_TRACK


def test_accepted_photo_and_ownership_kinds_satisfy_document_requirements() -> None:
    contents = triage_claim(
        _claim(),
        evidence=[_evidence('item_photo'), _evidence('receipt')],
        handoffs=[],
        policy_records=[_policy()],
        active_branches=['family.contents'],
        requirements=RequirementResolution(),
        registry=REGISTRY,
    )
    assert contents is not None
    assert 'document_outstanding' not in contents.reasons


def test_no_triage_before_the_claim_is_created() -> None:
    assert _triage(_claim(external_claim=None)) is None


def test_a_staff_decision_locks_the_result_and_keeps_the_rule_outcome() -> None:
    claim = _claim({'incident.injury_or_danger': True})
    decided = _apply_state_changes(
        claim,
        UpdateStaffActionRequest(
            status=StaffActionStatus.COMPLETED,
            state_changes=[StateChange(path='claim_state.severity', to='standard')],
        ),
    )

    triage = _triage(decided)

    assert decided.claim_state.severity is Severity.STANDARD
    assert triage.severity is Severity.STANDARD
    assert triage.source is TriageSource.STAFF
    assert triage.system_severity is Severity.COMPLEX
    assert triage.reasons == ['injury_or_danger']
    released = _apply_state_changes(
        decided,
        UpdateStaffActionRequest(
            status=StaffActionStatus.COMPLETED,
            state_changes=[StateChange(path='claim_state.severity', to='unassessed')],
        ),
    )
    assert _triage(released).source is TriageSource.SYSTEM


def test_workbench_triages_a_created_claim_and_claimants_never_see_it(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    journey_input = json.loads(
        (
            Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'
        ).read_text(encoding='utf-8')
    )['input']
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'triage-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    ).json()
    claim_id = created['claim']['claim_id']
    session_id = created['session']['session_id']
    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **auth_headers,
            'Idempotency-Key': 'triage-description',
            'If-Match': str(created['claim']['revision']),
        },
        json={
            'client_message_id': 'triage-description',
            'content': {'type': 'text', 'text': journey_input},
            'evidence_refs': [],
        },
    ).json()
    confirmed = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **auth_headers,
            'Idempotency-Key': 'triage-confirm',
            'If-Match': str(turn['claim_revision']),
        },
        json={'field_codes': sorted({item['field_code'] for item in turn['form_changes']})},
    ).json()
    completed = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={
            **auth_headers,
            'Idempotency-Key': 'triage-complete',
            'If-Match': str(confirmed['revision']),
        },
        json={
            'updates': [
                {'field_code': 'vehicle.drivable', 'value': True},
                {'field_code': 'incident.liability_position', 'value': 'other_party_accepts'},
            ]
        },
    ).json()
    assert completed['customer_next_step']['status'] == 'ready_to_create'

    before = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    assert before.status_code == 200, before.text
    assert before.json()['triage'] is None
    assert before.json()['claim_state']['severity'] == 'unassessed'

    revision = prepare_claim_submission(
        client, auth_headers, claim_id, completed['revision'], key='triage-submit'
    )
    creation = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={**auth_headers, 'Idempotency-Key': 'triage-create', 'If-Match': str(revision)},
    )
    assert creation.status_code == 201, creation.text

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers).json()
    triage = detail['triage']
    assert triage['severity'] == triage['system_severity'] == 'standard'
    assert triage['source'] == 'system'
    # Another car accepted fault; no amount, policy lookup or repair quote is on file yet.
    assert set(triage['reasons']) >= {
        'third_party_recovery',
        'amount_unknown',
        'policy_not_verified',
        'document_outstanding',
    }
    assert detail['claim_state']['severity'] == 'standard'
    listed = client.get(
        '/api/v1/workbench/claims',
        params={'view': 'completed', 'search': claim_id},
        headers=staff_auth_headers,
    ).json()
    item = next(entry for entry in listed['items'] if entry['claim_id'] == claim_id)
    assert item['triage']['severity'] == 'standard'

    claimant_payloads = [
        client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers).text,
        client.get('/api/v1/claims', headers=auth_headers).text,
        client.get(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages', headers=auth_headers
        ).text,
        creation.text,
    ]
    for payload in claimant_payloads:
        assert '"triage"' not in payload
        assert '"severity"' not in payload
        assert 'third_party_recovery' not in payload
        assert 'fast_track' not in payload


def test_the_amount_threshold_comes_from_settings() -> None:
    with pytest.raises(ValueError, match='NORTHWIND_TRIAGE_AMOUNT_THRESHOLD_NZD'):
        Settings(environment='test', triage_amount_threshold_nzd=0)
    create_app(Settings(environment='test', triage_amount_threshold_nzd=1000), FixtureRepository())
    try:
        triage = workbench._claim_triage(FixtureRepository(), _claim(), [], [])
        assert triage is not None
        assert triage.amount_threshold == 1000
        assert 'amount_over_threshold' in triage.reasons
    finally:
        create_app(Settings(environment='test'), FixtureRepository())
    default = workbench._claim_triage(FixtureRepository(), _claim(), [], [])
    assert default is not None
    assert default.amount_threshold == DEFAULT_AMOUNT_THRESHOLD
