from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.config import AgentRuntimeProfile
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelEvidenceContent,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
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


def test_live_verifier_accepts_synthetic_pdf_document_input(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / 'synthetic.pdf'
    pdf_path.write_bytes(b'%PDF-1.4 synthetic verification')
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        verify_model_gateway_live.Settings,  # type: ignore[attr-defined]
        'from_environment',
        classmethod(lambda _cls: _settings()),
    )

    class Gateway:
        capabilities = ModelCapabilities(structured_output=True, document_input=True)

        def complete(self, request: ModelRequest) -> ModelResponse:
            observed['request'] = request
            return ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    'document_type': 'synthetic receipt',
                    'synthetic_marker_confirmed': True,
                },
            )

    def build_gateway(
        _settings: object,
        registry: object = None,
        evidence_resolver: object = None,
    ) -> Gateway:
        observed['resolver'] = evidence_resolver
        return Gateway()

    monkeypatch.setattr(verify_model_gateway_live, 'build_model_gateway', build_gateway)

    assert verify_model_gateway_live.main(['--pdf', str(pdf_path)]) == 0
    output = capsys.readouterr().out
    assert '"verification_mode":"pdf_document"' in output
    request = observed['request']
    assert isinstance(request, ModelRequest)
    assert request.required_capabilities.document_input is True
    evidence_blocks = [
        block
        for block in request.messages[1].content_blocks
        if isinstance(block, ModelEvidenceContent)
    ]
    assert evidence_blocks == [
        ModelEvidenceContent(
            evidence_id='evd_live_synthetic_pdf',
            media_type='application/pdf',
        )
    ]
    resolver = observed['resolver']
    assert isinstance(resolver, verify_model_gateway_live._SinglePdfResolver)
    assert resolver.resolve('evd_live_synthetic_pdf', 'application/pdf') == pdf_path.read_bytes()
