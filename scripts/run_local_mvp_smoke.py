import argparse
import json
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import create_app
from scripts.check_runtime_profile import isolated_environment, load_environment_example

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENVIRONMENT = ROOT / 'deploy' / 'runtime' / 'local-mvp.env.example'
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}


def _expect(response: httpx.Response, status_code: int, step: str) -> dict[str, Any]:
    if response.status_code != status_code:
        raise RuntimeError(f'{step} failed with HTTP {response.status_code}: {response.text}')
    if not response.content:
        return {}
    return cast(dict[str, Any], response.json())


def _first_process(run_id: str) -> tuple[str, str, str, int]:
    evidence_bytes = b'northwind-local-mvp-evidence'
    with TestClient(create_app()) as client:
        created = _expect(
            client.post(
                '/api/v1/claims',
                headers={**CLAIMANT_AUTH, 'Idempotency-Key': f'{run_id}-claim'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            ),
            201,
            'claim creation',
        )
        claim_id = str(cast(dict[str, Any], created['claim'])['claim_id'])
        session_id = str(cast(dict[str, Any], created['session'])['session_id'])
        message_url = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
        message_payload = {
            'client_message_id': f'{run_id}-message',
            'content': {
                'type': 'text',
                'text': 'A synthetic rear-end incident occurred in Auckland. Nobody was injured.',
            },
            'evidence_refs': [],
        }
        turn = _expect(
            client.post(
                message_url,
                headers={
                    **CLAIMANT_AUTH,
                    'Idempotency-Key': f'{run_id}-message',
                    'If-Match': '1',
                },
                json=message_payload,
            ),
            200,
            'controlled message turn',
        )
        if int(turn['claim_revision']) != 2:
            raise RuntimeError('The controlled message turn did not advance revision to 2.')

        upload = _expect(
            client.post(
                f'/api/v1/claims/{claim_id}/evidence/uploads',
                headers={
                    **CLAIMANT_AUTH,
                    'Idempotency-Key': f'{run_id}-evidence',
                    'If-Match': '2',
                },
                json={
                    'kind': 'incident_image',
                    'original_filename': 'synthetic-damage.jpg',
                    'media_type': 'image/jpeg',
                    'size_bytes': len(evidence_bytes),
                },
            ),
            201,
            'evidence upload request',
        )
        evidence_id = str(upload['evidence_id'])
        capability = cast(dict[str, Any], upload['upload'])
        put_response = httpx.put(
            str(capability['url']),
            headers=cast(dict[str, str], capability['headers']),
            content=evidence_bytes,
            timeout=10,
        )
        if put_response.status_code not in {200, 204}:
            raise RuntimeError(f'evidence byte upload failed with HTTP {put_response.status_code}')
        completed = _expect(
            client.post(
                f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
                headers={
                    **CLAIMANT_AUTH,
                    'Idempotency-Key': f'{run_id}-evidence-complete',
                    'If-Match': str(upload['revision']),
                },
                json={'upload_checksum': f'sha256:{sha256(evidence_bytes).hexdigest()}'},
            ),
            202,
            'evidence completion',
        )
        knowledge = _expect(
            client.post(
                '/internal/v1/knowledge/search',
                headers=INTEGRATION_AUTH,
                json={
                    'question': 'What excess applies to my motor claim?',
                    'jurisdiction': 'NZ',
                    'visibility': 'customer_and_staff',
                    'authority': 'northwind_synthetic_demo',
                    'version': 'MVP-2026.1',
                    'insurer': 'Northwind Insurance',
                    'product': 'motor',
                    'effective_at': datetime.now(UTC).isoformat(),
                    'limit': 3,
                },
            ),
            200,
            'knowledge search',
        )
        if knowledge['status'] != 'evidence_found':
            raise RuntimeError('The governed MinIO knowledge query returned no evidence.')
        return claim_id, session_id, evidence_id, int(completed['revision'])


def _second_process(
    run_id: str,
    claim_id: str,
    session_id: str,
    evidence_id: str,
    expected_revision: int,
) -> dict[str, object]:
    with TestClient(create_app()) as client:
        replayed_claim = _expect(
            client.post(
                '/api/v1/claims',
                headers={**CLAIMANT_AUTH, 'Idempotency-Key': f'{run_id}-claim'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            ),
            201,
            'claim idempotency recovery',
        )
        replayed_claim_id = str(cast(dict[str, Any], replayed_claim['claim'])['claim_id'])
        if replayed_claim_id != claim_id:
            raise RuntimeError('The persisted claim idempotency result was not replayed.')
        replayed_turn = _expect(
            client.post(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers={
                    **CLAIMANT_AUTH,
                    'Idempotency-Key': f'{run_id}-message',
                    'If-Match': '1',
                },
                json={
                    'client_message_id': f'{run_id}-message',
                    'content': {
                        'type': 'text',
                        'text': (
                            'A synthetic rear-end incident occurred in Auckland. '
                            'Nobody was injured.'
                        ),
                    },
                    'evidence_refs': [],
                },
            ),
            200,
            'message idempotency recovery',
        )
        if int(replayed_turn['claim_revision']) != 2:
            raise RuntimeError('The persisted message turn was not replayed at revision 2.')
        claim = _expect(
            client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH),
            200,
            'claim recovery',
        )
        messages = _expect(
            client.get(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers=CLAIMANT_AUTH,
            ),
            200,
            'message recovery',
        )
        evidence = _expect(
            client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH),
            200,
            'evidence recovery',
        )
        staff = _expect(
            client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH),
            200,
            'staff projection recovery',
        )
        downloaded = client.get(
            f'/api/v1/workbench/claims/{claim_id}/evidence/{evidence_id}/content',
            headers=STAFF_AUTH,
        )
        if downloaded.status_code != 200 or downloaded.content != b'northwind-local-mvp-evidence':
            raise RuntimeError('The protected MinIO evidence bytes were not recovered.')
        stale = client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={**CLAIMANT_AUTH, 'If-Match': '1'},
            json={
                'updates': [{'field_code': 'incident.description', 'value': 'A stale replacement.'}]
            },
        )
        if stale.status_code != 409 or stale.json()['error']['code'] != 'REVISION_CONFLICT':
            raise RuntimeError('A stale revision was not rejected after restart.')
        readiness = _expect(client.get('/health/ready'), 200, 'runtime readiness')

    if int(claim['revision']) != expected_revision:
        raise RuntimeError('The recovered Claim revision does not match the committed revision.')
    if len(cast(list[object], messages['items'])) != 2:
        raise RuntimeError('The claimant and controlled Agent messages were not both recovered.')
    if len(cast(list[object], evidence['items'])) != 1:
        raise RuntimeError('The evidence metadata was not recovered exactly once.')
    if str(staff['claim_id']) != claim_id:
        raise RuntimeError('The staff projection did not recover the same Claim.')
    checks = cast(dict[str, str], readiness['checks'])
    return {
        'claim_id': claim_id,
        'revision': expected_revision,
        'messages': 2,
        'evidence_records': 1,
        'persistence': checks['persistence'],
        'evidence_storage': checks['evidence_storage'],
        'knowledge_retrieval': checks['knowledge_retrieval'],
        'policy': checks['policy'],
        'claim_history': checks['claim_history'],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Verify the non-Agent local MVP path across MongoDB and MinIO.'
    )
    parser.add_argument('--env-file', type=Path, default=DEFAULT_ENVIRONMENT)
    arguments = parser.parse_args()
    values = load_environment_example(arguments.env_file)
    if values.get('DATA_RUNTIME_PROFILE') != 'local_mvp':
        raise SystemExit('The smoke requires DATA_RUNTIME_PROFILE=local_mvp.')
    run_id = f'local-mvp-{uuid4().hex[:12]}'
    with isolated_environment(values):
        claim_id, session_id, evidence_id, revision = _first_process(run_id)
        result = _second_process(run_id, claim_id, session_id, evidence_id, revision)
    print(json.dumps({'status': 'PASS', 'run_id': run_id, **result}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
