import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app import create_app  # noqa: E402
from backend.core.config import DataRuntimeProfile  # noqa: E402

AppFactory = Callable[[], FastAPI]
IDEMPOTENCY_KEY = 'local-mvp-verification-claim-v1'


@dataclass(frozen=True, slots=True)
class LocalMVPJourneyResult:
    claim_id: str
    claimant_read: bool
    staff_read: bool
    restart_verified: bool
    persistence_status: str
    evidence_storage_status: str


def verify_local_mvp_journey(
    app_factory: AppFactory = create_app,
) -> LocalMVPJourneyResult:
    """Verify one idempotent claimant-to-workbench journey across app restart."""

    claimant_headers = {
        'Authorization': 'Bearer synthetic-claimant',
        'Idempotency-Key': IDEMPOTENCY_KEY,
    }
    with TestClient(app_factory()) as first_client:
        created = first_client.post(
            '/api/v1/claims',
            headers=claimant_headers,
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': 'motor',
            },
        )
        if created.status_code not in {200, 201}:
            raise RuntimeError('The claimant could not create or resume the verification claim.')
        claim_id = str(created.json()['claim']['claim_id'])

    second_app = app_factory()
    with TestClient(second_app) as second_client:
        claimant = second_client.get(
            f'/api/v1/claims/{claim_id}',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )
        if claimant.status_code != 200:
            raise RuntimeError('The claimant could not read the claim after app restart.')

        staff = second_client.get(
            '/api/v1/workbench/claims',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        if staff.status_code != 200:
            raise RuntimeError('The staff workbench could not read persisted claims.')
        staff_claim_ids = {str(item['claim_id']) for item in staff.json()['items']}
        if claim_id not in staff_claim_ids:
            raise RuntimeError('The staff workbench did not receive the claimant claim.')

        readiness = second_client.get('/health/ready')
        if readiness.status_code != 200:
            raise RuntimeError('Runtime readiness could not be read.')
        checks = readiness.json()['checks']
        profile = second_app.state.data_runtime_bundle.profile
        if profile is DataRuntimeProfile.LOCAL_MVP and (
            checks['persistence'] != 'verified'
            or checks['evidence_storage'] != 'configured_service'
        ):
            raise RuntimeError('The local MVP providers are not ready.')

    return LocalMVPJourneyResult(
        claim_id=claim_id,
        claimant_read=True,
        staff_read=True,
        restart_verified=True,
        persistence_status=str(checks['persistence']),
        evidence_storage_status=str(checks['evidence_storage']),
    )


if __name__ == '__main__':
    result = verify_local_mvp_journey()
    print(
        f'PASS local_mvp journey: claim={result.claim_id} '
        f'claimant_read={result.claimant_read} staff_read={result.staff_read} '
        f'restart={result.restart_verified} persistence={result.persistence_status} '
        f'evidence={result.evidence_storage_status}'
    )
