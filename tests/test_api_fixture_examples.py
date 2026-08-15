import json
import re
from pathlib import Path
from typing import Any, cast

from backend.domain.models import (
    ClaimantClaim,
    ClaimantEvidence,
    ClaimantSession,
    EvidenceListResponse,
    FormPatchResponse,
    MessageListResponse,
    MessageVisibility,
)
from backend.repositories.scenario_loader import load_scenario

FIXTURE_DIRECTORY = Path(__file__).parent / 'fixtures'
PUBLIC_FIXTURE_PATH = FIXTURE_DIRECTORY / 'api' / 'AT-08-resume-public.json'
DOMAIN_FIXTURE_PATH = FIXTURE_DIRECTORY / 'scenarios' / 'AT-08-resume.json'

STORAGE_SPECIFIC_KEYS = {
    'aws_object_key',
    'aws_region',
    'bucket_name',
    'dynamodb_table',
    'dynamodb_table_name',
    'dynamodb_index_name',
    'dynamodb_key',
    'iam',
    'iam_role',
    'index_name',
    'object_key',
    'object_reference',
    'partition_key',
    'pk',
    'provider_metadata',
    's3_key',
    's3_object_key',
    's3_uri',
    'sk',
    'sort_key',
    'storage_key',
    'storage_metadata',
    'storage_reference',
    'table_name',
}
LOGICAL_KEY_PREFIXES = (
    'CLAIM#',
    'CUSTOMER#',
    'DECISION#',
    'EVIDENCE#',
    'MESSAGE#',
    'SESSION#',
)


def load_public_fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(PUBLIC_FIXTURE_PATH.read_text(encoding='utf-8')),
    )


def normalise_key(key: str) -> str:
    return key.strip().lower().replace('-', '_')


def is_storage_specific_key(key: str) -> bool:
    normalised = normalise_key(key)
    return (
        normalised in STORAGE_SPECIFIC_KEYS
        or re.fullmatch(r'(?:gsi|lsi)\d+(?:pk|sk)', normalised) is not None
    )


def is_storage_specific_value(value: str) -> bool:
    normalised = value.strip()
    upper_value = normalised.upper()
    lower_value = normalised.lower()
    return (
        upper_value.startswith(LOGICAL_KEY_PREFIXES)
        or lower_value.startswith(('arn:aws:', 's3://'))
        or '.amazonaws.com' in lower_value
    )


def collect_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, nested_value in value.items():
            keys.add(normalise_key(str(key)))
            keys.update(collect_keys(nested_value))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(collect_keys(item))
        return keys
    return set()


def collect_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        strings: list[str] = []
        for nested_value in value.values():
            strings.extend(collect_strings(nested_value))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(collect_strings(item))
        return strings
    return [value] if isinstance(value, str) else []


def test_api_fixture_examples_match_current_public_response_models() -> None:
    fixture = load_public_fixture()

    assert set(fixture) == {'claim', 'session', 'messages', 'form', 'evidence'}
    ClaimantClaim.model_validate(fixture['claim'])
    ClaimantSession.model_validate(fixture['session'])
    MessageListResponse.model_validate(fixture['messages'])
    FormPatchResponse.model_validate(fixture['form'])
    EvidenceListResponse.model_validate(fixture['evidence'])


def test_api_fixture_reuses_canonical_at08_records_and_relationships() -> None:
    fixture = load_public_fixture()
    scenario = load_scenario(DOMAIN_FIXTURE_PATH)
    claim = ClaimantClaim.model_validate(fixture['claim'])
    session = ClaimantSession.model_validate(fixture['session'])
    messages = MessageListResponse.model_validate(fixture['messages'])
    form = FormPatchResponse.model_validate(fixture['form'])
    evidence = EvidenceListResponse.model_validate(fixture['evidence'])

    canonical_session = next(
        item for item in scenario.sessions if item.session_id == scenario.claim.active_session_id
    )
    assert claim.claim_id == scenario.claim.claim_id
    assert claim.revision == scenario.claim.revision
    assert claim.incident_type == scenario.claim.incident_type
    assert claim.workflow_state == scenario.claim.claim_state.workflow_state
    assert claim.form == scenario.claim.form
    assert claim.evidence_summary == scenario.claim.evidence_summary
    assert claim.external_claim == scenario.claim.external_claim
    assert claim.customer_next_step == scenario.claim.customer_next_step
    assert claim.created_at == scenario.claim.created_at
    assert claim.updated_at == scenario.claim.updated_at
    assert session.session_id == canonical_session.session_id
    assert session.claim_id == claim.claim_id
    assert session.status == canonical_session.status
    assert session.resume.summary == canonical_session.summary
    assert session.resume.unresolved_questions == canonical_session.unresolved_questions
    assert session.resume.pending_items == canonical_session.pending_items
    assert session.resume.prior_commitments == canonical_session.prior_commitments
    assert session.resume.customer_next_step == scenario.claim.customer_next_step
    assert session.started_at == canonical_session.started_at
    assert session.last_active_at == canonical_session.last_active_at
    assert session.closed_at == canonical_session.closed_at
    assert canonical_session.context_revision <= scenario.claim.revision
    assert canonical_session.context_revision < claim.revision

    assert messages.items == []
    assert session.last_active_at == session.started_at
    assert claim.created_at <= session.started_at <= session.last_active_at <= claim.updated_at

    public_message_ids = [message.message_id for message in messages.items]
    canonical_public_messages = [
        message
        for message in scenario.messages
        if message.session_id == canonical_session.session_id
        and message.visibility is not MessageVisibility.INTERNAL_ONLY
    ]
    assert public_message_ids == [message.message_id for message in canonical_public_messages]
    canonical_messages_by_id = {
        message.message_id: message for message in canonical_public_messages
    }
    for message in messages.items:
        canonical_message = canonical_messages_by_id[message.message_id]
        assert message.actor == canonical_message.actor
        assert message.content == canonical_message.content
        assert message.evidence_refs == canonical_message.evidence_refs
        assert message.in_reply_to == canonical_message.in_reply_to
        assert message.created_at == canonical_message.created_at

    evidence_ids = {item.evidence_id for item in evidence.items}
    assert evidence.claim_id == claim.claim_id
    assert evidence.revision == claim.revision
    assert form.claim_id == claim.claim_id
    assert form.revision == claim.revision
    assert form.updated_fields == scenario.claim.form
    assert form.customer_next_step == scenario.claim.customer_next_step
    assert evidence.customer_next_step == scenario.claim.customer_next_step
    messages_by_id = {message.message_id: message for message in messages.items}
    evidence_by_id = {item.evidence_id: item for item in evidence.items}
    canonical_public_history_by_id = {
        message.message_id: message
        for message in scenario.messages
        if message.visibility is not MessageVisibility.INTERNAL_ONLY
    }
    for field in form.updated_fields.values():
        assert set(field.source_refs) <= set(canonical_public_history_by_id)
        assert all(
            canonical_public_history_by_id[source_ref].created_at <= field.updated_at
            for source_ref in field.source_refs
        )
    for message in messages.items:
        assert set(message.evidence_refs) <= evidence_ids
        assert message.in_reply_to is None or message.in_reply_to in public_message_ids
        assert all(
            evidence_by_id[evidence_ref].created_at <= message.created_at
            for evidence_ref in message.evidence_refs
        )
        if message.in_reply_to is not None:
            assert messages_by_id[message.in_reply_to].created_at <= message.created_at

    canonical_evidence_by_id = {item.evidence_id: item for item in scenario.evidence}
    assert evidence_ids == set(canonical_evidence_by_id)
    for item in evidence.items:
        canonical_evidence = canonical_evidence_by_id[item.evidence_id]
        for field_name in ClaimantEvidence.model_fields:
            assert getattr(item, field_name) == getattr(canonical_evidence, field_name)
        assert claim.created_at <= item.created_at <= item.updated_at <= claim.updated_at


def test_internal_messages_and_evidence_provenance_are_not_public() -> None:
    fixture = load_public_fixture()
    scenario = load_scenario(DOMAIN_FIXTURE_PATH)
    public_message_ids = {
        item['message_id'] for item in cast(list[dict[str, Any]], fixture['messages']['items'])
    }
    internal_message_ids = {
        message.message_id
        for message in scenario.messages
        if message.visibility is MessageVisibility.INTERNAL_ONLY
    }

    assert internal_message_ids
    assert public_message_ids.isdisjoint(internal_message_ids)
    assert 'context_revision' not in cast(dict[str, Any], fixture['session'])
    assert all(item.provenance for item in scenario.evidence)
    assert all(
        'provenance' not in item
        for item in cast(list[dict[str, Any]], fixture['evidence']['items'])
    )


def test_public_fixture_contains_no_storage_specific_keys_or_values() -> None:
    fixture = load_public_fixture()
    keys = collect_keys(fixture)
    forbidden_keys = {key for key in keys if is_storage_specific_key(key)}
    storage_values = [
        value for value in collect_strings(fixture) if is_storage_specific_value(value)
    ]

    assert forbidden_keys == set()
    assert storage_values == []


def test_storage_leakage_rules_cover_nested_provider_fields_without_domain_false_positives() -> (
    None
):
    provider_payload = {
        'PK': 'claim#clm_fixture',
        'message': {
            'content': {
                'DynamoDB-Index-Name': 'claims-by-customer',
                'LSI2SK': 'message#msg_fixture',
            }
        },
        'form': {'value': {'s3_uri': 'S3://synthetic-bucket/object'}},
    }
    domain_payload = {
        'region': 'Auckland',
        'table': 'A dining table was damaged.',
        'bucket': 'A household bucket was damaged.',
    }

    assert {key for key in collect_keys(provider_payload) if is_storage_specific_key(key)} == {
        'dynamodb_index_name',
        'lsi2sk',
        'pk',
        's3_uri',
    }
    assert [
        value for value in collect_strings(provider_payload) if is_storage_specific_value(value)
    ] == [
        'claim#clm_fixture',
        'message#msg_fixture',
        'S3://synthetic-bucket/object',
    ]
    assert not any(is_storage_specific_key(key) for key in collect_keys(domain_payload))
    assert not any(is_storage_specific_value(value) for value in collect_strings(domain_payload))
