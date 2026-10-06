"""Policy advice API regressions with real reducers and mocked model/knowledge I/O.

These prove the backend integration and visibility contract, not live model
judgment quality or a browser journey. Persisted facts are synthetic setup.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse, ModelToolCall
from backend.domain.models import (
    ActorReference,
    ActorType,
    FormSource,
    FormStatus,
    NeededFor,
    StructuredFormField,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext
from backend.services.model_agent import GatewayAgent
from backend.services.model_request_planner import plan_model_turn
from tests.journey_v8_support import CLAIMANT, STAFF, Journey, V8JourneyProvider, envelope
from tests.test_agent_context_runtime_v7 import _RecordingGateway
from tests.test_claim_api import submit_message


class GuidanceAgent(GatewayAgent):
    """Mock transport while exercising the actual context resolver and v8 parser."""

    def __init__(
        self, kind: str, clause: str, *, invalid_ref: bool = False, request_handoff: bool = False
    ) -> None:
        self.gateway = _RecordingGateway([])
        super().__init__(self.gateway)
        self.kind = kind
        self.invalid_ref = invalid_ref
        self.request_handoff = request_handoff
        self.chunk = {
            'document_id': 'doc_policy_judgment',
            'chunk_id': 'chk_policy_judgment',
            'title': 'Synthetic standard policy guidance',
            'section_path': clause,
            'source_uri': 'fixture://policy-judgment',
            'version': 'MVP-2026.1',
            'checksum': 'synthetic-policy-checksum',
            'text': 'Staff must review these circumstances against the applicable policy.',
        }

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        context = replace(
            context,
            knowledge_context_loader=lambda _limit: {
                'status': 'evidence_found',
                'chunks': [self.chunk],
            },
        )
        plan = plan_model_turn(context)
        assert plan is not None
        reference = next(
            ref for ref in plan.context_plan.references if ref.resource_type == 'policy_version'
        )
        output = envelope(reply='The claims team can review the applicable policy.')
        if self.request_handoff:
            output['escalation'] = {
                'kind': 'human_requested',
                'reason': 'The claimant asked for staff assistance.',
            }
        output['policy_judgment_proposals'] = [
            {
                'kind': self.kind,
                'assessment': 'Internal advisory assessment, not a coverage decision.',
                'rationale': 'Internal rationale requiring professional review.',
                'source_refs': ['chk_unretrieved' if self.invalid_ref else self.chunk['chunk_id']],
            }
        ]
        self.gateway.responses.extend(
            [
                ModelResponse(
                    tool_calls=[
                        ModelToolCall(
                            call_id='call_judgment_guidance',
                            name='context.resolve',
                            arguments={
                                'ref': reference.ref,
                                'selector': 'matching_facts_and_guidance',
                                'max_tokens': 600,
                            },
                        )
                    ],
                    completion_status=ModelCompletionStatus.COMPLETE,
                ),
                ModelResponse(
                    structured_output=output,
                    completion_status=ModelCompletionStatus.COMPLETE,
                ),
            ]
        )
        return super().propose_turn(context)


def _seed_confirmed_facts(
    repository: FixtureRepository,
    journey: Journey,
    family: str,
    facts: dict[str, Any],
) -> None:
    claim = repository.get_claim_internal(journey.claim_id)
    assert claim is not None
    form = {
        code: StructuredFormField(
            value=value,
            source=FormSource.CLAIMANT,
            status=FormStatus.CONFIRMED,
            needed_for=NeededFor.CURRENT_ACTION,
            updated_at=datetime.now(UTC),
            updated_by=ActorReference(
                actor_type=ActorType.CLAIMANT, actor_id='cus_8f41a2c90d7e463b'
            ),
        )
        for code, value in {'claim.product_family': family, **facts}.items()
    }
    repository._claims[claim.claim_id] = claim.model_copy(
        update={'form': form, 'assignee_id': 'stf_demo'}
    )


FAMILIES = [
    (
        'motor',
        'liability_split',
        'MTR-COV-02',
        {
            'parties.other_parties': True,
            'incident.description': 'Another car hit my car.',
        },
    ),
    (
        'home',
        'gradual_damage_discoverability',
        'HOM-BEN-03',
        {
            'incident.discovered_at': '2026-09-20T09:00:00+12:00',
            'incident.description': 'Water stains appeared underneath the sink.',
        },
    ),
    (
        'contents',
        'theft_circumstance',
        'CON-COV-02',
        {
            'theft.entry_context': 'forced_entry',
            'incident.description': 'A laptop was stolen after the window was forced open.',
        },
    ),
]


@pytest.mark.parametrize(
    ('family', 'kind', 'clause', 'facts', 'decision_value'),
    [
        (*FAMILIES[0], 'confirmed'),
        (*FAMILIES[1], 'dismissed'),
        (*FAMILIES[2], 'overridden'),
        (*FAMILIES[0], 'resolved'),
    ],
)
def test_policy_advice_turn_persists_staff_only_signal_and_existing_decision(
    family: str,
    kind: str,
    clause: str,
    facts: dict[str, Any],
    decision_value: str,
) -> None:
    repository = FixtureRepository()
    provider = V8JourneyProvider([])
    agent = GuidanceAgent(kind, clause)
    provider.agent = agent
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        repository,
        provider,
    )
    with TestClient(app) as client:
        journey = Journey(client, family, f'judgment-{family}')
        _seed_confirmed_facts(repository, journey, family, facts)
        result = journey.send('Does my policy cover this incident?')
        signals = repository.list_review_signals(journey.claim_id, 'cus_8f41a2c90d7e463b')
        signal = next(item for item in signals if item.code == 'POLICY_JUDGMENT_PROPOSAL')
        assert signal.judgment_point_kind == kind
        assert signal.source_refs == [
            result['claimant_message']['message_id'],
            f'claim:{journey.claim_id}:revision:{journey.revision}',
            agent.chunk['chunk_id'],
        ]
        assert signal.policy_sources[0].section_path == clause
        assert len(agent.gateway.requests) == 2

        replay = submit_message(
            client,
            CLAIMANT,
            journey.claim_id,
            journey.session_id,
            revision=1,
            key=f'judgment-{family}-1',
            client_message_id=f'judgment-{family}-1',
            text='Does my policy cover this incident?',
        )
        assert replay.status_code == 200, replay.text
        assert len(repository.list_review_signals(journey.claim_id, 'cus_8f41a2c90d7e463b')) == len(
            signals
        )
        assert len(agent.gateway.requests) == 2

        endpoint = f'/api/v1/workbench/claims/{journey.claim_id}/signals'
        projected = client.get(endpoint, headers=STAFF)
        assert projected.status_code == 200, projected.text
        visible = next(
            item for item in projected.json()['items'] if item['signal_id'] == signal.signal_id
        )
        assert visible['proposed_assessment'] == signal.proposed_assessment
        assert visible['proposal_rationale'] == signal.proposal_rationale
        assert agent.chunk in visible['source_evidence']
        assert client.get(endpoint, headers=CLAIMANT).status_code == 403
        before = repository.get_claim_internal(journey.claim_id)
        assert before is not None
        detail = client.get(f'/api/v1/workbench/claims/{journey.claim_id}', headers=STAFF)
        assert detail.status_code == 200, detail.text
        action = next(
            action
            for action in detail.json()['allowed_actions']
            if action['action_code'] == 'signal.record_decision'
            and action['target_ref'] == signal.signal_id
        )
        inputs = {item['field_code']: item for item in action['inputs']}
        assert decision_value in {item['value'] for item in inputs['decision']['choices']}
        decision = {
            **action['payload_defaults'],
            'decision': decision_value,
            'reason_codes': [inputs['reason_codes.0']['choices'][0]['value']],
            'summary': 'Policy advice reviewed by staff.',
        }
        denied = client.post(
            f'{endpoint}/{signal.signal_id}/decisions',
            headers={**CLAIMANT, 'Idempotency-Key': 'denied', 'If-Match': str(before.revision)},
            json=decision,
        )
        assert denied.status_code == 403
        accepted = client.post(
            f'{endpoint}/{signal.signal_id}/decisions',
            headers={
                **STAFF,
                'Idempotency-Key': 'staff-judgment',
                'If-Match': str(before.revision),
            },
            json=decision,
        )
        assert accepted.status_code == 201, accepted.text
        after = repository.get_claim_internal(journey.claim_id)
        assert after is not None
        assert after.claim_state.coverage == before.claim_state.coverage
        assert after.claim_state.fraud_signal == before.claim_state.fraud_signal
        assert after.claim_state.workflow_state == before.claim_state.workflow_state
        assert after.external_claim == before.external_claim
        assert after.form == before.form
        assert repository.list_review_signals(journey.claim_id, 'cus_8f41a2c90d7e463b') == signals
        assert len(repository.list_signal_decisions(journey.claim_id)) == 1
        assert (
            repository.list_signal_decisions(journey.claim_id)[0].decision.value == decision_value
        )
        claimant_detail = journey.view()
        history = client.get(
            f'/api/v1/claims/{journey.claim_id}/sessions/{journey.session_id}/messages',
            headers=CLAIMANT,
        )
        assert history.status_code == 200, history.text
        for secret in (signal.signal_id, signal.proposed_assessment, signal.proposal_rationale):
            assert secret not in str(result)
            assert secret not in str(claimant_detail)
            assert secret not in history.text


@pytest.mark.parametrize(
    ('failure', 'reason'),
    [
        ('missing_fact', 'required_facts_missing'),
        ('unretrieved_source', 'policy_evidence_not_authorized'),
        ('same_turn_handoff', 'suppressed_during_handoff'),
    ],
)
def test_invalid_policy_advice_does_not_persist_or_break_claimant_turn(
    failure: str, reason: str
) -> None:
    repository = FixtureRepository()
    provider = V8JourneyProvider([])
    provider.agent = GuidanceAgent(
        'liability_split',
        'MTR-COV-02',
        invalid_ref=failure == 'unretrieved_source',
        request_handoff=failure == 'same_turn_handoff',
    )
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        repository,
        provider,
    )
    with TestClient(app) as client:
        journey = Journey(client, 'motor', f'rejected-{failure}')
        facts: dict[str, Any] = {'incident.description': 'Another car hit my car.'}
        if failure != 'missing_fact':
            facts['parties.other_parties'] = True
        _seed_confirmed_facts(repository, journey, 'motor', facts)
        result = journey.send('Does my policy cover this incident?')
        assert not any(
            signal.code == 'POLICY_JUDGMENT_PROPOSAL'
            for signal in repository.list_review_signals(journey.claim_id, 'cus_8f41a2c90d7e463b')
        )
        records = repository.get_runtime_turn_for_trigger(
            journey.claim_id, result['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
        )
        assert records is not None
        assert records.proposal.policy_judgment_rejections == [
            {'kind': 'liability_split', 'reason': reason}
        ]
        assert records.proposal.policy_judgment_signal_refs == []
        if failure == 'same_turn_handoff':
            assert repository.list_handoffs(journey.claim_id, 'cus_8f41a2c90d7e463b')
        for claimant_projection in (result, journey.view()):
            assert reason not in str(claimant_projection)
            assert 'Internal advisory assessment' not in str(claimant_projection)
            assert 'Internal rationale' not in str(claimant_projection)


def test_active_support_handoff_suppresses_policy_advice_model_turn() -> None:
    repository = FixtureRepository()
    provider = V8JourneyProvider([])
    agent = GuidanceAgent('liability_split', 'MTR-COV-02')
    provider.agent = agent
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        repository,
        provider,
    )
    with TestClient(app) as client:
        journey = Journey(client, 'motor', 'judgment-handoff')
        _seed_confirmed_facts(
            repository,
            journey,
            'motor',
            {'parties.other_parties': True, 'incident.description': 'Another car hit my car.'},
        )
        requested = client.post(
            f'/api/v1/claims/{journey.claim_id}/support-requests',
            headers={**CLAIMANT, 'Idempotency-Key': 'judgment-handoff', 'If-Match': '1'},
            json={'reason': 'Please help me finish my report.', 'support_need': 'human_requested'},
        )
        assert requested.status_code == 201, requested.text
        stored = repository.get_claim_internal(journey.claim_id)
        assert stored is not None
        journey.revision = stored.revision
        journey.send('Does my policy cover this incident?', expect_agent_message=False)
        assert agent.gateway.requests == []
        assert repository.list_review_signals(journey.claim_id, 'cus_8f41a2c90d7e463b') == []
