"""Regression evidence for lodged-history projection and ownership semantics."""

import os
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import mongomock
import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.domain.claim_history import history_window_start, lodged_claim_summary
from backend.domain.models import TerminalDispositionReasonCode, WorkingClaim
from backend.domain.retrieval import PolicyFacts, SeededPolicyRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository


def _lodged_claim(
    identity: str, lodged_at: datetime, *, customer: str = 'customer-1'
) -> WorkingClaim:
    """Build a real model, including the successful creation disposition contract."""
    return WorkingClaim.model_validate(
        {
            'claim_id': identity,
            'customer_id': customer,
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
            'created_at': lodged_at - timedelta(days=3),
            'updated_at': lodged_at,
            'customer_next_step': {
                'status': 'created',
                'summary': 'Claim lodged.',
                'responsible_party': 'system',
            },
            'external_claim': {
                'external_claim_id': f'external-{identity}',
                'claim_number': f'NUMBER-{identity}',
                'creation_status': 'created',
                'route': 'standard_motor_intake',
                'next_step': 'Await review.',
                'source': 'fixture',
                'created_at': lodged_at,
            },
            'terminal_disposition': {
                'value': 'completed',
                'reason_code': 'CLAIM_CREATED',
                'source_refs': [f'external-{identity}'],
                'recorded_by': {'actor_type': 'system', 'actor_id': 'creation'},
                'recorded_at': lodged_at,
                'recorded_revision': 1,
            },
            'form': {
                key: {
                    'value': value,
                    'source': 'claimant',
                    'status': 'confirmed',
                    'needed_for': 'current_action',
                    'updated_at': lodged_at,
                    'updated_by': {'actor_type': 'claimant', 'actor_id': customer},
                }
                for key, value in {
                    'incident.occurred_at': {'date': '2025-09-02', 'precision': 'partial'},
                    'incident.description': 'A synthetic collision. ' * 20,
                    'loss.estimated_amount': 0,
                }.items()
            },
        }
    )


def test_lodged_history_projects_actual_incident_facts_without_fabricated_fallbacks() -> None:
    claim = _lodged_claim('test', datetime(2026, 10, 6, tzinfo=UTC))
    summary = lodged_claim_summary(claim)
    assert summary.claim_number == 'NUMBER-test'
    assert summary.stated_amount == 0
    assert summary.occurred_at is not None and not isinstance(summary.occurred_at, str)
    assert summary.occurred_at.date == '2025-09-02'
    assert summary.occurred_at.precision.value == 'partial'
    assert summary.lodged_at != claim.created_at
    assert len(summary.description or '') == 240
    empty = claim.model_copy(deep=True)
    empty.form = {}
    assert empty.external_claim is not None
    empty.external_claim.claim_number = None
    summary = lodged_claim_summary(empty)
    assert summary.claim_number is None
    assert summary.occurred_at is None
    assert summary.stated_amount is None
    assert summary.description is None
    assert empty.terminal_disposition is not None
    empty.terminal_disposition.reason_code = TerminalDispositionReasonCode.AUTHORISED_CLOSURE
    with pytest.raises(ValueError, match='successfully lodged'):
        lodged_claim_summary(empty)
    empty.terminal_disposition = None
    with pytest.raises(ValueError, match='successfully lodged'):
        lodged_claim_summary(empty)


def test_fixture_history_scopes_counts_limits_and_exact_older_reference() -> None:
    now = datetime(2026, 10, 6, tzinfo=UTC)
    repository = FixtureRepository()
    claims = [
        _lodged_claim('recent', now),
        _lodged_claim('boundary', now.replace(year=2025)),
        _lodged_claim('old', now.replace(year=2024)),
        _lodged_claim('current', now),
        _lodged_claim('other', now, customer='other-customer'),
        _lodged_claim('future', now + timedelta(days=1)),
    ]
    closed = _lodged_claim('closed', now).model_dump(mode='python')
    closed['external_claim'] = None
    closed['terminal_disposition']['value'] = 'closed'
    closed['terminal_disposition']['reason_code'] = 'AUTHORISED_CLOSURE'
    claims.append(WorkingClaim.model_validate(closed))
    inconsistent = _lodged_claim('inconsistent-reason', now)
    assert inconsistent.terminal_disposition is not None
    inconsistent.terminal_disposition.reason_code = TerminalDispositionReasonCode.AUTHORISED_CLOSURE
    claims.append(inconsistent)
    repository._claims = {claim.claim_id: claim for claim in claims}
    result = repository.query_lodged_claim_history(
        'customer-1',
        'current',
        limit=1,
        as_of=now,
    )
    assert result.count_past_12_months == 2
    assert [item.claim_id for item in result.claims] == ['recent']
    for reference in ('old', 'external-old', 'NUMBER-old'):
        result = repository.query_lodged_claim_history(
            'customer-1',
            'current',
            limit=1,
            as_of=now,
            history_reference=reference,
        )
        assert result.count_past_12_months == 2
        assert [item.claim_id for item in result.claims] == ['old']
    result = repository.query_lodged_claim_history(
        'customer-1',
        'current',
        limit=10,
        as_of=now,
        history_reference='NUMBER-other',
    )
    assert result.claims == []


@pytest.mark.parametrize('backend', ['fixture', 'mongodb'])
def test_seeded_policy_insert_only_preserves_changes_and_customer_scope(backend: str) -> None:
    repository = (
        FixtureRepository()
        if backend == 'fixture'
        else MongoDBRepository(mongomock.MongoClient(), 'seed_policy_test')
    )
    record = SeededPolicyRecord(
        customer_id='customer-1',
        facts=PolicyFacts(policy_reference='POLICY-1', status='changed'),
    )
    repository.ensure_seed_policy(record)
    seed = record.model_copy(deep=True)
    seed.facts.status = 'active'
    repository.ensure_seed_policy(seed)
    assert repository.get_seed_policy('customer-1', 'POLICY-1') == record
    assert repository.get_seed_policy('customer-2', 'POLICY-1') is None


@pytest.mark.integration
def test_real_mongodb_history_is_read_only_scoped_and_persistent() -> None:
    """Verify real aggregation, timestamp offsets, retention, and repository reopen."""
    client: MongoClient[Any] = MongoClient(
        os.environ.get(
            'NORTHWIND_MONGODB_TEST_URI',
            'mongodb://localhost:27017/?replicaSet=rs0&directConnection=true',
        ),
        serverSelectionTimeoutMS=750,
    )
    database = f'northwind_history_test_{uuid4().hex}'
    created = False
    try:
        try:
            client.admin.command('ping')
        except PyMongoError as error:
            pytest.skip(f'real MongoDB unavailable: {type(error).__name__}')
        repository = MongoDBRepository(client, database)
        created = True
        now = datetime(2026, 10, 6, tzinfo=UTC)
        boundary = now.replace(year=2025)
        claims = [
            _lodged_claim('recent', now - timedelta(hours=1)),
            _lodged_claim('offset', now.astimezone(timezone(timedelta(hours=-12)))),
            _lodged_claim('boundary', boundary),
            _lodged_claim('before', boundary - timedelta(microseconds=1)),
            _lodged_claim('old', now.replace(year=2024)),
            _lodged_claim('other', now, customer='customer-2'),
            _lodged_claim('current', now),
            _lodged_claim('retained', now),
            _lodged_claim('future', now + timedelta(hours=1)),
        ]
        closed = _lodged_claim('closed', now).model_dump(mode='python')
        closed['external_claim'] = None
        closed['terminal_disposition']['value'] = 'closed'
        closed['terminal_disposition']['reason_code'] = 'AUTHORISED_CLOSURE'
        claims.append(WorkingClaim.model_validate(closed))
        inconsistent = _lodged_claim('inconsistent-reason', now)
        assert inconsistent.terminal_disposition is not None
        inconsistent.terminal_disposition.reason_code = (
            TerminalDispositionReasonCode.AUTHORISED_CLOSURE
        )
        claims.append(inconsistent)
        fixture = FixtureRepository()
        for claim in claims:
            repository._put(
                'claim',
                claim.claim_id,
                claim,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
            )
            if claim.claim_id != 'retained':
                fixture._claims[claim.claim_id] = claim
        repository._collection.insert_one(
            {
                '_id': 'retention-operation',
                'record_type': 'retention_operation',
                'claim_id': 'retained',
            }
        )
        before = list(repository._collection.find({}))
        for reference in (None, 'NUMBER-old', 'external-old', 'old', 'NUMBER-other'):
            actual = repository.query_lodged_claim_history(
                'customer-1',
                'current',
                limit=2,
                as_of=now,
                history_reference=reference,
            )
            expected = fixture.query_lodged_claim_history(
                'customer-1',
                'current',
                limit=2,
                as_of=now,
                history_reference=reference,
            )
            assert actual == expected
            assert actual.count_past_12_months == 3
        assert list(repository._collection.find({})) == before
        reopened = MongoDBRepository(client, database)
        assert [
            item.claim_id
            for item in reopened.query_lodged_claim_history(
                'customer-1',
                'current',
                limit=2,
                as_of=now,
            ).claims
        ] == ['offset', 'recent']
        assert 'claim_customer_lodged_history' in reopened._collection.index_information()
    finally:
        if created:
            client.drop_database(database)
        client.close()


def test_history_window_is_calendar_based_and_requires_bounded_aware_queries() -> None:
    assert history_window_start(datetime(2024, 2, 29, tzinfo=UTC)) == datetime(
        2023,
        2,
        28,
        tzinfo=UTC,
    )
    with pytest.raises(ValueError, match='timezone'):
        history_window_start(datetime(2026, 10, 6))
    repository = FixtureRepository()
    for limit in (0, 51):
        with pytest.raises(ValueError, match='limit'):
            repository.query_lodged_claim_history(
                'customer-1',
                'current',
                limit=limit,
                as_of=datetime(2026, 10, 6, tzinfo=UTC),
            )
