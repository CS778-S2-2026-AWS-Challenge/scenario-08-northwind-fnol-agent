from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    )


def _headers(key: str, token: str = 'synthetic-admin') -> dict[str, str]:
    return {'Authorization': f'Bearer {token}', 'Idempotency-Key': key}


def test_agent_rule_components_are_independent_versioned_records() -> None:
    with _client() as client:
        instruction = client.post(
            '/internal/v1/admin/agent-rules/instructions',
            headers=_headers('agent-instruction-create'),
            json={
                'values': {
                    'prompt_version': 'northwind-fnol-motor-claimant-v4',
                    'purpose': 'claimant_agent',
                    'system_prompt': 'Follow the published claimant Agent policy.',
                },
                'reason': 'Publish the claimant instruction reference.',
            },
        )
        tool_policy = client.post(
            '/internal/v1/admin/agent-rules/tool_permissions',
            headers=_headers('agent-tool-create'),
            json={
                'values': {
                    'policy_version': 'agent-tool-policy-v1',
                    'allowed_action_codes': [
                        'conversation.acknowledge',
                        'conversation.ask',
                        'conversation.state_limitation',
                        'human.create_handoff',
                        'runtime.fail_safe',
                        'runtime.interrupt_urgent',
                    ],
                    'allowed_tool_names': ['handoff_store.create'],
                },
                'reason': 'Publish the claimant tool boundary.',
            },
        )
        assert instruction.status_code == 201, instruction.text
        assert tool_policy.status_code == 201, tool_policy.text
        assert instruction.json()['domain'] == 'agent_instruction'
        assert tool_policy.json()['domain'] == 'agent_tool_policy'
        listed = client.get('/internal/v1/admin/agent-rules', headers=_headers('read'))
        assert listed.status_code == 200
        assert {item['domain'] for item in listed.json()['items']} == {
            'agent_instruction',
            'agent_tool_policy',
        }


def test_non_feature_agent_components_are_high_impact() -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/agent-rules/controlled_rules',
            headers=_headers('agent-rule-impact'),
            json={
                'impact': 'normal',
                'values': {
                    'rules_version': 'controlled-branch-rules-v1',
                    'disabled_rule_ids': [],
                    'observation_rule_ids': [],
                },
                'reason': 'Rule.',
            },
        )
    assert response.status_code == 201
    assert response.json()['impact'] == 'high'


def test_agent_rule_endpoint_rejects_a_component_schema_from_another_domain() -> None:
    with _client() as client:
        response = client.post(
            '/internal/v1/admin/agent-rules/instructions',
            headers=_headers('wrong-agent-component'),
            json={
                'values': {
                    'feature_version': 'features-v1',
                    'model_assisted_turns': True,
                    'knowledge_retrieval': True,
                },
                'reason': 'Do not accept a feature object as an instruction.',
            },
        )
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'AGENT_CONFIGURATION_INVALID'
