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

from backend.adapters.policy_history import MockPolicyHistoryAdapter, RetrievalUnavailable
from backend.app import create_app
from backend.repositories.protocols import IdempotencyConflict
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


def _first_process(run_id: str) -> tuple[str, str, str, int, list[str], str]:
    evidence_bytes = b'northwind-local-mvp-evidence'
    app = create_app()
    with TestClient(app) as client:
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

        policy = _expect(
            client.post(
                '/internal/v1/policy/search',
                headers=INTEGRATION_AUTH,
                json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
            ),
            200,
            'policy evidence lookup',
        )
        ambiguous_policy = _expect(
            client.post(
                '/internal/v1/policy/search',
                headers=INTEGRATION_AUTH,
                json={
                    'claim_id': claim_id,
                    'policy_reference': 'synthetic-policy-ambiguous',
                },
            ),
            200,
            'ambiguous policy lookup',
        )
        history = _expect(
            client.post(
                '/internal/v1/claim-history/search',
                headers=INTEGRATION_AUTH,
                json={
                    'claim_id': claim_id,
                    'history_reference': 'synthetic-history-204',
                    'purpose': 'relevant_history_review',
                },
            ),
            200,
            'claim history lookup',
        )
        no_evidence = _expect(
            client.post(
                '/internal/v1/policy/search',
                headers=INTEGRATION_AUTH,
                json={'claim_id': claim_id, 'policy_reference': f'{run_id}-missing'},
            ),
            200,
            'policy no-evidence lookup',
        )
        if (
            policy['status'] != 'evidence_found'
            or ambiguous_policy['status'] != 'ambiguous'
            or history['status'] != 'evidence_found'
            or no_evidence['status'] != 'no_evidence'
        ):
            raise RuntimeError('Policy or history lookup statuses crossed their typed boundaries.')
        provider_safe_payload = json.dumps([policy, ambiguous_policy, history])
        if any(
            banned in provider_safe_payload
            for banned in ('fraud_label', 'risk_score', 'policy_conclusion', 'internal_note')
        ):
            raise RuntimeError(
                'A provider-only policy or history field crossed the mapper boundary.'
            )

        adapter = app.state.policy_history_adapter
        if not isinstance(adapter, MockPolicyHistoryAdapter):
            raise RuntimeError('The local MVP policy/history fixture was not selected explicitly.')
        adapter.set_outage(
            RetrievalUnavailable(
                code='PROVIDER_UNAVAILABLE',
                detail='Synthetic local MVP provider outage.',
            )
        )
        try:
            unavailable = _expect(
                client.post(
                    '/internal/v1/claim-history/search',
                    headers=INTEGRATION_AUTH,
                    json={
                        'claim_id': claim_id,
                        'history_reference': 'synthetic-history-204',
                        'purpose': 'relevant_history_review',
                    },
                ),
                200,
                'claim history unavailable lookup',
            )
        finally:
            adapter.set_outage(None)
        if unavailable['status'] != 'unavailable' or unavailable['facts'] is not None:
            raise RuntimeError('Provider unavailability was not kept distinct from no evidence.')

        retrieval_ids = [
            str(policy['result_id']),
            str(ambiguous_policy['result_id']),
            str(history['result_id']),
        ]
        return (
            claim_id,
            session_id,
            evidence_id,
            int(completed['revision']),
            retrieval_ids,
            str(ambiguous_policy['result_id']),
        )


def _second_process(
    run_id: str,
    claim_id: str,
    session_id: str,
    evidence_id: str,
    expected_revision: int,
    retrieval_ids: list[str],
    ambiguous_retrieval_id: str,
) -> dict[str, object]:
    app = create_app()
    with TestClient(app) as client:
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
        if 'retrievals' in claim or 'signals' in claim:
            raise RuntimeError('Staff-only retrieval evidence leaked into the claimant projection.')
        recovered_retrievals = cast(list[dict[str, Any]], staff['retrievals'])
        if {str(item['retrieval_id']) for item in recovered_retrievals} != set(retrieval_ids):
            raise RuntimeError(
                'Policy and history retrieval records did not recover after restart.'
            )
        repository = app.state.data_runtime_bundle.repository
        recovered_signals = repository.list_review_signals(claim_id, 'cus_demo')
        expected_signal_id = f'sig_{ambiguous_retrieval_id}'
        if [signal.signal_id for signal in recovered_signals] != [expected_signal_id]:
            raise RuntimeError('The retrieval review signal did not recover after restart.')

        ambiguous_record = next(
            item
            for item in repository.list_retrieval_records(claim_id, 'cus_demo')
            if item.retrieval_id == ambiguous_retrieval_id
        )
        rollback_retrieval_id = f'ret_{run_id}_rollback'
        rollback_record = ambiguous_record.model_copy(
            update={'retrieval_id': rollback_retrieval_id}
        )
        conflicting_signal = recovered_signals[0].model_copy(
            update={
                'source_refs': [rollback_retrieval_id, ambiguous_record.source.reference],
                'summary': 'This conflicting replay must roll back atomically.',
            }
        )
        try:
            repository.save_retrieval_bundle(
                rollback_record,
                [conflicting_signal],
                'cus_demo',
            )
        except IdempotencyConflict:
            pass
        else:
            raise RuntimeError('A conflicting retrieval bundle was not rejected.')
        if any(
            item.retrieval_id == rollback_retrieval_id
            for item in repository.list_retrieval_records(claim_id, 'cus_demo')
        ):
            raise RuntimeError('A rejected retrieval bundle left a partial MongoDB record.')
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
        'retrieval_records': len(retrieval_ids),
        'review_signals': 1,
        'retrieval_rollback': 'verified',
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
        claim_id, session_id, evidence_id, revision, retrieval_ids, ambiguous_id = _first_process(
            run_id
        )
        result = _second_process(
            run_id,
            claim_id,
            session_id,
            evidence_id,
            revision,
            retrieval_ids,
            ambiguous_id,
        )
    print(json.dumps({'status': 'PASS', 'run_id': run_id, **result}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
