"""Audit construction sites and exercise three family states through the v8 API."""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.domain.models import FormStatus
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentTurnProvider
from tests.journey_v8_support import V8JourneyProvider, envelope
from tests.test_branch_registry import field

SERVICES = Path(__file__).resolve().parents[1] / 'backend' / 'services'


def _always_none_parameter(
    function: ast.FunctionDef, parameter: str, trees: list[ast.Module]
) -> bool:
    arguments = [*function.args.posonlyargs, *function.args.args]
    defaults = (
        dict(
            zip(
                [arg.arg for arg in arguments[-len(function.args.defaults) :]],
                function.args.defaults,
                strict=True,
            )
        )
        if function.args.defaults
        else {}
    )
    defaults.update(
        {
            arg.arg: default
            for arg, default in zip(
                function.args.kwonlyargs, function.args.kw_defaults, strict=True
            )
            if default is not None
        }
    )
    default = defaults.get(parameter)
    if not isinstance(default, ast.Constant) or default.value is not None:
        return False
    calls = [
        call
        for tree in trees
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == function.name
    ]
    if not calls:
        return False
    for call in calls:
        if any(item.arg is None for item in call.keywords):
            return False
        supplied = next((item.value for item in call.keywords if item.arg == parameter), None)
        if supplied is not None and not (
            isinstance(supplied, ast.Constant) and supplied.value is None
        ):
            return False
    return True


def test_every_namespaced_proposal_constructor_supplies_a_trace() -> None:
    files = sorted(SERVICES.glob('*.py'))
    trees = [ast.parse(path.read_text(encoding='utf-8')) for path in files]
    violations = []
    checked = 0
    for path, tree in zip(files, trees, strict=True):
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            for call in ast.walk(function):
                if (
                    not isinstance(call, ast.Call)
                    or not isinstance(call.func, ast.Name)
                    or call.func.id != 'AgentProposal'
                ):
                    continue
                keywords = {item.arg: item.value for item in call.keywords}
                action = keywords.get('action_code')
                if action is None or (isinstance(action, ast.Constant) and action.value is None):
                    continue
                if isinstance(action, ast.Name) and _always_none_parameter(
                    function, action.id, trees
                ):
                    continue
                checked += 1
                trace = keywords.get('runtime_trace')
                if trace is None or (isinstance(trace, ast.Constant) and trace.value is None):
                    violations.append(f'{path.name}:{call.lineno} {function.name}')
    assert checked >= 3
    assert not violations, 'Namespaced proposals missing a construction trace: ' + ', '.join(
        violations
    )


@pytest.fixture
def agent_turn_provider() -> AgentTurnProvider:
    return V8JourneyProvider([envelope()])


@pytest.mark.parametrize('family_state', ['unresolved', 'ambiguous', 'conflicting'])
def test_non_authoritative_family_still_receives_model_reply_and_trace(
    client: TestClient, repository: FixtureRepository, family_state: str
) -> None:
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    created = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': family_state},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    claim_id, session_id = body['claim']['claim_id'], body['session']['session_id']
    revision = body['claim']['revision']
    if family_state == 'conflicting':
        claim = repository.get_claim_internal(claim_id)
        assert claim is not None
        repository.save_claim(
            claim.model_copy(
                update={
                    'incident_type': 'motor',
                    'form': {'claim.product_family': field('home', FormStatus.CONFIRMED)},
                    'revision': revision + 1,
                }
            ),
            revision,
        )
        revision += 1
    message = (
        'My car and house were damaged.'
        if family_state == 'ambiguous'
        else 'Please help me report what happened.'
    )
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**headers, 'Idempotency-Key': f'turn-{family_state}', 'If-Match': str(revision)},
        json={
            'client_message_id': f'turn-{family_state}',
            'content': {'type': 'text', 'text': message},
        },
    )
    assert response.status_code == 200, response.text
    turn = response.json()
    assert turn['agent_message'] is not None
    trace = repository.find_runtime_trace_for_trigger(
        claim_id, turn['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
    )
    assert trace is not None
    assert trace.model_invocations == 1
    assert trace.action_code == 'conversation.answer'
