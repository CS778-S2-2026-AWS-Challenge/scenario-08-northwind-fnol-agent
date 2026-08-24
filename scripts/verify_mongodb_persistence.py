import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pymongo import MongoClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.domain.models import StaffActionRecord, StaffActionStatus  # noqa: E402
from backend.repositories.mongodb import (  # noqa: E402
    MongoDBConnectionConfig,
    MongoDBRepository,
    connect_mongodb_repository,
)
from backend.repositories.protocols import IdempotencyRecord  # noqa: E402
from backend.repositories.scenario_loader import load_scenario, seed_scenario  # noqa: E402

SCENARIO_PATH = REPOSITORY_ROOT / 'backend/demo_data/scenarios/AT-01-clear-motor.json'
RepositoryFactory = Callable[[MongoDBConnectionConfig], MongoDBRepository]
CollectionCleanup = Callable[[MongoDBConnectionConfig], None]


@dataclass(frozen=True, slots=True)
class MongoDBPersistenceResult:
    status: str
    claims: int
    sessions: int
    messages: int
    evidence: int
    staff_actions: int
    reconnect_verified: bool
    ownership_verified: bool


def _temporary_config(base: MongoDBConnectionConfig) -> MongoDBConnectionConfig:
    return MongoDBConnectionConfig(
        uri=base.uri,
        database_name=base.database_name,
        collection_name=f'northwind_verify_{uuid4().hex}',
        server_selection_timeout_ms=base.server_selection_timeout_ms,
    )


def _drop_verification_collection(config: MongoDBConnectionConfig) -> None:
    client: MongoClient[Any] = MongoClient(
        config.uri,
        serverSelectionTimeoutMS=config.server_selection_timeout_ms,
    )
    try:
        client[config.database_name].drop_collection(config.collection_name)
    finally:
        client.close()


def verify_mongodb_persistence(
    base_config: MongoDBConnectionConfig | None = None,
    *,
    repository_factory: RepositoryFactory = connect_mongodb_repository,
    cleanup: CollectionCleanup = _drop_verification_collection,
) -> MongoDBPersistenceResult:
    """Verify a durable claimant/staff slice in an isolated temporary collection."""

    config = _temporary_config(base_config or MongoDBConnectionConfig.from_environment())
    scenario = load_scenario(SCENARIO_PATH)
    repository: MongoDBRepository | None = None
    reconnected: MongoDBRepository | None = None
    collection_created = False
    try:
        repository = repository_factory(config)
        collection_created = True
        seed_scenario(repository, scenario)

        stored_claim = repository.get_claim(scenario.claim.claim_id, scenario.claim.customer_id)
        if stored_claim != scenario.claim:
            raise RuntimeError('MongoDB did not return the seeded claim.')
        if repository.get_claim(scenario.claim.claim_id, 'customer-not-owner') is not None:
            raise RuntimeError('MongoDB ownership filtering failed.')

        action = StaffActionRecord(
            action_id='act_mongodb_verification',
            claim_id=stored_claim.claim_id,
            action_type='review_claim',
            status=StaffActionStatus.OPEN,
            assigned_to='stf_mongodb_verification',
            requested_outcome='Verify the persisted FNOL information.',
            created_at=datetime.now(UTC),
        )
        updated_claim = stored_claim.model_copy(
            update={'revision': stored_claim.revision + 1, 'updated_at': datetime.now(UTC)}
        )
        repository.save_staff_mutation(
            updated_claim,
            stored_claim.revision,
            IdempotencyRecord(
                actor_id='stf_mongodb_verification',
                route='/internal/verification/staff-actions',
                key='mongodb-persistence-verification',
                request_fingerprint='mongodb-persistence-verification-v1',
                claim_id=stored_claim.claim_id,
                session_id=stored_claim.active_session_id or '',
            ),
            staff_action=action,
        )
        repository.close()
        repository = None

        reconnected = repository_factory(config)
        durable_claim = reconnected.get_claim(scenario.claim.claim_id, scenario.claim.customer_id)
        if durable_claim != updated_claim:
            raise RuntimeError('MongoDB claim state did not survive reconnect.')
        if reconnected.get_staff_action(updated_claim.claim_id, action.action_id) != action:
            raise RuntimeError('MongoDB staff write-back did not survive reconnect.')

        sessions = reconnected.list_sessions_for_claim(
            updated_claim.claim_id, updated_claim.customer_id
        )
        messages = reconnected.list_messages(
            updated_claim.claim_id,
            updated_claim.active_session_id or '',
            updated_claim.customer_id,
        )
        evidence = reconnected.list_evidence(updated_claim.claim_id, updated_claim.customer_id)
        staff_actions = reconnected.list_staff_actions(updated_claim.claim_id)
        return MongoDBPersistenceResult(
            status=reconnected.connection_status(),
            claims=len(reconnected.list_claims_internal()),
            sessions=len(sessions),
            messages=len(messages),
            evidence=len(evidence),
            staff_actions=len(staff_actions),
            reconnect_verified=True,
            ownership_verified=True,
        )
    finally:
        if repository is not None:
            repository.close()
        if reconnected is not None:
            reconnected.close()
        if collection_created:
            cleanup(config)


if __name__ == '__main__':
    result = verify_mongodb_persistence()
    print(
        f'PASS MongoDB persistence: status={result.status} claims={result.claims} '
        f'sessions={result.sessions} messages={result.messages} evidence={result.evidence} '
        f'staff_actions={result.staff_actions} reconnect={result.reconnect_verified} '
        f'ownership={result.ownership_verified}'
    )
