"""Exercise a configured model gateway with synthetic FNOL context.

This command intentionally performs a real provider call. It must only be run with an
explicitly authorised, budgeted environment and synthetic data. No credential or full model
response is printed.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from backend.core.config import AgentRuntimeProfile, Settings
from backend.core.model_gateway import build_model_gateway
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelEvidenceContent,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ModelTextContent,
)

_PDF_EVIDENCE_ID = 'evd_live_synthetic_pdf'


class LiveVerificationOutput(BaseModel):
    """Strict structured result required for a successful live verification."""

    model_config = ConfigDict(extra='forbid')

    action: str
    response: str

    @field_validator('action', 'response')
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('value must not be blank')
        return value


class LivePdfVerificationOutput(BaseModel):
    """Strict result proving that the provider consumed the synthetic PDF."""

    model_config = ConfigDict(extra='forbid')

    document_type: str
    synthetic_marker_confirmed: bool

    @field_validator('document_type')
    @classmethod
    def require_document_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('document_type must not be blank')
        return value


class _SinglePdfResolver:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def resolve(self, evidence_id: str, media_type: str) -> bytes | None:
        if evidence_id != _PDF_EVIDENCE_ID or media_type != 'application/pdf':
            return None
        return self._content


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--pdf',
        type=Path,
        help='Synthetic PDF used to verify document input; no file content is printed.',
    )
    return parser.parse_args(argv)


def _pdf_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    if path.suffix.lower() != '.pdf' or not content.startswith(b'%PDF-'):
        raise ValueError('The verification document must be a readable PDF.')
    return content


def main(argv: Sequence[str] = ()) -> int:
    try:
        arguments = _arguments(argv)
        settings = Settings.from_environment()
        if settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
            print('status=live_call_not_run reason=MODEL_GATEWAY_PROFILE_REQUIRED')
            return 2

        pdf_content = _pdf_bytes(arguments.pdf) if arguments.pdf is not None else None
        if pdf_content is None:
            gateway = build_model_gateway(settings)
            request = ModelRequest(
                purpose=settings.model_purpose,
                prompt_version=settings.model_prompt_version,
                privacy_class=settings.model_privacy_class,
                required_capabilities=ModelCapabilities(structured_output=True),
                messages=[
                    ModelMessage(
                        role=ModelRole.SYSTEM,
                        content=(
                            'You are a Northwind FNOL proposal generator. Return a JSON object '
                            'with an action and a short customer-safe response. Use only the '
                            'synthetic incident supplied by the user.'
                        ),
                    ),
                    ModelMessage(
                        role=ModelRole.USER,
                        content=json.dumps(
                            {
                                'incident_type': 'motor',
                                'incident_description': (
                                    'Synthetic rear-end collision; no injury reported.'
                                ),
                                'urgency': 'normal',
                            },
                            separators=(',', ':'),
                        ),
                    ),
                ],
                response_schema={
                    'type': 'object',
                    'properties': {
                        'action': {'type': 'string'},
                        'response': {'type': 'string'},
                    },
                    'required': ['action', 'response'],
                    'additionalProperties': False,
                },
            )
            output_adapter: type[BaseModel] = LiveVerificationOutput
            verification_mode = 'structured_text'
        else:
            gateway = build_model_gateway(
                settings,
                evidence_resolver=_SinglePdfResolver(pdf_content),
            )
            request = ModelRequest(
                purpose=settings.model_purpose,
                prompt_version=settings.model_prompt_version,
                privacy_class=settings.model_privacy_class,
                required_capabilities=ModelCapabilities(
                    structured_output=True,
                    document_input=True,
                ),
                messages=[
                    ModelMessage(
                        role=ModelRole.SYSTEM,
                        content=(
                            'Read only the attached synthetic PDF. Return the requested JSON. '
                            'Do not infer from the filename.'
                        ),
                    ),
                    ModelMessage(
                        role=ModelRole.USER,
                        content_blocks=[
                            ModelTextContent(
                                text=(
                                    'Identify the document type and confirm whether the document '
                                    'explicitly says it is simulated.'
                                )
                            ),
                            ModelEvidenceContent(
                                evidence_id=_PDF_EVIDENCE_ID,
                                media_type='application/pdf',
                            ),
                        ],
                    ),
                ],
                response_schema={
                    'type': 'object',
                    'properties': {
                        'document_type': {'type': 'string'},
                        'synthetic_marker_confirmed': {'type': 'boolean'},
                    },
                    'required': ['document_type', 'synthetic_marker_confirmed'],
                    'additionalProperties': False,
                },
            )
            output_adapter = LivePdfVerificationOutput
            verification_mode = 'pdf_document'
        response = gateway.complete(request)
    except ModelGatewayError as error:
        retryable = str(error.retryable).lower()
        print(f'status=live_call_failed code={error.code.value} retryable={retryable}')
        return 1
    except (OSError, ValueError):
        print('status=live_call_failed code=configuration retryable=false')
        return 1
    if response.completion_status is not ModelCompletionStatus.COMPLETE:
        print(
            f'status=live_call_failed code={response.completion_status.value}_response '
            'retryable=false'
        )
        return 1
    if response.structured_output is None:
        print('status=live_call_failed code=malformed_response retryable=false')
        return 1
    try:
        parsed = output_adapter.model_validate(response.structured_output)
    except ValidationError:
        print('status=live_call_failed code=malformed_response retryable=false')
        return 1
    if isinstance(parsed, LivePdfVerificationOutput) and not parsed.synthetic_marker_confirmed:
        print('status=live_call_failed code=pdf_content_not_verified retryable=false')
        return 1
    print(
        json.dumps(
            {
                'status': 'live_call_succeeded',
                'verification_mode': verification_mode,
                'profile_id': settings.model_profile_id,
                'protocol': settings.model_protocol_adapter,
                'provider': settings.model_provider,
                'model': response.provider_model,
                'request_id_present': bool(response.provider_request_id),
                'usage': response.usage.model_dump(mode='json') if response.usage else None,
                'capabilities': gateway.capabilities.model_dump(mode='json'),
            },
            separators=(',', ':'),
        )
    )
    return 0


if __name__ == '__main__':
    import sys

    raise SystemExit(main(sys.argv[1:]))
