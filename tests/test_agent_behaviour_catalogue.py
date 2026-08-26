from pathlib import Path

import pytest

from scripts.check_agent_behaviour_catalogue import CatalogueError, validate_catalogue

CATALOGUE_PATH = Path('docs/agent-behaviour-catalogue.md')


def _catalogue_copy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'agent-behaviour-catalogue.md'
    path.write_text(text, encoding='utf-8')
    return path


def test_agent_behaviour_catalogue_has_complete_target_behaviours() -> None:
    validate_catalogue(CATALOGUE_PATH)


def test_agent_behaviour_catalogue_rejects_missing_behaviour(tmp_path: Path) -> None:
    text = CATALOGUE_PATH.read_text(encoding='utf-8')
    start = text.index('### correction_confirmation')
    end = text.index('### urgent_interruption')
    path = _catalogue_copy(tmp_path, text[:start] + text[end:])

    with pytest.raises(CatalogueError, match='missing behaviours: correction_confirmation'):
        validate_catalogue(path)


def test_agent_behaviour_catalogue_rejects_empty_required_field(tmp_path: Path) -> None:
    text = CATALOGUE_PATH.read_text(encoding='utf-8')
    authority = (
        '- **Authority:** The claimant authorises corrections to claimant-controlled '
        'facts; deterministic field, conflict, and revision validation authorises the '
        'resulting Claim State revision.'
    )
    text = text.replace(
        authority,
        '- **Authority:**',
        1,
    )
    path = _catalogue_copy(tmp_path, text)

    with pytest.raises(
        CatalogueError,
        match='correction_confirmation missing or empty fields: Authority',
    ):
        validate_catalogue(path)


def test_agent_behaviour_catalogue_rejects_missing_cross_cutting_contract(
    tmp_path: Path,
) -> None:
    text = CATALOGUE_PATH.read_text(encoding='utf-8')
    text = '\n'.join(
        line for line in text.splitlines() if not line.startswith('| `unknown_command` |')
    )
    path = _catalogue_copy(tmp_path, text)

    with pytest.raises(
        CatalogueError,
        match='missing cross-cutting contracts: unknown_command',
    ):
        validate_catalogue(path)
