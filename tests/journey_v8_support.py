"""Shared real-API, mocked-provider acceptance harness for v8 claimant journeys.

Only model transport and the published test policy are controlled here.  No
Claim, reducer, form, confirmation or lifecycle mutation is patched. The
published production v8 request ceilings apply; these are workflow/contract
tests, not live provider latency evidence.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.domain.configuration import ModelRuntimeConfiguration
from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext
from backend.services.model_agent import GatewayAgent
from backend.services.provider_capability_registry import provider_capability
from tests.issue_928_support import prepare_claim_submission
from tests.test_agent_context_runtime_v7 import _RecordingGateway
from tests.test_claim_api import create_claim, submit_message
from tests.test_turn_proposal_v8 import v8_context

CLAIMANT = {'Authorization': 'Bearer synthetic-claimant'}
STAFF = {'Authorization': 'Bearer synthetic-staff'}


def fact(
    code: str,
    value: Any,
    quote: str | None = None,
    *,
    precision: str = 'exact',
    disposition: str = 'value',
    service_identity: str | None = None,
) -> dict[str, Any]:
    return {
        'field_code': code,
        'value': value,
        'reported_text': quote,
        'precision': precision,
        'disposition': disposition,
        'service_identity': service_identity,
    }


def unknown_for_now(code: str, quote: str) -> dict[str, Any]:
    """The claimant said they cannot supply this fact yet."""

    return fact(code, None, quote, precision='unknown', disposition='claimant_will_supply')


def third_party_fills(code: str, service_identity: str, quote: str | None = None) -> dict[str, Any]:
    """The fact should come from a registered service, not the claimant."""

    return fact(
        code,
        None,
        quote,
        precision='unknown',
        disposition='third_party_pending',
        service_identity=service_identity,
    )


def envelope(
    *,
    fields: Sequence[dict[str, Any]] = (),
    question: str | None = None,
    services: Sequence[str] = (),
    requested: Mapping[str, str] | None = None,
    items: Sequence[dict[str, Any]] = (),
    confirms: bool = False,
    action: str | None = None,
    reply: str = 'I have recorded these details.',
    summary_fields: Sequence[str] | None = None,
    documents: Sequence[dict[str, Any]] = (),
    interpretations: Sequence[dict[str, Any]] = (),
    ready: bool = False,
    escalation: dict[str, str] | None = None,
) -> dict[str, Any]:
    if action is None:
        action = (
            'summarize'
            if summary_fields is not None
            else 'propose_submit'
            if ready
            else 'offer_service'
            if services
            else 'record_and_ask'
        )
    return {
        'action': action,
        'reply': reply,
        'reason_codes': ['FACT_RECORDED'],
        'field_changes': list(fields),
        'contents_item_changes': list(items),
        'next_question': {
            'field_codes': [question],
            'wording': f'Please tell me about {question}?',
            'reason': 'natural_follow_up',
        }
        if question
        else None,
        'service_suggestions': [
            {
                'service_identity': service,
                'rationale': 'This support fits the reported situation.',
                'claimant_request_quote': (requested or {}).get(service),
            }
            for service in services
        ],
        'document_requests': list(documents),
        'evidence_interpretations': list(interpretations),
        'summary_fields': list(summary_fields) if summary_fields is not None else None,
        'state_proposals': [],
        'escalation': escalation,
        'ready_to_create': ready,
        'confirms_batch': confirms,
    }


class V8JourneyProvider:
    def __init__(self, proposals: Sequence[dict[str, Any]]) -> None:
        self.gateway = _RecordingGateway(
            [
                ModelResponse(
                    completion_status=ModelCompletionStatus.COMPLETE,
                    structured_output=value,
                    provider_model='openai/gpt-4o',
                )
                for value in proposals
            ]
        )
        self.agent = GatewayAgent(self.gateway)

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        template = v8_context(context.message_text or '')
        policy = template.runtime_policy
        assert policy is not None
        assert template.runtime_configuration_snapshot is not None
        previous = template.runtime_configuration_snapshot.model('qwen-local')
        assert previous is not None
        assert policy.controlled_rules.context_budget_policy is not None
        config = {
            **previous.values,
            'profile_id': 'openrouter-gpt-4o',
            'provider': 'openrouter',
            'model_identifier': 'openai/gpt-4o',
            'base_url': 'https://openrouter.example.test/v1',
            'document_input': False,
        }
        record = previous.model_copy(
            update={'configuration_key': 'openrouter-gpt-4o', 'values': config}
        )
        snapshot = replace(
            template.runtime_configuration_snapshot,
            configurations=MappingProxyType({'model:openrouter-gpt-4o': record}),
        )
        policy = replace(
            policy,
            runtime_snapshot=snapshot,
            tool_policy=policy.tool_policy.model_copy(
                update={
                    'provider_capabilities': {
                        'openrouter-gpt-4o': provider_capability(
                            ModelRuntimeConfiguration.model_validate(config)
                        )
                    },
                }
            ),
        )
        evaluator = policy.branch_evaluator()
        evaluation = evaluator.evaluate(
            context.claim,
            latest_message=context.message_text,
            recomputation_reason='fixture_v8_journey',
        )
        return self.agent.propose_turn(
            replace(
                context,
                model_profile_id='openrouter-gpt-4o',
                runtime_configuration_snapshot=snapshot,
                runtime_policy=policy,
                branch_evaluation=evaluation,
            )
        )


class Journey:
    def __init__(self, client: TestClient, family: str, key: str) -> None:
        self.client = client
        self.key = key
        self.request_paths: list[tuple[str, str]] = []
        client.event_hooks['request'].append(
            lambda request: self.request_paths.append((request.method, request.url.path))
        )
        created = create_claim(client, CLAIMANT, key=key, incident_type=family)
        assert created.status_code == 201, created.text
        body = created.json()
        self.claim_id = body['claim']['claim_id']
        self.session_id = body['session']['session_id']
        self.revision = body['claim']['revision']
        self.turns: list[dict[str, Any]] = []

    def send(self, message: str, *, expect_agent_message: bool = True) -> dict[str, Any]:
        count = len(self.turns) + 1
        response = submit_message(
            self.client,
            CLAIMANT,
            self.claim_id,
            self.session_id,
            revision=self.revision,
            key=f'{self.key}-{count}',
            client_message_id=f'{self.key}-{count}',
            text=message,
        )
        assert response.status_code == 200, response.text
        body = cast(dict[str, Any], response.json())
        if expect_agent_message:
            assert body['agent_message'] is not None, body
        else:
            assert body['agent_message'] is None, body
        self.revision = body['claim_revision']
        self.turns.append(body)
        return body

    def view(self) -> dict[str, Any]:
        response = self.client.get(f'/api/v1/claims/{self.claim_id}', headers=CLAIMANT)
        assert response.status_code == 200, response.text
        return cast(dict[str, Any], response.json())

    def budget_measurements(self, repository: FixtureRepository) -> list[dict[str, Any]]:
        # A turn silenced by an active handoff never invokes the model, so it
        # never creates a RuntimeTraceRecord; it contributes no budget usage.
        measurements: list[dict[str, Any]] = []
        for turn in self.turns:
            if turn['agent_message'] is None:
                continue
            trace = repository.find_runtime_trace_for_trigger(
                self.claim_id, turn['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
            )
            assert trace is not None
            measurements.append(cast(dict[str, Any], trace.request_budget['invocations'][0]))
        return measurements

    def create(self) -> dict[str, Any]:
        self.revision = prepare_claim_submission(
            self.client,
            CLAIMANT,
            self.claim_id,
            self.revision,
            key=f'{self.key}-submit',
        )
        response = self.client.post(
            f'/api/v1/claims/{self.claim_id}/creation',
            headers={
                **CLAIMANT,
                'Idempotency-Key': f'{self.key}-create',
                'If-Match': str(self.revision),
            },
        )
        assert response.status_code == 201, response.text
        self.revision = response.json()['revision']
        assert self.view()['workflow_state'] == 'created'
        assert not any(path.endswith('/form/confirmations') for _, path in self.request_paths)
        assert sum(
            method == 'POST' and '/sessions/' in path and path.endswith('/messages')
            for method, path in self.request_paths
        ) == len(self.turns)
        return cast(dict[str, Any], response.json())

    def resolve_handoff(self, repository: FixtureRepository, handoff_id: str) -> None:
        accepted = self.client.post(
            f'/api/v1/workbench/claims/{self.claim_id}/handoffs/{handoff_id}/accept',
            headers={
                **STAFF,
                'Idempotency-Key': f'{self.key}-accept',
                'If-Match': str(self.revision),
            },
            json={},
        )
        assert accepted.status_code == 200, accepted.text
        self.revision = accepted.json()['revision']
        handoff = repository.get_handoff(self.claim_id, handoff_id, 'cus_8f41a2c90d7e463b')
        assert handoff is not None
        assert handoff.resume_workflow_state is not None
        assert handoff.resume_next_action is not None
        resolved = self.client.post(
            f'/api/v1/workbench/claims/{self.claim_id}/handoffs/{handoff_id}/resolve',
            headers={
                **STAFF,
                'Idempotency-Key': f'{self.key}-resolve',
                'If-Match': str(self.revision),
            },
            json={
                'result': {
                    'outcome': 'support_completed',
                    'summary': 'Safety support is complete.',
                    'reason_codes': ['SUPPORT_NEED_MET'],
                    'source_refs': handoff.packet.source_refs,
                },
                'state_changes': [
                    {
                        'path': 'claim_state.workflow_state',
                        'to': handoff.resume_workflow_state.value,
                    },
                    {'path': 'claim_state.next_action', 'to': handoff.resume_next_action.value},
                ],
                'customer_update': {
                    'summary': 'You can continue your report.',
                    'responsible_party': 'claims_professional',
                    'related_refs': [handoff_id],
                },
            },
        )
        assert resolved.status_code == 200, resolved.text
        self.revision = resolved.json()['revision']
