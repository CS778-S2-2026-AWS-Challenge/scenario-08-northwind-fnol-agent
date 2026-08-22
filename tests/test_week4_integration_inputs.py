"""Keep the Week 4 integration inputs aligned with current runtime facts.

Issue #150 is a status/compatibility deliverable. The most dangerous failure is
therefore not a syntax error but stale prose that silently becomes false as the
runtime or canonical fixtures change. These checks derive the high-value facts
from the application and EvidenceFixtureService rather than trusting the table.
"""

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.services.evidence_fixtures import EvidenceFixtureService

DOCUMENT = Path(__file__).resolve().parents[1] / 'docs' / 'week4-integration-inputs.md'


def readiness_checks() -> dict[str, str]:
    with TestClient(create_app(Settings())) as client:
        response = client.get('/health/ready')
    assert response.status_code == 200
    checks: dict[str, str] = response.json()['checks']
    return checks


def test_every_runtime_readiness_status_is_recorded_exactly() -> None:
    """A changed/added readiness key must update the Week 4 source of truth."""
    text = DOCUMENT.read_text(encoding='utf-8')

    for name, status in readiness_checks().items():
        row = f'| `{name}` | `{status}` |'
        assert row in text, f'{row} is missing from {DOCUMENT.name}'


def test_no_aws_capability_is_presented_as_confirmed() -> None:
    """Fixture-backed behaviour must never be promoted into an AWS claim."""
    checks = readiness_checks()
    aws = {name: status for name, status in checks.items() if name.startswith('aws_')}

    assert aws, 'the readiness endpoint no longer exposes AWS confirmation state'
    assert set(aws.values()) == {'pending_confirmation'}

    text = DOCUMENT.read_text(encoding='utf-8')
    assert 'No AWS capability is confirmed' in text
    assert 'Draft / NOT READY' in text
    assert 'pending_confirmation' in text


def test_five_path_table_is_derived_from_canonical_evidence_service() -> None:
    """Path compatibility must describe the records the runtime actually owns."""
    text = DOCUMENT.read_text(encoding='utf-8')
    paths = EvidenceFixtureService().all_paths()

    assert len(paths) == 5
    for path in paths:
        summary = path.evidence_summary
        row = (
            f'| `{path.business_path.value}` | `{path.scenario_id}` | '
            f'`{path.evidence_state.value}` | {len(path.records)} | '
            f'{len(path.claimant_visible_records)} | {summary.received} | '
            f'{summary.pending} | {summary.needs_attention} |'
        )
        assert row in text, f'canonical path row drifted: {row}'


def test_persistence_and_agent_are_documented_as_seams_not_missing_boundaries() -> None:
    """Readiness status must not be confused with whether injection exists."""
    parameters = inspect.signature(create_app).parameters
    assert 'repository' in parameters
    assert 'agent_turn_provider' in parameters

    text = ' '.join(DOCUMENT.read_text(encoding='utf-8').split())
    assert 'not a missing software seam' in text
    assert '`PersistenceRepository`' in text
    assert '`AgentTurnProvider`' in text


def test_known_incomplete_inputs_remain_explicitly_visible() -> None:
    """The compilation must not turn open delivery work into implied readiness."""
    text = DOCUMENT.read_text(encoding='utf-8')

    for token in ('#200', '#224', '#225', '#230', '#231'):
        assert token in text
    assert 'MongoDB runtime' in text
    assert 'Production Agent/model' in text
    assert 'Final #150 Ready gate' in text
