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
from backend.repositories.scenario_loader import CANONICAL_SCENARIO_DIRECTORY, load_scenarios
from backend.services.evidence_fixtures import EvidenceFixtureService

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


def test_the_path_table_separates_scenario_state_from_fixture_claims() -> None:
    """Defect 1 is open, so the two must not be presented as one thing.

    Review found the first draft showing the path-entry fixture's evidence
    state as if it described the business path, while the same document
    recorded that those entries are not anchored to their scenarios. AT-01
    holds no evidence but the table said `received`, `1 of 1`.
    """
    text = DOCUMENT.read_text(encoding='utf-8')

    assert 'Canonical scenario holds' in text
    assert 'Path entry declares' in text
    assert 'should read the left pair' in text

    scenarios = {item.scenario_id: item for item in load_scenarios(CANONICAL_SCENARIO_DIRECTORY)}
    for entry in EvidenceFixtureService().path_entries():
        scenario = scenarios[entry.scenario_id]
        held = len(scenario.evidence)
        declared = len(entry.evidence)
        # Whichever way round they are, the document must state both numbers.
        assert f'{held} records' in text or f'{held} record' in text
        assert f'{declared} records' in text or f'{declared} record' in text


def test_the_document_does_not_claim_persistence_and_agent_lack_a_seam() -> None:
    """They are injectable; readiness simply has nothing to ask them.

    `create_app()` takes both and defaults them to `FixtureRepository` and
    `ControlledAgent`, so calling them unreplaceable was wrong.
    """
    import inspect

    from backend.app import create_app

    parameters = inspect.signature(create_app).parameters
    assert 'repository' in parameters
    assert 'agent_turn_provider' in parameters

    # Collapse wrapping so the assertion is about the claim, not the layout.
    text = ' '.join(DOCUMENT.read_text(encoding='utf-8').split())
    assert 'reporting gap, not a missing seam' in text
    assert 'no replaceable seam' not in text
    assert 'have no adapter seam' not in text
