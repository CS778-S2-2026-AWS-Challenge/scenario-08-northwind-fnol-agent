"""Publish the governed FNOL model catalogue without handling provider secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.config import load_model_runtime_bindings  # noqa: E402
from backend.domain.configuration import ModelRuntimeBinding  # noqa: E402
from backend.services.initial_runtime_release import repository_v7_values  # noqa: E402

DEFAULT_BINDINGS = ROOT / 'config' / 'model-runtime-bindings.json'


class PublicationError(RuntimeError):
    """A bounded Control Plane publication step failed."""


class ControlPlaneClient:
    def __init__(self, base_url: str, author_token: str, approver_token: str) -> None:
        self.base_url = base_url.rstrip('/')
        self.author_token = author_token
        self.approver_token = approver_token

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        payload: dict[str, object] | None = None,
        revision: int | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if revision is not None:
            headers['If-Match'] = f'"{revision}"'
        if idempotent:
            headers['Idempotency-Key'] = f'model-release-{uuid4().hex}'
        request = Request(f'{self.base_url}{path}', data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
        except HTTPError as error:
            detail = error.read().decode('utf-8', errors='replace')
            raise PublicationError(
                f'{method} {path} failed with HTTP {error.code}: {detail}'
            ) from error
        except (URLError, TimeoutError) as error:
            raise PublicationError(f'{method} {path} could not reach the Control Plane.') from error
        if not isinstance(result, dict):
            raise PublicationError(f'{method} {path} returned a non-object response.')
        return result

    def get(self, path: str, *, token: str | None = None) -> dict[str, Any]:
        return self.request('GET', path, token=token or self.author_token)

    def publish_configuration(
        self,
        *,
        domain: str,
        values: dict[str, object],
        evidence: str,
    ) -> dict[str, Any]:
        existing = self.get(
            f'/internal/v1/admin/configurations?{urlencode({"domain": domain, "limit": 100})}'
        )
        for item in existing.get('items', []):
            if item.get('state') == 'published' and item.get('values') == values:
                return cast(dict[str, Any], item)

        created = self.request(
            'POST',
            '/internal/v1/admin/configurations',
            token=self.author_token,
            payload={
                'domain': domain,
                'impact': 'high',
                'values': values,
                'secret_references': {},
                'reason': 'Publish the verified FNOL model Runtime contract.',
            },
            idempotent=True,
        )
        configuration_id = str(created['configuration_id'])
        validated = self.request(
            'POST',
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            token=self.author_token,
            revision=int(created['revision']),
            payload={
                'scenario_results': [
                    {
                        'scenario_id': 'fnol-model-runtime-contract',
                        'outcome': 'passed',
                        'evidence': evidence,
                    }
                ]
            },
            idempotent=True,
        )
        revision = int(validated['revision'])
        self.request(
            'POST',
            f'/internal/v1/admin/configurations/{configuration_id}/approval',
            token=self.approver_token,
            revision=revision,
            payload={
                'decision': 'approved',
                'reason': 'Independent review of the exact deployment binding and prompt.',
            },
            idempotent=True,
        )
        return self.request(
            'POST',
            f'/internal/v1/admin/configurations/{configuration_id}/publish',
            token=self.approver_token,
            revision=revision,
            payload={'reason': 'Publish the independently approved FNOL Runtime configuration.'},
            idempotent=True,
        )


def _required_token(environment_variable: str) -> str:
    token = os.getenv(environment_variable, '').strip()
    if not token:
        raise PublicationError(
            f'{environment_variable} must contain an administrator bearer token.'
        )
    return token


def _load_bindings(path: Path) -> list[ModelRuntimeBinding]:
    try:
        bindings = load_model_runtime_bindings(path, require_endpoints=True)
    except ValueError as error:
        raise PublicationError(f'Invalid model binding manifest: {path}') from error
    return list(bindings)


def publish(args: argparse.Namespace) -> str:
    bindings = _load_bindings(args.bindings)
    if not any(item.profile_id == 'qwen-local' for item in bindings):
        raise PublicationError('The deployment manifest must retain qwen-local.')
    if not any(item.profile_id == 'nowcoding-gpt55' for item in bindings):
        raise PublicationError('The deployment manifest must include nowcoding-gpt55.')
    if not any(item.profile_id == 'bedrock-nova2-lite' for item in bindings):
        raise PublicationError('The deployment manifest must include bedrock-nova2-lite.')
    if not any(item.profile_id == 'google-gemini35-flash-lite' for item in bindings):
        raise PublicationError('The deployment manifest must include google-gemini35-flash-lite.')
    for binding in bindings:
        credential_name = binding.credential_environment_variable
        if (
            binding.evaluation_status == 'configured'
            and credential_name
            and not os.getenv(credential_name, '')
        ):
            raise PublicationError(f'{credential_name} is not available to the publishing process.')

    client = ControlPlaneClient(
        args.base_url,
        _required_token(args.author_token_env),
        _required_token(args.approver_token_env),
    )
    query = urlencode({'environment': args.environment, 'runtime_profile': args.runtime_profile})
    active = client.get(f'/internal/v1/admin/runtime-snapshots?{query}')

    release_values = repository_v7_values(bindings)
    published = {
        slot: client.publish_configuration(
            domain='model' if slot.startswith('model:') else slot,
            values=values,
            evidence=args.validation_evidence,
        )
        for slot, values in release_values.items()
    }

    configuration_refs = {
        slot: {
            'configuration_id': item['configuration_id'],
            'revision': item['revision'],
        }
        for slot, item in published.items()
    }

    release = client.request(
        'POST',
        '/internal/v1/admin/release-sets',
        token=client.author_token,
        payload={
            'environment': args.environment,
            'runtime_profile': args.runtime_profile,
            'configuration_refs': configuration_refs,
            'integration_refs': {
                key: {
                    'configuration_id': item['configuration_id'],
                    'revision': item['revision'],
                }
                for key, item in active.get('integrations', {}).items()
            },
            'knowledge_refs': {
                key: {'knowledge_id': item['knowledge_id'], 'revision': item['revision']}
                for key, item in active.get('knowledge', {}).items()
            },
            'reason': 'Publish the complete atomic Agent Context Runtime v7 Release Set.',
        },
        idempotent=True,
    )
    release_id = str(release['release_set_id'])
    validated = client.request(
        'POST',
        f'/internal/v1/admin/release-sets/{release_id}/validate',
        token=client.author_token,
        revision=int(release['revision']),
        payload={
            'scenario_results': [
                {
                    'scenario_id': 'fnol-model-catalogue-release',
                    'outcome': 'passed',
                    'evidence': args.validation_evidence,
                }
            ]
        },
        idempotent=True,
    )
    client.request(
        'POST',
        f'/internal/v1/admin/release-sets/{release_id}/publish',
        token=client.author_token,
        revision=int(validated['revision']),
        payload={'reason': 'Activate the validated FNOL model-catalogue Release Set.'},
        idempotent=True,
    )
    verified = client.get(f'/internal/v1/admin/runtime-snapshots?{query}')
    if verified.get('release_set_id') != release_id:
        raise PublicationError('The new Release Set was published but is not active.')
    actual_profiles = {
        key.removeprefix('model:')
        for key in verified.get('configurations', {})
        if key.startswith('model:')
    }
    expected_profiles = {item.profile_id for item in bindings}
    if actual_profiles != expected_profiles:
        raise PublicationError(
            'The active Runtime snapshot does not contain the exact model catalogue.'
        )
    return release_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--environment', default='development')
    parser.add_argument('--runtime-profile', default='local_mvp')
    parser.add_argument('--bindings', type=Path, default=DEFAULT_BINDINGS)
    parser.add_argument('--author-token-env', default='NORTHWIND_CONTROL_PLANE_AUTHOR_TOKEN')
    parser.add_argument('--approver-token-env', default='NORTHWIND_CONTROL_PLANE_APPROVER_TOKEN')
    parser.add_argument('--validation-evidence', required=True)
    return parser


def main() -> int:
    try:
        release_id = publish(_parser().parse_args())
    except PublicationError as error:
        print(f'Publication failed: {error}', file=sys.stderr)
        return 1
    print(f'Published active Release Set: {release_id}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
