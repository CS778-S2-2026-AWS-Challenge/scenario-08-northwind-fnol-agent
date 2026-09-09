from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.core.errors import ApiError
from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.identity import CustomerAccountRecord
from backend.domain.ids import new_id
from backend.domain.models import (
    DemoSeedResponse,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
)
from backend.domain.staff_identity import StaffPresenceRecord
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import (
    DemoSeedConflict,
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
    ValidationSeedGraph,
)
from backend.repositories.scenario_loader import (
    ScenarioFixture,
    load_mvp_journey_scenarios,
    load_scenario,
    seed_scenario,
)
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.support import now_utc, request_fingerprint, require_idempotency_key

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'demo_data' / 'scenarios'

ADDITIONAL_WORKBENCH_DEMO_SCENARIO_IDS = ('AT-10-controlled-assessor',)
VALIDATION_SCENARIO_IDS = (
    'AT-14-field-states-motor',
    'AT-15-field-states-home',
    'AT-16-field-states-contents',
)
VALIDATION_SEED_ROUTE = 'POST /api/v1/workbench/demo/seed-validation'
DEMO_CLAIMANT_EMAIL = 'claimant.one@example.invalid'
DEMO_CLAIMANT_PASSWORD = 'northwind-demo-one'
DEMO_CLAIMANT_DISPLAY_NAME = 'Demo Claimant One'


@dataclass(frozen=True, slots=True)
class DemoScenarioSeedResult:
    scenario_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def _replace_values(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_values(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _ensure_demo_claimant(identity_repository: IdentityRepository) -> CustomerAccountRecord:
    account = next(
        (item for item in identity_repository.list_accounts() if item.email == DEMO_CLAIMANT_EMAIL),
        None,
    )
    if account is None:
        account = identity_repository.create_account(
            DEMO_CLAIMANT_EMAIL,
            DEMO_CLAIMANT_PASSWORD,
            DEMO_CLAIMANT_DISPLAY_NAME,
        )
        if account is None:
            account = next(
                (
                    item
                    for item in identity_repository.list_accounts()
                    if item.email == DEMO_CLAIMANT_EMAIL
                ),
                None,
            )
    if account is None or not account.active:
        raise ApiError(
            status_code=409,
            code='DEMO_CLAIMANT_UNAVAILABLE',
            message='The synthetic claimant account is unavailable for validation data.',
        )
    return account


def _validation_scenario(
    scenario: ScenarioFixture,
    *,
    customer_id: str,
    staff_id: str,
) -> ScenarioFixture:
    replacements = {
        'cus_demo': customer_id,
        scenario.claim.claim_id: new_id('clm'),
        scenario.claim.active_session_id or '': new_id('ses'),
    }
    for message in scenario.messages:
        replacements[message.message_id] = new_id('msg')

    payload = _replace_values(scenario.model_dump(mode='json'), replacements)
    claim_id = payload['claim']['claim_id']
    timestamp = datetime.fromisoformat(payload['claim']['updated_at'].replace('Z', '+00:00'))
    evidence_id = new_id('evd')
    evidence = EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='claimant_attachment',
        status=EvidenceStatus.UNOFFICIAL,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.CLAIMANT,
        related_fields=['incident.description'],
        needed_for=['validation_demo'],
        claimant_note='Synthetic evidence reference for the validation demonstration.',
        created_at=timestamp,
        updated_at=timestamp,
    )
    payload['claim']['assignee_id'] = staff_id
    payload['claim']['claim_state']['evidence'] = evidence_state_for([evidence]).value
    payload['claim']['evidence_summary'] = evidence_summary_for([evidence]).model_dump(mode='json')
    payload['evidence'] = [evidence.model_dump(mode='json')]
    payload['messages'][-1]['evidence_refs'] = [evidence_id]
    return ScenarioFixture.model_validate(payload)


def _validation_presence(
    repository: PersistenceRepository,
    staff_id: str,
) -> tuple[StaffPresenceRecord, int | None]:
    current = repository.get_staff_presence(staff_id)
    now = now_utc()
    return (
        StaffPresenceRecord(
            staff_id=staff_id,
            online=True,
            available=True,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=5),
            revision=(current.revision + 1) if current is not None else 1,
            updated_at=now,
        ),
        current.revision if current is not None else None,
    )


def seed_validation_scenarios(
    repository: PersistenceRepository,
    identity_repository: IdentityRepository,
    staff_identity_repository: StaffIdentityRepository,
    staff_id: str,
    idempotency_key: str | None,
) -> DemoSeedResponse:
    """Seed the three validation paths through the shared persistence contract."""
    key = require_idempotency_key(idempotency_key)
    fingerprint = request_fingerprint({'route': VALIDATION_SEED_ROUTE, 'version': 1})
    staff_account = staff_identity_repository.get_account(staff_id)
    if staff_account is None or not staff_account.active:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='The staff account is not active for validation seeding.',
        )
    existing = repository.find_idempotency(staff_id, VALIDATION_SEED_ROUTE, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.response_payload is None:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The Idempotency-Key was already used for a different request.',
            )
        return DemoSeedResponse.model_validate(existing.response_payload)

    if repository.list_claims_internal():
        raise ApiError(
            status_code=409,
            code='DEMO_SEED_REQUIRES_EMPTY_QUEUE',
            message='Reset the local demo before loading validation scenarios.',
        )

    claimant = _ensure_demo_claimant(identity_repository)
    scenarios = tuple(
        _validation_scenario(
            load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json'),
            customer_id=claimant.customer_id,
            staff_id=staff_id,
        )
        for scenario_id in VALIDATION_SCENARIO_IDS
    )
    presence, expected_presence_revision = _validation_presence(repository, staff_id)
    response = DemoSeedResponse(
        status='seeded',
        scenario_ids=list(VALIDATION_SCENARIO_IDS),
        claim_ids=[scenario.claim.claim_id for scenario in scenarios],
    )
    idempotency = IdempotencyRecord(
        actor_id=staff_id,
        route=VALIDATION_SEED_ROUTE,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=scenarios[0].claim.claim_id,
        session_id=scenarios[0].claim.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    graph = ValidationSeedGraph(
        claims=tuple(scenario.claim for scenario in scenarios),
        sessions=tuple(session for scenario in scenarios for session in scenario.sessions),
        messages=tuple(message for scenario in scenarios for message in scenario.messages),
        evidence=tuple(item for scenario in scenarios for item in scenario.evidence),
        staff_presence=presence,
        expected_presence_revision=expected_presence_revision,
        idempotency=idempotency,
    )
    try:
        replayed = repository.seed_validation_graph(graph)
    except DemoSeedConflict as error:
        raise ApiError(
            status_code=409,
            code='DEMO_SEED_REQUIRES_EMPTY_QUEUE',
            message='Reset the local demo before loading validation scenarios.',
        ) from error
    except IdempotencyConflict as error:
        replayed = repository.find_idempotency(staff_id, VALIDATION_SEED_ROUTE, key)
        if (
            replayed is not None
            and replayed.request_fingerprint == fingerprint
            and replayed.response_payload is not None
        ):
            return DemoSeedResponse.model_validate(replayed.response_payload)
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The Idempotency-Key was already used for a different request.',
        ) from error
    except RevisionConflict as error:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The staff presence changed before validation data could be seeded.',
            retryable=True,
            current_revision=error.current_revision,
        ) from error
    if replayed is not None:
        if replayed.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The validation seed replay could not be restored.',
            )
        return DemoSeedResponse.model_validate(replayed.response_payload)
    return response


def load_workbench_demo_scenarios(
    directory: Path = SCENARIO_DIRECTORY,
) -> tuple[ScenarioFixture, ...]:
    """Load the five canonical MVP paths plus bounded integration demonstrations."""

    journey_scenarios = load_mvp_journey_scenarios(directory)
    additional_scenarios = [
        load_scenario(directory / f'{scenario_id}.json')
        for scenario_id in ADDITIONAL_WORKBENCH_DEMO_SCENARIO_IDS
    ]
    return (*journey_scenarios, *additional_scenarios)


def seed_workbench_demo_scenarios(repository: PersistenceRepository) -> DemoScenarioSeedResult:
    if repository.list_claims_internal():
        raise ApiError(
            status_code=409,
            code='DEMO_SEED_REQUIRES_EMPTY_QUEUE',
            message='Reset the local demo before loading the workbench scenario queue.',
        )

    scenarios = load_workbench_demo_scenarios()
    claim_ids: list[str] = []
    for scenario in scenarios:
        seed_scenario(repository, scenario)
        claim_ids.append(scenario.claim.claim_id)
    return DemoScenarioSeedResult(
        scenario_ids=tuple(scenario.scenario_id for scenario in scenarios),
        claim_ids=tuple(claim_ids),
    )
