from pathlib import Path

from scripts.check_agent_behaviour_catalogue import validate_catalogue


def test_agent_behaviour_catalogue_has_complete_target_routes() -> None:
    validate_catalogue(Path('docs/agent-behaviour-catalogue.md'))
