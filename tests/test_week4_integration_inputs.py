"""Keep the Week 4 integration inputs true to the runtime.

Issue #150 requires every integration point to name its provider, consumer, and
current status. A hand-written table drifts the moment an adapter changes, so
the two facts most likely to drift are asserted against the running application
rather than trusted.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings

DOCUMENT = Path(__file__).resolve().parents[1] / 'docs' / 'week4-integration-inputs.md'


def readiness_checks() -> dict[str, str]:
    with TestClient(create_app(Settings())) as client:
        response = client.get('/health/ready')
    assert response.status_code == 200
    checks: dict[str, str] = response.json()['checks']
    return checks


def test_every_readiness_check_appears_in_the_document() -> None:
    """A new adapter must be added to the Week 4 inputs, not left out of them."""
    text = DOCUMENT.read_text(encoding='utf-8')

    for name in readiness_checks():
        assert name in text, f'{name} is missing from {DOCUMENT.name}'


def test_the_document_does_not_claim_a_confirmed_aws_capability() -> None:
    """Acceptance: incomplete work stays visible and is not marked Ready."""
    checks = readiness_checks()
    aws = {name: status for name, status in checks.items() if name.startswith('aws_')}

    assert aws, 'the readiness endpoint no longer reports any AWS capability'
    assert set(aws.values()) == {'pending_confirmation'}

    text = DOCUMENT.read_text(encoding='utf-8')
    assert 'No AWS capability is confirmed' in text
    assert 'pending_confirmation' in text
