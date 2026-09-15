import argparse
import json
from pathlib import Path
from typing import Any, cast

import pytest

from scripts import publish_fnol_model_release as publication


class RecordingControlPlaneClient:
    latest: 'RecordingControlPlaneClient | None' = None

    def __init__(self, base_url: str, author_token: str, approver_token: str) -> None:
        self.base_url = base_url
        self.author_token = author_token
        self.approver_token = approver_token
        self.published_configurations: list[tuple[str, dict[str, object], str]] = []
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []
        self.snapshot_reads = 0
        type(self).latest = self

    def get(self, path: str, *, token: str | None = None) -> dict[str, Any]:
        del token
        assert path.startswith('/internal/v1/admin/runtime-snapshots?')
        self.snapshot_reads += 1
        if self.snapshot_reads == 1:
            return {
                'release_set_id': 'rel_previous',
                'configurations': {
                    'agent_instruction': _record('cfg_old_instruction'),
                    'agent_rule': _record('cfg_rules'),
                    'agent_tool_policy': _record('cfg_tools'),
                    'feature': _record('cfg_feature'),
                    'model:qwen-local': _record('cfg_old_qwen'),
                    'model:retired-profile': _record('cfg_retired_model'),
                },
                'integrations': {'policy': _record('cfg_policy')},
                'knowledge': {'motor': {'knowledge_id': 'kn_motor', 'revision': 4}},
            }
        return {
            'release_set_id': 'rel_new',
            'configurations': {
                'agent_instruction': _record('cfg_agent_instruction'),
                'agent_rule': _record('cfg_rules'),
                'agent_tool_policy': _record('cfg_tools'),
                'feature': _record('cfg_feature'),
                'model:qwen-local': _record('cfg_qwen-local'),
                'model:nowcoding-gpt55': _record('cfg_nowcoding-gpt55'),
            },
        }

    def publish_configuration(
        self,
        *,
        domain: str,
        values: dict[str, object],
        evidence: str,
    ) -> dict[str, Any]:
        self.published_configurations.append((domain, values, evidence))
        suffix = str(values.get('profile_id', domain))
        return _record(f'cfg_{suffix}', values)

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
        del token, revision, idempotent
        self.requests.append((method, path, payload))
        if path == '/internal/v1/admin/release-sets':
            return {'release_set_id': 'rel_new', 'revision': 1}
        if path.endswith('/validate'):
            return {'release_set_id': 'rel_new', 'revision': 2}
        if path.endswith('/publish'):
            return {'release_set_id': 'rel_new', 'revision': 3}
        raise AssertionError(f'Unexpected request: {method} {path}')


def _record(configuration_id: str, values: dict[str, object] | None = None) -> dict[str, Any]:
    return {
        'configuration_id': configuration_id,
        'revision': 3,
        'values': values or {},
    }


def test_publication_preserves_release_context_and_never_serializes_the_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_CONTROL_PLANE_AUTHOR_TOKEN', 'author-token')
    monkeypatch.setenv('NORTHWIND_CONTROL_PLANE_APPROVER_TOKEN', 'approver-token')
    monkeypatch.setenv('NORTHWIND_QWEN_BASE_URL', 'http://qwen.test/v1')
    monkeypatch.setenv('NORTHWIND_MODEL_API_KEY', 'provider-secret-must-not-be-serialized')
    monkeypatch.setattr(publication, 'ControlPlaneClient', RecordingControlPlaneClient)
    args = argparse.Namespace(
        base_url='http://control-plane.test',
        environment='development',
        runtime_profile='local_mvp',
        bindings=Path('config/model-runtime-bindings.json'),
        prompt=Path('backend/prompts/northwind_fnol_claimant_v6.md'),
        author_token_env='NORTHWIND_CONTROL_PLANE_AUTHOR_TOKEN',
        approver_token_env='NORTHWIND_CONTROL_PLANE_APPROVER_TOKEN',
        validation_evidence='Live strict schema and forced tool-call probes passed.',
    )

    release_id = publication.publish(args)

    assert release_id == 'rel_new'
    client = RecordingControlPlaneClient.latest
    assert client is not None
    assert [item[0] for item in client.published_configurations] == [
        'agent_instruction',
        'model',
        'model',
    ]
    release_payload = client.requests[0][2]
    assert release_payload is not None
    configuration_refs = cast(dict[str, object], release_payload['configuration_refs'])
    assert set(configuration_refs) == {
        'agent_instruction',
        'agent_rule',
        'agent_tool_policy',
        'feature',
        'model:qwen-local',
        'model:nowcoding-gpt55',
    }
    assert cast(dict[str, object], release_payload['integration_refs']) == {
        'policy': {'configuration_id': 'cfg_policy', 'revision': 3}
    }
    assert cast(dict[str, object], release_payload['knowledge_refs']) == {
        'motor': {'knowledge_id': 'kn_motor', 'revision': 4}
    }
    serialized = json.dumps(
        {'configurations': client.published_configurations, 'requests': client.requests}
    )
    assert 'provider-secret-must-not-be-serialized' not in serialized
    assert 'NORTHWIND_MODEL_API_KEY' in serialized


def test_publication_requires_environment_owned_private_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NORTHWIND_QWEN_BASE_URL', raising=False)

    with pytest.raises(publication.PublicationError, match='Invalid model binding manifest'):
        publication._load_bindings(Path('config/model-runtime-bindings.json'))
