import gc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from backend.adapters.identity import FixtureIdentityRepository, SQLiteIdentityRepository
from backend.adapters.staff_identity import FixtureStaffIdentityRepository
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.identity import CustomerAccountRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    DemoSeedConflict,
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
    ValidationSeedGraph,
)
from backend.repositories.scenario_loader import load_scenario
from backend.services.demo_seed import (
    VALIDATION_SEED_ROUTE,
    _ensure_demo_claimant,
    _validation_presence,
    _validation_scenario,
    seed_validation_scenarios,
)

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
SEED_PATH = '/api/v1/workbench/demo/seed-validation'
SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def _validation_graph(repository: PersistenceRepository, key: str = 'graph') -> ValidationSeedGraph:
    scenario = _validation_scenario(
        load_scenario(Path('backend/demo_data/scenarios/AT-14-field-states-motor.json')),
        customer_id='cus_demo',
        staff_id='stf_demo',
    )
    presence, expected_presence_revision = _validation_presence(repository, 'stf_demo')
    response_payload = {
        'status': 'seeded',
        'scenario_ids': ['AT-14-field-states-motor'],
        'claim_ids': [scenario.claim.claim_id],
    }
    return ValidationSeedGraph(
        claims=(scenario.claim,),
        sessions=tuple(scenario.sessions),
        messages=tuple(scenario.messages),
        evidence=tuple(scenario.evidence),
        staff_presence=presence,
        expected_presence_revision=expected_presence_revision,
        idempotency=IdempotencyRecord(
            actor_id='stf_demo',
            route=VALIDATION_SEED_ROUTE,
            key=key,
            request_fingerprint='validation-seed-v1',
            claim_id=scenario.claim.claim_id,
            session_id=scenario.claim.active_session_id or '',
            response_payload=response_payload,
        ),
    )


def test_validation_seed_creates_three_cross_role_graphs() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'seed-1'})

        assert response.status_code == 200
        body = response.json()
        assert body['scenario_ids'] == [
            'AT-14-field-states-motor',
            'AT-15-field-states-home',
            'AT-16-field-states-contents',
        ]
        assert len(body['claim_ids']) == 3
        assert client.get('/api/v1/staff/me', headers=STAFF_AUTH).status_code == 200

        for claim_id in body['claim_ids']:
            staff_claim = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)
            claimant_claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)
            claimant_evidence = client.get(
                f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH
            )
            assert staff_claim.status_code == 200
            assert claimant_claim.status_code == 200
            assert claimant_evidence.status_code == 200
            stored_claim = repository.get_claim_internal(claim_id)
            assert stored_claim is not None
            assert stored_claim.assignee_id == 'stf_demo'
            assert claimant_claim.json()['claim_id'] == claim_id

            staff_sessions = client.get(
                f'/api/v1/workbench/claims/{claim_id}/sessions', headers=STAFF_AUTH
            )
            assert staff_sessions.status_code == 200
            assert len(staff_sessions.json()['items']) == 1
            session_id = staff_sessions.json()['items'][0]['session_id']
            messages = client.get(
                f'/api/v1/workbench/claims/{claim_id}/sessions/{session_id}/messages',
                headers=STAFF_AUTH,
            )
            evidence = client.get(
                f'/api/v1/workbench/claims/{claim_id}/evidence', headers=STAFF_AUTH
            )
            assert len(messages.json()['items']) == 4
            assert len(evidence.json()['items']) == 1
            assert {item['evidence_id'] for item in claimant_evidence.json()['items']} == {
                evidence.json()['items'][0]['evidence_id']
            }
            assert messages.json()['items'][-1]['evidence_refs'] == [
                evidence.json()['items'][0]['evidence_id']
            ]
            assert staff_claim.json()['claim_state']['evidence'] == 'unofficial'
            assert staff_claim.json()['section_summaries']['evidence']['needs_attention'] == 1

        contents_id = body['claim_ids'][2]
        contents = client.get(f'/api/v1/claims/{contents_id}', headers=CLAIMANT_AUTH).json()
        assert len(contents['contents_items']) == 2
        assert all('item_id' in item for item in contents['contents_items'])


def test_validation_seed_is_idempotent_and_requires_empty_queue() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        headers = {**STAFF_AUTH, 'Idempotency-Key': 'seed-replay'}
        first = client.post(SEED_PATH, headers=headers)
        replay = client.post(SEED_PATH, headers=headers)
        changed_key = client.post(
            SEED_PATH,
            headers={**STAFF_AUTH, 'Idempotency-Key': 'seed-other'},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert changed_key.status_code == 409
    assert changed_key.json()['error']['code'] == 'DEMO_SEED_REQUIRES_EMPTY_QUEUE'
    assert len(repository.list_claims_internal()) == 3


def test_validation_seed_enforces_staff_and_idempotency_boundaries() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        missing_key = client.post(SEED_PATH, headers=STAFF_AUTH)
        claimant = client.post(
            SEED_PATH,
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'claimant-seed'},
        )

    assert missing_key.status_code == 400
    assert missing_key.json()['error']['code'] == 'VALIDATION_ERROR'
    assert claimant.status_code == 403
    assert repository.list_claims_internal() == []


def test_validation_seed_rejects_inactive_staff_before_any_write() -> None:
    repository = FixtureRepository()
    app = create_app(SETTINGS, repository)
    app.state.staff_identity_repository._accounts['stf_demo'].active = False

    with TestClient(app) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'inactive'})

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'
    assert repository.list_claims_internal() == []


def test_validation_seed_replay_rechecks_staff_authorization() -> None:
    repository = FixtureRepository()
    app = create_app(SETTINGS, repository)
    with TestClient(app) as client:
        headers = {**STAFF_AUTH, 'Idempotency-Key': 'auth-replay'}
        first = client.post(SEED_PATH, headers=headers)
        app.state.staff_identity_repository._accounts['stf_demo'].active = False
        replay = client.post(SEED_PATH, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 403
    assert replay.json()['error']['code'] == 'ACCESS_DENIED'


class _FailingMessageRepository(FixtureRepository):
    def save_message(self, message, customer_id):  # type: ignore[no-untyped-def]
        raise RuntimeError('injected persistence failure')


def test_validation_seed_rolls_back_when_a_child_write_fails() -> None:
    repository = _FailingMessageRepository()
    with TestClient(create_app(SETTINGS, repository), raise_server_exceptions=False) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'failure'})

    assert response.status_code == 500
    assert repository.list_claims_internal() == []
    presence = repository.get_staff_presence('stf_demo')
    assert presence is not None
    assert presence.revision == 1
    assert (
        repository.find_idempotency(
            'stf_demo',
            'POST /api/v1/workbench/demo/seed-validation',
            'failure',
        )
        is None
    )


def test_validation_seed_provisions_claimant_for_normal_sqlite_identity() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        identity_path = Path(directory) / 'claimant.sqlite'
        identity = SQLiteIdentityRepository(str(identity_path))
        settings = Settings(
            environment='test',
            identity_mode=IdentityMode.NORMAL,
            identity_db_path=str(identity_path),
        )
        repository = FixtureRepository()

        with TestClient(
            create_app(
                settings,
                repository,
                identity_repository=identity,
                staff_identity_repository=FixtureStaffIdentityRepository(),
            ),
        ) as client:
            staff_response = client.post(
                '/api/v1/staff/auth/sessions',
                json={'email': 'staff.one@example.invalid', 'password': 'northwind-demo-staff'},
            )
            assert staff_response.status_code == 201
            seed_response = client.post(
                SEED_PATH,
                headers={
                    'Authorization': f'Bearer {staff_response.json()["access_token"]}',
                    'Idempotency-Key': 'sqlite-seed',
                },
            )
            assert seed_response.status_code == 200
            claimant_response = client.post(
                '/api/v1/auth/sessions',
                json={
                    'email': 'claimant.one@example.invalid',
                    'password': 'northwind-demo-one',
                },
            )
            assert claimant_response.status_code == 201
            claimant_headers = {
                'Authorization': f'Bearer {claimant_response.json()["access_token"]}'
            }
            claims = client.get('/api/v1/claims', headers=claimant_headers)

        assert claims.status_code == 200
        assert len(claims.json()['items']) == 3
        del client
        del identity
        del repository
        gc.collect()


def test_validation_seed_uses_the_same_graph_boundary_for_mongodb() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]

    with TestClient(create_app(SETTINGS, repository)) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'mongo-seed'})

    assert response.status_code == 200
    assert len(repository.list_claims_internal()) == 3
    assert all(
        len(repository.list_evidence(claim.claim_id, claim.customer_id)) == 1
        for claim in repository.list_claims_internal()
    )


def test_fixture_validation_seed_repository_guards_replay_conflict_and_graph_shape() -> None:
    repository = FixtureRepository()
    graph = _validation_graph(repository)

    assert repository.seed_validation_graph(graph) is None
    replay = repository.seed_validation_graph(graph)
    assert replay is not None
    assert replay.response_payload == graph.idempotency.response_payload
    with pytest.raises(IdempotencyConflict):
        repository.seed_validation_graph(
            replace(
                graph,
                idempotency=replace(graph.idempotency, request_fingerprint='different'),
            ),
        )
    with pytest.raises(DemoSeedConflict):
        repository.seed_validation_graph(_validation_graph(repository, key='populated'))

    for invalid_graph in (
        replace(graph, claims=()),
        replace(graph, sessions=(graph.sessions[0], graph.sessions[0])),
        replace(graph, messages=(graph.messages[0], graph.messages[0])),
        replace(graph, evidence=(graph.evidence[0], graph.evidence[0])),
    ):
        invalid_repository = FixtureRepository()
        with pytest.raises(ValueError):
            invalid_repository.seed_validation_graph(invalid_graph)

    missing_active = graph.claims[0].model_copy(update={'active_session_id': 'ses_missing'})
    with pytest.raises(ValueError):
        FixtureRepository().seed_validation_graph(replace(graph, claims=(missing_active,)))

    extra_session = graph.sessions[0].model_copy(update={'session_id': 'ses_extra'})
    extra_graph = replace(
        graph,
        idempotency=replace(graph.idempotency, key='extra-session'),
        sessions=(*graph.sessions, extra_session),
    )
    repository = FixtureRepository()
    repository.seed_validation_graph(extra_graph)
    assert (
        repository.get_session(
            graph.claims[0].claim_id,
            'ses_extra',
            graph.claims[0].customer_id,
        )
        is not None
    )


def test_fixture_validation_seed_same_key_race_returns_one_persisted_result() -> None:
    repository = FixtureRepository()
    first_graph = _validation_graph(repository, key='same-key-race')
    second_graph = _validation_graph(repository, key='same-key-race')

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(repository.seed_validation_graph, (first_graph, second_graph)))

    persisted = repository.find_idempotency('stf_demo', VALIDATION_SEED_ROUTE, 'same-key-race')
    assert persisted is not None
    assert sum(result is None for result in results) == 1
    replay = next(result for result in results if result is not None)
    assert replay.response_payload == persisted.response_payload
    assert all(
        repository.get_claim(claim_id, 'cus_demo') is not None
        for claim_id in (persisted.response_payload or {}).get('claim_ids', [])
    )


@pytest.mark.parametrize(
    'field_update',
    [
        {'claim_id': 'clm_other'},
        {'customer_id': 'cus_other'},
        {'status': 'closed'},
        {'context_revision': 2},
    ],
)
def test_fixture_validation_seed_rejects_incoherent_active_session(
    field_update: dict[str, object],
) -> None:
    graph = _validation_graph(FixtureRepository(), key='incoherent')
    session = graph.sessions[0].model_copy(update=field_update)
    with pytest.raises(ValueError):
        FixtureRepository().seed_validation_graph(replace(graph, sessions=(session,)))


def test_mongodb_validation_seed_repository_guards_replay_conflict_and_graph_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_boundaries')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    graph = _validation_graph(repository)

    assert repository.seed_validation_graph(graph) is None
    replay = repository.seed_validation_graph(graph)
    assert replay is not None
    assert replay.response_payload == graph.idempotency.response_payload
    with pytest.raises(IdempotencyConflict):
        repository.seed_validation_graph(
            replace(
                graph,
                idempotency=replace(graph.idempotency, request_fingerprint='different'),
            ),
        )
    with pytest.raises(DemoSeedConflict):
        repository.seed_validation_graph(_validation_graph(repository, key='populated'))

    invalid_repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_invalid')
    invalid_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    with pytest.raises(ValueError):
        invalid_repository.seed_validation_graph(replace(graph, claims=()))

    revision_repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_revision')
    revision_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    mismatched_presence = replace(
        _validation_graph(revision_repository, key='presence-mismatch'),
        expected_presence_revision=99,
    )
    with pytest.raises(RevisionConflict):
        revision_repository.seed_validation_graph(mismatched_presence)

    invalid_initial_revision = replace(
        _validation_graph(revision_repository, key='initial-revision'),
        staff_presence=_validation_graph(revision_repository).staff_presence.model_copy(
            update={'revision': 2},
        ),
        expected_presence_revision=None,
    )
    with pytest.raises(RevisionConflict):
        revision_repository.seed_validation_graph(invalid_initial_revision)

    wrong_revision_repository = MongoDBRepository(
        mongomock.MongoClient(),
        'validation_seed_wrong_revision',
    )
    wrong_revision_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    stored_graph = _validation_graph(wrong_revision_repository, key='stored-presence')
    wrong_revision_repository.save_staff_presence(
        stored_graph.staff_presence,
        stored_graph.expected_presence_revision,
    )
    wrong_revision_graph = replace(
        _validation_graph(wrong_revision_repository, key='wrong-presence-revision'),
        staff_presence=stored_graph.staff_presence.model_copy(
            update={'revision': stored_graph.staff_presence.revision + 2},
        ),
        expected_presence_revision=stored_graph.staff_presence.revision,
    )
    with pytest.raises(RevisionConflict):
        wrong_revision_repository.seed_validation_graph(wrong_revision_graph)

    missing_active_repository = MongoDBRepository(
        mongomock.MongoClient(),
        'validation_seed_missing_active',
    )
    missing_active_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    missing_active_graph = _validation_graph(missing_active_repository, key='missing-active')
    missing_active_claim = missing_active_graph.claims[0].model_copy(
        update={'active_session_id': 'ses_missing'},
    )
    with pytest.raises(ValueError):
        missing_active_repository.seed_validation_graph(
            replace(missing_active_graph, claims=(missing_active_claim,)),
        )

    duplicate_repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_race')
    duplicate_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    duplicate_graph = _validation_graph(duplicate_repository)

    def raise_duplicate(*args: Any, **kwargs: Any) -> None:
        raise DuplicateKeyError('presence race')

    monkeypatch.setattr(duplicate_repository._collection, 'insert_one', raise_duplicate)
    with pytest.raises(RevisionConflict):
        duplicate_repository.seed_validation_graph(duplicate_graph)

    replace_repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_replace')
    replace_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    replace_graph = _validation_graph(replace_repository)
    replace_repository.save_staff_presence(
        replace_graph.staff_presence,
        replace_graph.expected_presence_revision,
    )
    next_graph = replace(
        _validation_graph(replace_repository, key='replace-race'),
        staff_presence=replace_graph.staff_presence.model_copy(
            update={'revision': replace_graph.staff_presence.revision + 1},
        ),
        expected_presence_revision=replace_graph.staff_presence.revision,
    )
    monkeypatch.setattr(
        replace_repository._collection,
        'replace_one',
        lambda *args, **kwargs: SimpleNamespace(matched_count=0),
    )
    with pytest.raises(RevisionConflict):
        replace_repository.seed_validation_graph(next_graph)

    extra_session = graph.sessions[0].model_copy(update={'session_id': 'ses_extra'})
    extra_graph = replace(
        graph,
        idempotency=replace(graph.idempotency, key='extra-session'),
        sessions=(*graph.sessions, extra_session),
    )
    extra_repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_extra')
    extra_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    extra_repository.seed_validation_graph(extra_graph)
    assert (
        extra_repository.get_session(
            graph.claims[0].claim_id,
            'ses_extra',
            graph.claims[0].customer_id,
        )
        is not None
    )


@pytest.mark.parametrize(
    'field_update',
    [
        {'claim_id': 'clm_other'},
        {'customer_id': 'cus_other'},
        {'status': 'closed'},
        {'context_revision': 2},
    ],
)
def test_mongodb_validation_seed_rejects_incoherent_active_session(
    field_update: dict[str, object],
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_incoherent')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    graph = _validation_graph(repository, key=f'incoherent-{field_update}')
    session = graph.sessions[0].model_copy(update=field_update)
    with pytest.raises(ValueError):
        repository.seed_validation_graph(replace(graph, sessions=(session,)))


class _RacingIdentityRepository(FixtureIdentityRepository):
    def create_account(
        self,
        email: str,
        password: str,
        display_name: str,
        phone: str = '',
    ) -> CustomerAccountRecord | None:
        super().create_account(email, password, display_name, phone)
        return None


def test_validation_seed_handles_claimant_provision_race_and_unavailable_account() -> None:
    racing_identity = _RacingIdentityRepository()
    racing_identity._accounts.pop('cus_demo')
    account = _ensure_demo_claimant(racing_identity)
    assert account.email == 'claimant.one@example.invalid'

    unavailable_identity = FixtureIdentityRepository()
    unavailable_identity._accounts['cus_demo'].active = False
    with pytest.raises(ApiError) as error:
        _ensure_demo_claimant(unavailable_identity)
    assert error.value.code == 'DEMO_CLAIMANT_UNAVAILABLE'


def test_validation_seed_maps_existing_idempotency_conflict() -> None:
    repository = FixtureRepository()
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id='stf_demo',
            route=VALIDATION_SEED_ROUTE,
            key='existing',
            request_fingerprint='old',
            claim_id='clm_existing',
            session_id='ses_existing',
        ),
    )
    with pytest.raises(ApiError) as error:
        seed_validation_scenarios(
            repository,
            FixtureIdentityRepository(),
            FixtureStaffIdentityRepository(),
            'stf_demo',
            'existing',
        )
    assert error.value.code == 'IDEMPOTENCY_CONFLICT'


class _FailingValidationSeedRepository(FixtureRepository):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    def seed_validation_graph(self, graph: ValidationSeedGraph) -> None:
        raise self.failure


class _RaceReplayValidationSeedRepository(FixtureRepository):
    def seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        self.save_idempotency(graph.idempotency)
        raise IdempotencyConflict(graph.idempotency.key)


def test_validation_seed_reconciles_idempotency_conflict_to_committed_response() -> None:
    repository = _RaceReplayValidationSeedRepository()

    with TestClient(create_app(SETTINGS, repository)) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'race-replay'})

    assert response.status_code == 200
    persisted = repository.find_idempotency('stf_demo', VALIDATION_SEED_ROUTE, 'race-replay')
    assert persisted is not None
    assert response.json() == persisted.response_payload


@pytest.mark.parametrize(
    ('failure', 'code'),
    [
        (DemoSeedConflict('queue'), 'DEMO_SEED_REQUIRES_EMPTY_QUEUE'),
        (IdempotencyConflict('key'), 'IDEMPOTENCY_CONFLICT'),
        (RevisionConflict(4), 'REVISION_CONFLICT'),
    ],
)
def test_validation_seed_maps_repository_conflicts(failure: Exception, code: str) -> None:
    with pytest.raises(ApiError) as error:
        seed_validation_scenarios(
            _FailingValidationSeedRepository(failure),
            FixtureIdentityRepository(),
            FixtureStaffIdentityRepository(),
            'stf_demo',
            f'failure-{code}',
        )
    assert error.value.code == code


def test_validation_source_scenarios_remain_unchanged() -> None:
    scenario_ids = (
        'AT-14-field-states-motor',
        'AT-15-field-states-home',
        'AT-16-field-states-contents',
    )
    for scenario_id in scenario_ids:
        scenario = load_scenario(Path('backend/demo_data/scenarios') / f'{scenario_id}.json')
        assert scenario.claim.customer_id == 'cus_demo'
        assert scenario.claim.assignee_id is None
        assert scenario.evidence == []
