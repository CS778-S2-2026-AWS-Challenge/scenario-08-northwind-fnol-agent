import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.agent_action_registry import (
    ActionIdempotencyPolicy,
    ActionStateEffect,
    ActionVisibility,
    action_contract,
)
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from backend.domain.models import (
    AgentAction,
    AuthorityOutcome,
    BranchEvaluationResult,
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    ResponsibleParty,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, validate_proposal
from backend.services.agent_tools import (
    read_evidence_history_for_runtime,
    validate_evidence_proposal,
)
from backend.services.messages import (
    _execute_evidence_history_search,
    _validate_evidence_history_action,
    _validate_tool_requests,
)


class EvidenceHistoryGateway:
    """Return the same Evidence proposal before and after Runtime history lookup."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.required_tool_name:
            return ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                tool_calls=[
                    ModelToolCall(
                        call_id=f'call-claim-read-{len(self.requests)}',
                        name='claim.read',
                        arguments={},
                    )
                ],
                provider_model='qwen3.8-27b',
                provider_request_id=f'provider-{len(self.requests)}',
            )
        history_loaded = len(self.requests) == 4
        return ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={
                'action_code': 'claim.propose_evidence_reuse',
                'runtime_action_code': 'runtime.wait_for_user',
                'reason_codes': ['EVIDENCE_REUSE_AVAILABLE'],
                'customer_reason': (
                    'An eligible prior Evidence item is available.'
                    if history_loaded
                    else 'Authorised Evidence history is required before selecting an item.'
                ),
                'customer_response': (
                    'I found your prior damage photo. Confirm if you want the original '
                    'Evidence linked to this Claim without copying the file.'
                    if history_loaded
                    else 'I will check your authorised Evidence history first.'
                ),
                'customer_next_step': {
                    'status': 'confirm_evidence_reuse',
                    'summary': 'Confirm whether the prior Evidence should be reused.',
                    'responsible_party': 'claimant',
                    'required_items': ['evidence_reuse_confirmation'],
                },
                'form_changes': [],
                'contents_item_changes': [],
                'source_refs': ['evd_ready'] if history_loaded else [],
                'evidence_id': 'evd_ready' if history_loaded else None,
                'source_claim_id': 'clm_source' if history_loaded else None,
            },
            provider_model='qwen3.8-27b',
            provider_request_id=f'provider-{len(self.requests)}',
        )


def _claim(claim_id: str = 'clm_target', customer_id: str = 'cus_owner') -> WorkingClaim:
    now = datetime.now(UTC)
    return WorkingClaim(
        claim_id=claim_id,
        customer_id=customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )


def _evidence(
    evidence_id: str,
    claim_id: str,
    *,
    status: EvidenceStatus = EvidenceStatus.RECEIVED,
    file_status: EvidenceFileStatus = EvidenceFileStatus.READY,
    source: EvidenceSource = EvidenceSource.CLAIMANT,
) -> EvidenceRecord:
    now = datetime.now(UTC)
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='incident_image',
        status=status,
        file_status=file_status,
        original_filename=f'{evidence_id}.jpg',
        media_type='image/jpeg',
        size_bytes=10,
        source=source,
        created_at=now,
        updated_at=now,
    )


def _proposal(
    claim: WorkingClaim,
    *,
    action_code: str = 'conversation.answer',
    evidence_id: str | None = None,
    source_claim_id: str | None = None,
    removal_scope: str | None = None,
    required_tools: list[dict[str, object]] | None = None,
    tool_results: list[dict[str, object]] | None = None,
) -> AgentProposal:
    return AgentProposal(
        action=AgentAction.UPDATE,
        action_code=action_code,
        reason_codes=['EVIDENCE_HISTORY_REQUESTED'],
        customer_reason='Evidence history was checked.',
        customer_response='I checked your Evidence history.',
        customer_next_step=claim.customer_next_step,
        form_changes=[],
        state_changes=[],
        proposed_signals=[],
        required_tools=required_tools or [],
        next_action_requirements=[],
        tool_results=tool_results or [],
        evidence_id=evidence_id,
        source_claim_id=source_claim_id,
        removal_scope=removal_scope,
    )


def test_history_tool_is_bounded_to_authenticated_claimant_records() -> None:
    repository = FixtureRepository()
    target = _claim()
    other = _claim('clm_other', 'cus_other')
    repository._claims[target.claim_id] = target
    repository._claims[other.claim_id] = other
    repository.save_evidence(_evidence('evd_ready', target.claim_id), target.customer_id)
    repository.save_evidence(
        _evidence('evd_processing', target.claim_id, file_status=EvidenceFileStatus.PROCESSING),
        target.customer_id,
    )
    repository.save_evidence(_evidence('evd_other', other.claim_id), other.customer_id)
    repository.save_evidence(
        _evidence('evd_external', target.claim_id, source=EvidenceSource.EXTERNAL_SYSTEM),
        target.customer_id,
    )

    result = read_evidence_history_for_runtime(repository, target, {})

    assert result['tool'] == 'evidence.history'
    assert result['status'] == 'succeeded'
    items = cast(list[dict[str, object]], result['items'])
    source_refs = cast(list[str], result['source_refs'])
    assert {item['evidence_id'] for item in items} == {
        'evd_ready',
        'evd_processing',
    }
    assert set(source_refs) == {'evd_ready', 'evd_processing'}
    assert all('storage_key' not in item for item in items)
    assert all(item['can_remove'] is False for item in items)


@pytest.mark.parametrize('limit', [0, 51, True])
def test_history_tool_rejects_provider_selected_scope_and_bad_limit(limit: object) -> None:
    repository = FixtureRepository()
    target = _claim()

    with pytest.raises(ValueError, match='does not accept'):
        read_evidence_history_for_runtime(repository, target, {'customer_id': target.customer_id})
    with pytest.raises(ValueError, match='between 1 and 50'):
        read_evidence_history_for_runtime(repository, target, {'limit': limit})


def test_history_tool_rejects_invalid_repository_and_argument_container() -> None:
    target = _claim()

    with pytest.raises(TypeError, match='claimant-scoped'):
        read_evidence_history_for_runtime(object(), target, {})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match='mapping'):
        read_evidence_history_for_runtime(FixtureRepository(), target, [])  # type: ignore[arg-type]


def test_evidence_proposal_contracts_are_proposal_only_and_execution_confirmation_bound() -> None:
    reuse = action_contract('claim.propose_evidence_reuse')
    remove = action_contract('claim.propose_evidence_remove')

    assert reuse.state_effect is ActionStateEffect.CLAIM_PROPOSAL
    assert reuse.side_effect_class.value == 'none'
    assert reuse.idempotency_policy is ActionIdempotencyPolicy.NOT_REQUIRED
    assert reuse.requires_confirmation is False
    assert reuse.visibility == (ActionVisibility.CLAIMANT,)
    assert any('explicit confirmation' in item for item in reuse.response_obligations)
    assert [field.name for field in reuse.input_schema.fields] == [
        'claim_id',
        'evidence_id',
        'source_claim_id',
    ]
    assert remove.requires_confirmation is False
    assert remove.permitted_tools == ('evidence.history',)
    assert [field.name for field in remove.input_schema.fields] == [
        'claim_id',
        'evidence_id',
        'removal_scope',
    ]


def test_reuse_proposal_requires_owned_ready_evidence_and_requests_confirmation() -> None:
    repository = FixtureRepository()
    source = _claim('clm_source')
    target = _claim('clm_target')
    repository._claims[source.claim_id] = source
    repository._claims[target.claim_id] = target
    repository.save_evidence(_evidence('evd_ready', source.claim_id), source.customer_id)

    proposed = validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_reuse',
        evidence_id='evd_ready',
        source_claim_id=source.claim_id,
    )
    assert proposed['status'] == 'proposed'
    assert proposed['reason'] == 'CLAIMANT_CONFIRMATION_REQUIRED_BEFORE_EVIDENCE_API_ATTACH'
    assert proposed['target_claim_id'] == target.claim_id
    assert proposed['source_claim_id'] == source.claim_id


def test_reuse_and_remove_fail_closed_for_ineligible_or_unavailable_paths() -> None:
    repository = FixtureRepository()
    target = _claim()
    repository._claims[target.claim_id] = target
    repository.save_evidence(
        _evidence('evd_processing', target.claim_id, file_status=EvidenceFileStatus.PROCESSING),
        target.customer_id,
    )

    rejected = validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_reuse',
        evidence_id='evd_processing',
        source_claim_id=target.claim_id,
    )
    assert rejected == {'status': 'rejected', 'reason': 'EVIDENCE_NOT_REUSABLE'}

    unavailable = validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_remove',
        evidence_id='evd_processing',
        removal_scope='persisted',
    )
    assert unavailable['status'] == 'unavailable'
    assert unavailable['reason'] == 'PERSISTED_REMOVE_HANDLER_UNAVAILABLE'
    assert unavailable['can_remove'] is False


def test_evidence_proposals_reject_invalid_identity_source_and_scope() -> None:
    repository = FixtureRepository()
    target = _claim()
    other = _claim('clm_other', 'cus_other')
    repository._claims[target.claim_id] = target
    repository._claims[other.claim_id] = other
    repository.save_evidence(_evidence('evd_ready', target.claim_id), target.customer_id)
    repository.save_evidence(_evidence('evd_other', other.claim_id), other.customer_id)
    repository.save_evidence(
        _evidence('evd_external', target.claim_id, source=EvidenceSource.EXTERNAL_SYSTEM),
        target.customer_id,
    )

    with pytest.raises(ValueError, match='Unsupported Evidence proposal'):
        validate_evidence_proposal(
            repository,
            target,
            action_code='claim.unknown',
            evidence_id='evd_ready',
        )
    assert validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_reuse',
        evidence_id='',
    ) == {'status': 'rejected', 'reason': 'EVIDENCE_ID_REQUIRED'}
    for denied_id in ('evd_other', 'evd_external'):
        assert validate_evidence_proposal(
            repository,
            target,
            action_code='claim.propose_evidence_reuse',
            evidence_id=denied_id,
            source_claim_id=target.claim_id,
        ) == {'status': 'rejected', 'reason': 'EVIDENCE_SCOPE_DENIED'}
    assert validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_reuse',
        evidence_id='evd_ready',
        source_claim_id='clm_wrong',
    ) == {'status': 'rejected', 'reason': 'SOURCE_CLAIM_MISMATCH'}
    assert validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_remove',
        evidence_id='evd_ready',
    ) == {'status': 'rejected', 'reason': 'REMOVAL_SCOPE_REQUIRED'}
    assert validate_evidence_proposal(
        repository,
        target,
        action_code='claim.propose_evidence_remove',
        evidence_id='evd_ready',
        removal_scope='draft',
    ) == {
        'status': 'unavailable',
        'reason': 'DRAFT_REMOVAL_IS_FRONTEND_OWNED',
        'evidence_id': 'evd_ready',
    }


def test_runtime_requires_successful_history_before_accepting_evidence_proposal() -> None:
    repository = FixtureRepository()
    source = _claim('clm_source')
    target = _claim()
    repository._claims[source.claim_id] = source
    repository._claims[target.claim_id] = target
    repository.save_evidence(_evidence('evd_ready', source.claim_id), source.customer_id)
    reuse = _proposal(
        target,
        action_code='claim.propose_evidence_reuse',
        evidence_id='evd_ready',
        source_claim_id=source.claim_id,
    )

    assert _validate_evidence_history_action(repository, target, _proposal(target)) == _proposal(
        target
    )
    with pytest.raises(ApiError) as missing:
        _validate_evidence_history_action(repository, target, reuse)
    assert missing.value.code == 'AGENT_TOOL_NOT_PERMITTED'

    with pytest.raises(ApiError) as rejected:
        _validate_evidence_history_action(
            repository,
            target,
            _proposal(
                target,
                action_code='claim.propose_evidence_reuse',
                evidence_id='evd_missing',
                source_claim_id=source.claim_id,
                tool_results=[
                    {
                        'tool': 'evidence.history',
                        'status': 'succeeded',
                        'items': [{'evidence_id': 'evd_missing'}],
                    }
                ],
            ),
        )
    assert rejected.value.code == 'VALIDATION_ERROR'

    with pytest.raises(ApiError) as outside_result:
        _validate_evidence_history_action(
            repository,
            target,
            _proposal(
                target,
                action_code='claim.propose_evidence_reuse',
                evidence_id='evd_ready',
                source_claim_id=source.claim_id,
                tool_results=[{'tool': 'evidence.history', 'status': 'succeeded', 'items': []}],
            ),
        )
    assert outside_result.value.code == 'VALIDATION_ERROR'

    checked = _validate_evidence_history_action(
        repository,
        target,
        _proposal(
            target,
            action_code='claim.propose_evidence_reuse',
            evidence_id='evd_ready',
            source_claim_id=source.claim_id,
            tool_results=[
                {
                    'tool': 'evidence.history',
                    'status': 'succeeded',
                    'items': [{'evidence_id': 'evd_ready'}],
                }
            ],
        ),
    )
    assert checked.action_code == 'claim.propose_evidence_reuse'
    assert validate_proposal(checked).outcome is AuthorityOutcome.AUTHORISED


@pytest.mark.parametrize(
    ('scope', 'expected_response'),
    [
        ('draft', 'Select the draft file in the upload composer'),
        ('persisted', 'cannot remove the persisted record'),
    ],
)
def test_runtime_reports_unavailable_removal_without_claiming_success(
    scope: str,
    expected_response: str,
) -> None:
    repository = FixtureRepository()
    target = _claim()
    repository._claims[target.claim_id] = target
    repository.save_evidence(_evidence('evd_ready', target.claim_id), target.customer_id)

    result = _validate_evidence_history_action(
        repository,
        target,
        _proposal(
            target,
            action_code='claim.propose_evidence_remove',
            evidence_id='evd_ready',
            removal_scope=scope,
            tool_results=[
                {
                    'tool': 'evidence.history',
                    'status': 'succeeded',
                    'items': [{'evidence_id': 'evd_ready'}],
                }
            ],
        ),
    )

    assert expected_response in result.customer_response
    assert 'removed' not in result.customer_response


def test_evidence_history_tool_request_validation_and_execution() -> None:
    repository = FixtureRepository()
    target = _claim()
    repository._claims[target.claim_id] = target
    repository.save_evidence(_evidence('evd_ready', target.claim_id), target.customer_id)
    branch = cast(
        BranchEvaluationResult,
        SimpleNamespace(permitted_tools=['evidence.history']),
    )
    valid = _proposal(
        target,
        required_tools=[{'tool': 'evidence.history', 'operation': 'list', 'limit': 1}],
    )

    _validate_tool_requests(valid, branch)
    outcome = _execute_evidence_history_search(repository, target, valid)
    assert outcome is not None
    assert outcome[1]['source_refs'] == ['evd_ready']
    assert _execute_evidence_history_search(repository, target, _proposal(target)) is None

    invalid_requests: list[dict[str, object]] = [
        {'tool': 'evidence.history', 'operation': 'list', 'customer_id': target.customer_id},
        {'tool': 'evidence.history', 'operation': 'list', 'limit': 0},
    ]
    for request in invalid_requests:
        with pytest.raises(ApiError) as invalid:
            _validate_tool_requests(
                _proposal(target, required_tools=[request]),
                branch,
            )
        assert invalid.value.code == 'AGENT_TOOL_NOT_PERMITTED'

    assert (
        _execute_evidence_history_search(
            repository,
            target,
            _proposal(
                target,
                required_tools=[{'tool': 'evidence.history', 'operation': 'list', 'limit': False}],
            ),
        )
        is None
    )


def test_model_runtime_queries_history_then_proposes_reuse_without_mutating_evidence() -> None:
    gateway = EvidenceHistoryGateway()
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', lambda _config: gateway)
    repository = FixtureRepository()
    source = _claim('clm_source', 'cus_demo')
    repository._claims[source.claim_id] = source
    original = _evidence('evd_ready', source.claim_id)
    repository.save_evidence(original, source.customer_id)
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='openai_compatible',
        model_profile_id='qwen-local',
        model_base_url='http://model.example.test/v1',
        model_identifier='qwen3.8-27b',
        model_supports_tools=True,
    )

    with TestClient(
        create_app(
            settings,
            repository=repository,
            model_gateway_registry=registry,
        )
    ) as client:
        headers = {'Authorization': 'Bearer synthetic-claimant'}
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': 'evidence-history-claim'},
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': 'motor',
                'model_profile_id': 'qwen-local',
            },
        )
        assert created.status_code == 201, created.text
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']

        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': 'evidence-history-turn',
                'If-Match': '1',
            },
            json={
                'client_message_id': 'evidence-history-message',
                'content': {
                    'type': 'text',
                    'text': 'Can I reuse the damage photo from my earlier claim?',
                },
                'evidence_refs': [],
            },
        )

        assert response.status_code == 200, response.text
        assert 'Confirm if you want' in response.json()['agent_message']['content']['text']
        assert len(gateway.requests) == 4
        replanned_context = json.loads(gateway.requests[2].messages[-1].content or '{}')
        history_result = next(
            result
            for result in replanned_context['tool_results']
            if result['tool'] == 'evidence.history'
        )
        assert [item['evidence_id'] for item in history_result['items']] == ['evd_ready']
        assert all('storage_key' not in item for item in history_result['items'])

        runtime_turn = repository.get_runtime_turn_for_trigger(
            claim_id,
            response.json()['claimant_message']['message_id'],
            'cus_demo',
        )
        assert runtime_turn is not None
        assert runtime_turn.proposal.action_code == 'claim.propose_evidence_reuse'
        assert {result.tool_name for result in runtime_turn.tool_results} == {
            'claim.read',
            'evidence.history',
        }
        persisted_history = next(
            result for result in runtime_turn.tool_results if result.tool_name == 'evidence.history'
        )
        assert persisted_history.source_refs == ['evd_ready']
        assert persisted_history.status == 'succeeded'

    assert repository.get_evidence(source.claim_id, original.evidence_id, 'cus_demo') == original
    assert repository.list_evidence_for_customer('cus_demo') == [original]
