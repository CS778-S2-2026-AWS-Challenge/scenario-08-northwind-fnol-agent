"""Run the complete motor VP journey against a deployed HTTP stack.

The smoke deliberately uses normal identity mode and the public API boundary. It is
deployment evidence for the controlled VP, not a replacement for the backend test suite.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx

MOTOR_DESCRIPTION = (
    'Another car hit the rear of mine at Queen Street this morning and damaged the rear '
    'bumper. Nobody was injured and the scene is safe. The vehicle is safe to drive.'
)
MOTOR_FIELDS = [
    'incident.description',
    'incident.type',
    'incident.location',
    'loss.description',
    'incident.injury_or_danger',
    'incident.occurred_at',
    'parties.other_parties',
    'vehicle.damage_description',
    'vehicle.drivable',
]


def _json(response: httpx.Response, expected: set[int], step: str) -> dict[str, Any]:
    if response.status_code not in expected:
        raise RuntimeError(f'{step} failed with HTTP {response.status_code}: {response.text}')
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f'{step} returned a non-object JSON response.')
    return cast(dict[str, Any], value)


def _bearer(payload: dict[str, Any]) -> dict[str, str]:
    token = payload.get('access_token')
    if not isinstance(token, str) or not token:
        raise RuntimeError('Authentication response did not contain an access token.')
    return {'Authorization': f'Bearer {token}'}


def _restart_backend(directory: Path) -> None:
    result = subprocess.run(
        ['docker', 'compose', '--profile', 'vp', 'restart', 'backend'],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f'backend restart failed: {result.stderr.strip()}')


def _wait_ready(client: httpx.Client) -> dict[str, Any]:
    for _ in range(60):
        try:
            response = client.get('/health/ready')
            if response.status_code == 200:
                return _json(response, {200}, 'readiness')
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError('deployed backend did not become ready after restart.')


def run(base_url: str, compose_directory: Path, *, restart: bool) -> dict[str, Any]:
    staff_email = os.environ.get('NORTHWIND_VP_STAFF_EMAIL', '').strip()
    staff_password = os.environ.get('NORTHWIND_VP_STAFF_PASSWORD', '')
    if not staff_email or not staff_password:
        raise RuntimeError(
            'Set NORTHWIND_VP_STAFF_EMAIL and NORTHWIND_VP_STAFF_PASSWORD '
            'for the deployed staff account.'
        )

    run_id = f'vp-smoke-{uuid4().hex[:12]}'
    claimant_email = f'{run_id}@northwind.invalid'
    claimant_password = f'Northwind-{uuid4().hex[:20]}!'
    client = httpx.Client(base_url=base_url.rstrip('/'), timeout=20.0)
    try:
        claimant = _json(
            client.post(
                '/api/v1/auth/accounts',
                json={
                    'email': claimant_email,
                    'password': claimant_password,
                    'display_name': 'VP Smoke Claimant',
                },
            ),
            {201},
            'claimant registration',
        )
        claimant_auth = _bearer(claimant)
        staff = _json(
            client.post(
                '/api/v1/staff/auth/sessions',
                json={'email': staff_email, 'password': staff_password},
            ),
            {201},
            'staff login',
        )
        staff_auth = _bearer(staff)

        claim_response = _json(
            client.post(
                '/api/v1/claims',
                headers={**claimant_auth, 'Idempotency-Key': f'{run_id}-claim'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            ),
            {201},
            'claim creation',
        )
        claim_replay = _json(
            client.post(
                '/api/v1/claims',
                headers={**claimant_auth, 'Idempotency-Key': f'{run_id}-claim'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            ),
            {200, 201},
            'claim creation replay',
        )
        if claim_replay != claim_response:
            raise RuntimeError('claim creation replay did not return the original response.')
        claim = cast(dict[str, Any], claim_response['claim'])
        claim_id = str(claim['claim_id'])
        session_id = str(cast(dict[str, Any], claim_response['session'])['session_id'])
        claim_revision = int(claim['revision'])

        message_headers = {
            **claimant_auth,
            'Idempotency-Key': f'{run_id}-description',
            'If-Match': str(claim_revision),
        }
        message_payload = {
            'client_message_id': f'{run_id}-description',
            'content': {'type': 'text', 'text': MOTOR_DESCRIPTION},
            'evidence_refs': [],
        }
        message = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers=message_headers,
                json=message_payload,
            ),
            {200},
            'motor description',
        )
        replayed_message = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers=message_headers,
                json=message_payload,
            ),
            {200},
            'motor description replay',
        )
        if replayed_message != message:
            raise RuntimeError('message replay did not return the original response.')

        confirmation = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/form/confirmations',
                headers={
                    **claimant_auth,
                    'Idempotency-Key': f'{run_id}-confirmation',
                    'If-Match': str(message['claim_revision']),
                },
                json={'field_codes': MOTOR_FIELDS},
            ),
            {200},
            'form confirmation',
        )
        confirmation_replay = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/form/confirmations',
                headers={
                    **claimant_auth,
                    'Idempotency-Key': f'{run_id}-confirmation',
                    'If-Match': str(message['claim_revision']),
                },
                json={'field_codes': MOTOR_FIELDS},
            ),
            {200},
            'form confirmation replay',
        )
        if confirmation_replay != confirmation:
            raise RuntimeError('form confirmation replay did not return the original response.')
        creation = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/creation',
                headers={
                    **claimant_auth,
                    'Idempotency-Key': f'{run_id}-creation',
                    'If-Match': str(confirmation['revision']),
                },
            ),
            {201},
            'external claim creation',
        )
        creation_replay = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/creation',
                headers={
                    **claimant_auth,
                    'Idempotency-Key': f'{run_id}-creation',
                    'If-Match': str(confirmation['revision']),
                },
            ),
            {200, 201},
            'external claim creation replay',
        )
        if creation_replay != creation:
            raise RuntimeError(
                'external claim creation replay did not return the original response.'
            )
        consent = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/assessor-routing/consent',
                headers={
                    **claimant_auth,
                    'Idempotency-Key': f'{run_id}-consent',
                    'If-Match': str(creation['revision']),
                },
                json={'consent': True},
            ),
            {201},
            'assessor consent',
        )
        consent_replay = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/assessor-routing/consent',
                headers={
                    **claimant_auth,
                    'Idempotency-Key': f'{run_id}-consent',
                    'If-Match': str(creation['revision']),
                },
                json={'consent': True},
            ),
            {200, 201},
            'assessor consent replay',
        )
        if consent_replay != consent:
            raise RuntimeError('assessor consent replay did not return the original response.')
        assessor_headers = {
            **claimant_auth,
            'Idempotency-Key': f'{run_id}-assessor',
            'If-Match': str(consent['revision']),
        }
        assessor = _json(
            client.post(f'/api/v1/claims/{claim_id}/assessor-routing', headers=assessor_headers),
            {201},
            'assessor request',
        )
        assessor_replay = _json(
            client.post(f'/api/v1/claims/{claim_id}/assessor-routing', headers=assessor_headers),
            {200},
            'assessor request replay',
        )
        if assessor_replay != assessor:
            raise RuntimeError('assessor replay did not return the original response.')
        if assessor['action']['status'] != 'assigned':
            raise RuntimeError('assessor request did not reach assigned status.')

        support_headers = {
            **claimant_auth,
            'Idempotency-Key': f'{run_id}-support',
            'If-Match': str(assessor['revision']),
        }
        support_payload = {
            'reason': 'I want to speak with a person now.',
            'support_need': 'human_requested',
            'preferred_channel': 'email',
        }
        support = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/support-requests',
                headers=support_headers,
                json=support_payload,
            ),
            {201},
            'Staff Assistance request',
        )
        support_replay = _json(
            client.post(
                f'/api/v1/claims/{claim_id}/support-requests',
                headers=support_headers,
                json=support_payload,
            ),
            {200, 201},
            'Staff Assistance replay',
        )
        if support_replay != support:
            raise RuntimeError('Staff Assistance replay did not return the original response.')
        handoff_id = str(support['handoff']['handoff_id'])

        detail = _json(
            client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth),
            {200},
            'Workbench detail',
        )
        accepted_headers = {
            **staff_auth,
            'Idempotency-Key': f'{run_id}-accept',
            'If-Match': str(detail['revision']),
        }
        accepted = _json(
            client.post(
                f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
                headers=accepted_headers,
                json={},
            ),
            {200},
            'Workbench handoff acceptance',
        )
        accepted_replay = _json(
            client.post(
                f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/accept',
                headers=accepted_headers,
                json={},
            ),
            {200},
            'Workbench handoff acceptance replay',
        )
        if accepted_replay != accepted:
            raise RuntimeError('handoff acceptance replay did not return the original response.')

        reply_headers = {
            **staff_auth,
            'Idempotency-Key': f'{run_id}-reply',
            'If-Match': str(accepted['revision']),
        }
        reply_payload = {
            'content': {
                'type': 'text',
                'text': 'Northwind has accepted your request for staff assistance.',
            }
        }
        reply = _json(
            client.post(
                f'/api/v1/workbench/claims/{claim_id}/messages',
                headers=reply_headers,
                json=reply_payload,
            ),
            {200},
            'staff reply',
        )
        reply_replay = _json(
            client.post(
                f'/api/v1/workbench/claims/{claim_id}/messages',
                headers=reply_headers,
                json=reply_payload,
            ),
            {200},
            'staff reply replay',
        )
        if reply_replay != reply:
            raise RuntimeError('staff reply replay did not return the original response.')

        handoffs = _json(
            client.get(f'/api/v1/workbench/claims/{claim_id}/handoffs', headers=staff_auth),
            {200},
            'Workbench handoff listing',
        )
        handoff = next(item for item in handoffs['items'] if item['handoff_id'] == handoff_id)
        resolve_headers = {
            **staff_auth,
            'Idempotency-Key': f'{run_id}-resolve',
            'If-Match': str(reply['claim_revision']),
        }
        resolve_payload = {
            'result': {
                'outcome': 'support_completed',
                'summary': 'The staff member reviewed and accepted the report.',
                'reason_codes': ['SUPPORT_NEED_MET'],
                'source_refs': handoff['packet']['source_refs'],
            },
            'state_changes': [],
            'customer_update': {
                'summary': 'Northwind staff has reviewed your report.',
                'responsible_party': 'claims_professional',
                'related_refs': [handoff_id],
            },
        }
        resolved = _json(
            client.post(
                f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve',
                headers=resolve_headers,
                json=resolve_payload,
            ),
            {200},
            'handoff resolution',
        )
        resolved_replay = _json(
            client.post(
                f'/api/v1/workbench/claims/{claim_id}/handoffs/{handoff_id}/resolve',
                headers=resolve_headers,
                json=resolve_payload,
            ),
            {200},
            'handoff resolution replay',
        )
        if resolved_replay != resolved:
            raise RuntimeError('handoff resolution replay did not return the original response.')

        if restart:
            _restart_backend(compose_directory)
            readiness = _wait_ready(client)
            claimant_after = _json(
                client.post(
                    '/api/v1/auth/sessions',
                    json={'email': claimant_email, 'password': claimant_password},
                ),
                {201},
                'claimant login after restart',
            )
            staff_after = _json(
                client.post(
                    '/api/v1/staff/auth/sessions',
                    json={'email': staff_email, 'password': staff_password},
                ),
                {201},
                'staff login after restart',
            )
            claimant_after_auth = _bearer(claimant_after)
            staff_after_auth = _bearer(staff_after)
            recovered_claim = _json(
                client.get(f'/api/v1/claims/{claim_id}', headers=claimant_after_auth),
                {200},
                'claim recovery after restart',
            )
            recovered_detail = _json(
                client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_after_auth),
                {200},
                'Workbench recovery after restart',
            )
            recovered_messages = _json(
                client.get(
                    f'/api/v1/workbench/claims/{claim_id}/sessions/{session_id}/messages',
                    headers=staff_after_auth,
                ),
                {200},
                'message recovery after restart',
            )
            recovered_handoffs = _json(
                client.get(
                    f'/api/v1/workbench/claims/{claim_id}/handoffs', headers=staff_after_auth
                ),
                {200},
                'handoff recovery after restart',
            )
            recovered_external = _json(
                client.get(
                    f'/api/v1/workbench/claims/{claim_id}/external-requests',
                    headers=staff_after_auth,
                ),
                {200},
                'external request recovery after restart',
            )
            if recovered_claim['claim_id'] != claim_id or recovered_detail['claim_id'] != claim_id:
                raise RuntimeError('restarted services returned a different Claim.')
            if len(recovered_messages['items']) != 3:
                raise RuntimeError('restart recovery produced duplicate or missing messages.')
            if len(recovered_handoffs['items']) != 1:
                raise RuntimeError('restart recovery produced duplicate or missing handoffs.')
            if len(recovered_external['items']) != 1:
                raise RuntimeError(
                    'restart recovery produced duplicate or missing external requests.'
                )
            return {
                'status': 'PASS',
                'run_id': run_id,
                'claim_id': claim_id,
                'assessor_status': assessor['action']['status'],
                'handoff_status': resolved['handoff']['status'],
                'recovered_messages': len(recovered_messages['items']),
                'recovered_handoffs': len(recovered_handoffs['items']),
                'recovered_external_requests': len(recovered_external['items']),
                'persistence': readiness['checks']['persistence'],
            }
        return {
            'status': 'PASS',
            'run_id': run_id,
            'claim_id': claim_id,
            'assessor_status': assessor['action']['status'],
            'handoff_status': resolved['handoff']['status'],
        }
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--compose-directory', type=Path, default=Path.cwd())
    parser.add_argument('--no-restart', action='store_true')
    args = parser.parse_args()
    result = run(args.base_url, args.compose_directory, restart=not args.no_restart)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
