from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.adapters.evidence_storage import (
    EvidenceContentConflict,
    EvidenceStorage,
    EvidenceStorageUnavailable,
    EvidenceUploadTooLarge,
)
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
    ClaimSeedGraph,
    seed_scenario,
)
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.branching import build_applied_branch_evaluation
from backend.services.business_seed import BusinessSeed, SeedDemoCase
from backend.services.demo_materials import associate_materials, material_content
from backend.services.support import now_utc, request_fingerprint, require_idempotency_key

VALIDATION_SEED_ROUTE = 'POST /api/v1/workbench/demo/seed-validation'


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


def _ensure_demo_claimant(
    identity_repository: IdentityRepository, seed: BusinessSeed
) -> CustomerAccountRecord:
    customer = next(
        (item for item in seed.customers if item.customer_id == seed.primary_customer_id), None
    )
    account = None
    if customer is not None:
        try:
            account = identity_repository.ensure_seed_account(
                customer.customer_id,
                customer.email,
                customer.synthetic_password,
                customer.display_name,
            )
        except ValueError as error:
            raise ApiError(
                status_code=409,
                code='DEMO_CLAIMANT_UNAVAILABLE',
                message='The synthetic claimant identity conflicts with an existing account.',
            ) from error
    if account is None or not account.active:
        raise ApiError(
            status_code=409,
            code='DEMO_CLAIMANT_UNAVAILABLE',
            message='The synthetic claimant account is unavailable for validation data.',
        )
    return account


def _case_scenario(case: SeedDemoCase) -> ClaimSeedGraph:
    """Build a persisted graph from the selected seed's business inputs.

    Args:
        case: Validated manifest case, without expected actions or test assertions.
    Returns:
        Fresh claim, session, and messages using the shared domain contracts.
    """
    claim_id, session_id = new_id('clm'), new_id('ses')
    timestamp = case.recorded_at
    actor = {'actor_type': 'claimant', 'actor_id': case.customer_id}
    messages: list[dict[str, Any]] = []
    for text in case.messages:
        messages.append(
            {
                'message_id': new_id('msg'),
                'claim_id': claim_id,
                'session_id': session_id,
                'actor': 'claimant',
                'visibility': 'shared',
                'content': {'type': 'text', 'text': text},
                'in_reply_to': messages[-1]['message_id'] if messages else None,
                'created_at': timestamp + timedelta(seconds=len(messages)),
            }
        )
    source_refs = [message['message_id'] for message in messages]
    form = {
        code: {
            'value': field.value,
            'status': field.status,
            'source': 'claimant',
            'source_refs': source_refs if field.value is not None else [],
            'needed_for': 'current_action',
            'updated_at': timestamp,
            'updated_by': actor,
        }
        for code, field in case.fields.items()
    }
    form['claim.product_family'] = {
        'value': case.family,
        'status': 'confirmed',
        'source': 'claimant',
        'source_refs': source_refs,
        'needed_for': 'current_action',
        'updated_at': timestamp,
        'updated_by': actor,
    }
    return ClaimSeedGraph.model_validate(
        {
            'scenario_id': case.case_id,
            'description': 'Business seed claim for staff and claimant exploration.',
            'claim': {
                'claim_id': claim_id,
                'customer_id': case.customer_id,
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': case.family,
                'active_session_id': session_id,
                'form': form,
                'contents_items': [
                    {
                        'item_id': new_id('itm'),
                        'description': description,
                        'source': 'claimant',
                        'source_refs': source_refs,
                        'status': 'proposed',
                        'needed_for': 'current_action',
                        'updated_at': timestamp,
                        'updated_by': actor,
                    }
                    for description in case.contents_descriptions
                ],
                'created_at': timestamp,
                'updated_at': timestamp,
                'customer_next_step': {
                    'status': 'collecting',
                    'summary': 'Confirm the incident details to continue.',
                    'responsible_party': 'claimant',
                    'can_resume': True,
                },
            },
            'sessions': [
                {
                    'session_id': session_id,
                    'claim_id': claim_id,
                    'customer_id': case.customer_id,
                    'started_at': timestamp,
                    'last_active_at': timestamp,
                }
            ],
            'messages': messages,
        }
    )


def _validation_scenario(
    scenario: ClaimSeedGraph,
    *,
    customer_id: str,
    staff_id: str,
) -> ClaimSeedGraph:
    replacements = {
        scenario.claim.customer_id: customer_id,
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
        needed_for=['current_action'],
        claimant_note='An attachment was mentioned, but its file has not been provided.',
        created_at=timestamp,
        updated_at=timestamp,
    )
    payload['claim']['assignee_id'] = staff_id
    payload['claim']['claim_state']['evidence'] = evidence_state_for([evidence]).value
    payload['claim']['evidence_summary'] = evidence_summary_for([evidence]).model_dump(mode='json')
    payload['evidence'] = [evidence.model_dump(mode='json')]
    payload['messages'][-1]['evidence_refs'] = [evidence_id]
    return ClaimSeedGraph.model_validate(payload)


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


def _store_material_content(
    scenarios: tuple[ClaimSeedGraph, ...],
    storage: EvidenceStorage,
) -> tuple[ClaimSeedGraph, ...]:
    """Place each produced material's bytes in evidence storage and record where they are.

    Association attaches the produced materials as Evidence, but their bytes stayed in the
    repository. The Workbench content route reads only what evidence storage holds, so every
    material with a file answered `404`. The bytes go through `store_generated_content`, the
    server-side path a received assessor report already uses, so the key is real under the
    fixture adapter and the S3-compatible adapter alike. This runs before the graph is built,
    so a storage key is only ever written onto a record that commits with the graph.

    Args:
        scenarios: Validation scenarios after material association.
        storage: The configured evidence storage adapter.

    Returns:
        The scenarios, with each produced material's `storage_key` and `upload_checksum`.

    Raises:
        ApiError: Evidence storage is unavailable (`503`, retryable, nothing seeded), or a
            produced material cannot be stored as it is.
    """

    stored_scenarios: list[ClaimSeedGraph] = []
    for scenario in scenarios:
        evidence: list[EvidenceRecord] = []
        for record in scenario.evidence:
            content = material_content(record)
            if content is None or record.media_type is None:
                evidence.append(record)
                continue
            try:
                stored = storage.store_generated_content(
                    claim_id=record.claim_id,
                    evidence_id=record.evidence_id,
                    content=content,
                    media_type=record.media_type,
                )
            except EvidenceStorageUnavailable as error:
                raise ApiError(
                    status_code=503,
                    code='DEPENDENCY_UNAVAILABLE',
                    message=(
                        'Evidence storage is temporarily unavailable. '
                        'No validation data was seeded.'
                    ),
                    retryable=True,
                ) from error
            except (EvidenceContentConflict, EvidenceUploadTooLarge) as error:
                raise ApiError(
                    status_code=500,
                    code='INTERNAL_ERROR',
                    message='A demonstration material could not be stored.',
                ) from error
            provenance = {
                **record.provenance,
                'storage_key': stored.storage_key,
                'upload_checksum': stored.checksum,
            }
            evidence.append(record.model_copy(update={'provenance': provenance}))
        stored_scenarios.append(scenario.model_copy(update={'evidence': evidence}))
    return tuple(stored_scenarios)


def seed_validation_scenarios(
    repository: PersistenceRepository,
    identity_repository: IdentityRepository,
    staff_identity_repository: StaffIdentityRepository,
    staff_id: str,
    idempotency_key: str | None,
    *,
    seed: BusinessSeed,
    evidence_storage: EvidenceStorage | None = None,
) -> DemoSeedResponse:
    """Seed the three validation paths through the shared persistence contract.

    When an evidence storage adapter is supplied, the produced materials' bytes are stored
    with it, so each material can be opened through the Workbench content route.

    Args:
        repository: Selected Claim persistence adapter.
        identity_repository: Selected claimant identity adapter.
        staff_identity_repository: Selected staff identity adapter.
        staff_id: Authenticated staff principal.
        idempotency_key: Request replay key.
        seed: The manifest selected by Settings.business_seed_path.
        evidence_storage: Selected storage for generated demonstration material.
    Returns:
        Identifiers of the committed graphs, or the original idempotent result.
    Raises:
        ApiError: Identity, empty-queue, persistence, or storage checks fail.
    """
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

    base_scenarios = load_workbench_demo_scenarios(seed)
    _ensure_demo_claimant(identity_repository, seed)
    scenarios = tuple(
        _validation_scenario(
            scenario,
            customer_id=scenario.claim.customer_id,
            staff_id=staff_id,
        )
        for scenario in base_scenarios
    )
    # The produced demonstration materials become Evidence on the claim of their family.
    # This runs after `_validation_scenario` rather than before it: that transform replaces
    # the scenario's evidence wholesale and assigns the claim its seeded identity, so
    # associating first would attach material to a claim id that no longer exists.
    scenarios = associate_materials(scenarios).scenarios
    if evidence_storage is not None:
        scenarios = _store_material_content(scenarios, evidence_storage)
    presence, expected_presence_revision = _validation_presence(repository, staff_id)
    response = DemoSeedResponse(
        status='seeded',
        scenario_ids=[case.case_id for case in seed.demo_cases],
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
        branch_evaluations=tuple(
            build_applied_branch_evaluation(scenario.claim, recomputation_reason='claim_seeded')
            for scenario in scenarios
        ),
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
        replayed = repository.find_idempotency(staff_id, VALIDATION_SEED_ROUTE, key)
        if (
            replayed is not None
            and replayed.request_fingerprint == fingerprint
            and replayed.response_payload is not None
        ):
            return DemoSeedResponse.model_validate(replayed.response_payload)
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
    seed: BusinessSeed,
) -> tuple[ClaimSeedGraph, ...]:
    """Build the selected manifest's cases, without loading regression fixtures.

    Args:
        seed: The application's configured and validated manifest.
    Returns:
        Claim graphs from this source alone.
    Raises:
        ApiError: The selected manifest contains no cases.
    """
    if not seed.demo_cases:
        raise ApiError(
            status_code=409,
            code='DEMO_CLAIMANT_UNAVAILABLE',
            message='The selected business seed has no demo cases.',
        )
    return tuple(_case_scenario(case) for case in seed.demo_cases)


def seed_workbench_demo_scenarios(
    repository: PersistenceRepository, seed: BusinessSeed
) -> DemoScenarioSeedResult:
    """Populate an empty staff queue from the selected business manifest.

    Args:
        repository: Selected Claim persistence adapter.
        seed: Validated application manifest.
    Returns:
        Configured case IDs and newly generated Claim IDs.
    Raises:
        ApiError: The queue already contains a Claim.
    """
    if repository.list_claims_internal():
        raise ApiError(
            status_code=409,
            code='DEMO_SEED_REQUIRES_EMPTY_QUEUE',
            message='Reset the local demo before loading the workbench scenario queue.',
        )

    scenarios = load_workbench_demo_scenarios(seed)
    claim_ids: list[str] = []
    for scenario in scenarios:
        seed_scenario(repository, scenario)
        claim_ids.append(scenario.claim.claim_id)
    return DemoScenarioSeedResult(
        scenario_ids=tuple(scenario.scenario_id for scenario in scenarios),
        claim_ids=tuple(claim_ids),
    )
