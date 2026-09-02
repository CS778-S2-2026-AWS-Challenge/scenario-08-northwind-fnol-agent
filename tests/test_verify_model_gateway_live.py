from types import SimpleNamespace

import pytest

from backend.core.config import AgentRuntimeProfile
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelResponse,
)
from scripts import verify_model_gateway_live


def _settings(*, profile: str = 'model_gateway') -> SimpleNamespace:
    return SimpleNamespace(
        agent_runtime_profile=(
            AgentRuntimeProfile.MODEL_GATEWAY
            if profile == 'model_gateway'
            else AgentRuntimeProfile.CONTROLLED
        ),
        model_purpose='agent_turn',
        model_prompt_version='prompt-v1',
        model_privacy_class='synthetic_fnol',
        model_profile_id='profile-1',
        model_protocol_adapter='openai_compatible',
        model_provider='synthetic-provider',
    )


def test_live_verifier_requires_model_gateway_profile(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_model_gateway_live.Settings,  # type: ignore[attr-defined]
        'from_environment',
        classmethod(lambda _cls: _settings(profile='controlled')),
    )

    assert verify_model_gateway_live.main() == 2
    assert capsys.readouterr().out == (
        'status=live_call_not_run reason=MODEL_GATEWAY_PROFILE_REQUIRED\n'
    )


def test_live_verifier_projects_gateway_errors_without_traceback(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_model_gateway_live.Settings,  # type: ignore[attr-defined]
        'from_environment',
        classmethod(lambda _cls: _settings()),
    )
    monkeypatch.setattr(
        verify_model_gateway_live,
        'build_model_gateway',
        lambda _settings: (_ for _ in ()).throw(
            ModelGatewayError(ModelGatewayErrorCode.AUTHENTICATION)
        ),
    )

    assert verify_model_gateway_live.main() == 1
    assert capsys.readouterr().out == (
        'status=live_call_failed code=authentication retryable=false\n'
    )


def test_live_verifier_rejects_non_complete_response_without_provider_details(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_model_gateway_live.Settings,  # type: ignore[attr-defined]
        'from_environment',
        classmethod(lambda _cls: _settings()),
    )

    class Gateway:
        capabilities = ModelCapabilities(structured_output=True)

        def complete(self, _request: object) -> ModelResponse:
            return ModelResponse(completion_status=ModelCompletionStatus.INCOMPLETE)

    monkeypatch.setattr(
        verify_model_gateway_live,
        'build_model_gateway',
        lambda _settings: Gateway(),
    )

    assert verify_model_gateway_live.main() == 1
    assert capsys.readouterr().out == (
        'status=live_call_failed code=incomplete_response retryable=false\n'
    )


@pytest.mark.parametrize(
    'structured_output',
    [
        {},
        {'action': 'claim.review'},
        {'response': 'Please review the claim.'},
        {'action': ' ', 'response': 'Please review the claim.'},
        {'action': 'claim.review', 'response': 7},
        {
            'action': 'claim.review',
            'response': 'Please review the claim.',
            'unexpected': True,
        },
    ],
)
def test_live_verifier_rejects_invalid_structured_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    structured_output: dict[str, object],
) -> None:
    monkeypatch.setattr(
        verify_model_gateway_live.Settings,  # type: ignore[attr-defined]
        'from_environment',
        classmethod(lambda _cls: _settings()),
    )

    class Gateway:
        capabilities = ModelCapabilities(structured_output=True)

        def complete(self, _request: object) -> ModelResponse:
            return ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output=structured_output,
            )

    monkeypatch.setattr(
        verify_model_gateway_live,
        'build_model_gateway',
        lambda _settings: Gateway(),
    )

    assert verify_model_gateway_live.main() == 1
    assert capsys.readouterr().out == (
        'status=live_call_failed code=malformed_response retryable=false\n'
    )


def test_live_verifier_accepts_strict_structured_output(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verify_model_gateway_live.Settings,  # type: ignore[attr-defined]
        'from_environment',
        classmethod(lambda _cls: _settings()),
    )

    class Gateway:
        capabilities = ModelCapabilities(structured_output=True)

        def complete(self, _request: object) -> ModelResponse:
            return ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    'action': 'claim.review',
                    'response': 'Please review the claim.',
                },
            )

    monkeypatch.setattr(
        verify_model_gateway_live,
        'build_model_gateway',
        lambda _settings: Gateway(),
    )

    assert verify_model_gateway_live.main() == 0
    assert 'status":"live_call_succeeded"' in capsys.readouterr().out
