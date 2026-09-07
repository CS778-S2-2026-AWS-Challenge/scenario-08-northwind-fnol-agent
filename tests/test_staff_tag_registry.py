from dataclasses import replace
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

import backend.domain.tag_registry as tag_registry
from backend.domain.models import (
    ActorReference,
    ActorType,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    FormSource,
    FormStatus,
    FraudSignal,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    Urgency,
)
from backend.domain.tag_registry import (
    STAFF_TAG_REGISTRY,
    TAG_REGISTRY_VERSION,
    TagCategory,
    TagDefinitionStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.support import now_utc


def _create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    incident_type: str,
    key: str,
) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': incident_type},
    )
    assert response.status_code == 201
    return str(response.json()['claim']['claim_id'])


def _confirmed(value: object, field_ref: str) -> StructuredFormField:
    timestamp = now_utc()
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        source_refs=[field_ref],
        status=FormStatus.CONFIRMED,
        needed_for=NeededFor.CURRENT_ACTION,
        updated_at=timestamp,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
    )


def test_registry_contains_the_approved_staff_facing_catalogue() -> None:
    assert TAG_REGISTRY_VERSION == '0.2'
    assert len(STAFF_TAG_REGISTRY) == 106
    counts = {
        category: sum(definition.category is category for definition in STAFF_TAG_REGISTRY.values())
        for category in TagCategory
    }
    assert counts == {
        TagCategory.CLAIM_TYPE: 5,
        TagCategory.INCIDENT: 18,
        TagCategory.PEOPLE_SAFETY: 12,
        TagCategory.STAKEHOLDER: 16,
        TagCategory.IMPACT: 16,
        TagCategory.EVIDENCE: 12,
        TagCategory.PROGRESS: 15,
        TagCategory.ATTENTION: 12,
    }
    assert (
        sum(
            definition.status is TagDefinitionStatus.PUBLISHED
            for definition in STAFF_TAG_REGISTRY.values()
        )
        == 103
    )
    assert STAFF_TAG_REGISTRY['injury.none_reported'].staff_label == 'No injuries reported'
    assert STAFF_TAG_REGISTRY['stakeholder.police'].staff_label == 'Police involved'
    assert STAFF_TAG_REGISTRY['attention.fraud_l2'].staff_label == 'Fraud concern · Level 2'


def test_workbench_projects_human_readable_tags_from_authoritative_records(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _create_claim(
        client,
        auth_headers,
        incident_type='motor',
        key='tag-projection-motor',
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    form = {
        **claim.form,
        'incident.injury_or_danger': _confirmed(False, 'msg_no_injuries'),
        'vehicle.drivable': _confirmed(False, 'msg_not_drivable'),
        'authorities.police_report_reference': StructuredFormField(
            value=None,
            source=FormSource.CLAIMANT,
            source_refs=['msg_police_pending'],
            status=FormStatus.PENDING_GENERATION,
            needed_for=NeededFor.LATER_ACTION,
            updated_at=now_utc(),
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
        ),
    }
    repository.save_claim(
        claim.model_copy(
            update={
                'revision': claim.revision + 1,
                'form': form,
                'claim_state': claim.claim_state.model_copy(
                    update={'fraud_signal': FraudSignal.REVIEW_REQUIRED}
                ),
                'updated_at': now_utc(),
            }
        ),
        expected_revision=claim.revision,
    )
    timestamp = now_utc()
    repository.save_evidence(
        EvidenceRecord(
            evidence_id='evd_tag_police',
            claim_id=claim_id,
            kind='police_report',
            status=EvidenceStatus.PENDING_GENERATION,
            file_status=EvidenceFileStatus.NOT_AVAILABLE,
            source=EvidenceSource.CLAIMANT,
            related_fields=['authorities.police_report_reference'],
            needed_for=['later_action'],
            responsible_party=ResponsibleParty.EXTERNAL_PARTY,
            created_at=timestamp,
            updated_at=timestamp,
        ),
        'cus_demo',
    )

    response = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    tags = {item['code']: item for item in response.json()['tags']}
    assert tags['claim_type.motor']['label'] == 'Motor claim'
    assert tags['injury.none_reported']['label'] == 'No injuries reported'
    assert tags['safety.scene_safe_reported']['basis'] == 'reported'
    assert tags['stakeholder.police']['label'] == 'Police involved'
    assert tags['impact.vehicle_not_drivable']['label'] == 'Vehicle not drivable'
    assert tags['evidence.police_report_pending']['label'] == 'Police report pending'
    assert tags['progress.awaiting_external']['label'] == 'Awaiting external party'
    assert not any(code.startswith('attention.fraud_') for code in tags)


def test_workbench_tag_filter_uses_the_published_backend_registry(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    motor_id = _create_claim(
        client,
        auth_headers,
        incident_type='motor',
        key='tag-filter-motor',
    )
    home_id = _create_claim(
        client,
        auth_headers,
        incident_type='home',
        key='tag-filter-home',
    )

    response = client.get(
        '/api/v1/workbench/claims?tag=claim_type.home',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    assert [item['claim_id'] for item in response.json()['items']] == [home_id]
    assert motor_id not in {item['claim_id'] for item in response.json()['items']}

    unknown = client.get(
        '/api/v1/workbench/claims?tag=made_up_tag',
        headers=staff_auth_headers,
    )
    draft_only = client.get(
        '/api/v1/workbench/claims?tag=stakeholder.engineer_specialist',
        headers=staff_auth_headers,
    )
    retired_code = 'claim_type.retired_test'
    retired = replace(
        STAFF_TAG_REGISTRY['claim_type.motor'],
        code=retired_code,
        status=TagDefinitionStatus.RETIRED,
    )
    monkeypatch.setattr(
        tag_registry,
        'STAFF_TAG_REGISTRY',
        MappingProxyType({**STAFF_TAG_REGISTRY, retired_code: retired}),
    )
    retired_only = client.get(
        f'/api/v1/workbench/claims?tag={retired_code}',
        headers=staff_auth_headers,
    )
    assert unknown.status_code == 400
    assert unknown.json()['error']['code'] == 'INVALID_TAG_FILTER'
    assert draft_only.status_code == 400
    assert draft_only.json()['error']['code'] == 'INVALID_TAG_FILTER'
    assert retired_only.status_code == 400
    assert retired_only.json()['error']['code'] == 'INVALID_TAG_FILTER'


def test_claimant_projection_does_not_expose_staff_tags(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    claim_id = _create_claim(
        client,
        auth_headers,
        incident_type='contents',
        key='tag-claimant-boundary',
    )

    response = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)

    assert response.status_code == 200
    assert 'tags' not in response.json()


def test_generic_urgency_does_not_invent_or_duplicate_scene_safety_tags(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _create_claim(
        client,
        auth_headers,
        incident_type='motor',
        key='tag-urgent-scene-boundary',
    )
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    repository.save_claim(
        claim.model_copy(
            update={
                'revision': claim.revision + 1,
                'claim_state': claim.claim_state.model_copy(update={'urgency': Urgency.URGENT}),
                'updated_at': now_utc(),
            }
        ),
        expected_revision=claim.revision,
    )

    response = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )

    assert response.status_code == 200
    codes = {item['code'] for item in response.json()['tags']}
    assert 'safety.scene_uncertain' in codes
    assert 'safety.scene_unsafe' not in codes
    assert (
        len(codes & {'safety.scene_safe_reported', 'safety.scene_uncertain', 'safety.scene_unsafe'})
        == 1
    )
