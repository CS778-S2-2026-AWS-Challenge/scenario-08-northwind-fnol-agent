from pathlib import Path

import pytest

from scripts.check_agent_runtime_mapping import MappingError, validate_mapping

MIGRATION_PATH = Path('docs/design/agent-runtime/agent-runtime-migration.md')


def _mapping_copy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / 'agent-runtime-migration.md'
    path.write_text(text, encoding='utf-8')
    return path


def test_agent_runtime_mapping_preserves_action_dimensions() -> None:
    validate_mapping(MIGRATION_PATH)


def test_agent_runtime_mapping_rejects_missing_compatibility_value(
    tmp_path: Path,
) -> None:
    text = MIGRATION_PATH.read_text(encoding='utf-8')
    text = '\n'.join(line for line in text.splitlines() if not line.startswith('| `PROCEED` |'))

    with pytest.raises(MappingError, match='missing compatibility mappings: PROCEED'):
        validate_mapping(_mapping_copy(tmp_path, text))


def test_agent_runtime_mapping_rejects_update_claim_side_effect(
    tmp_path: Path,
) -> None:
    text = MIGRATION_PATH.read_text(encoding='utf-8')
    text = text.replace(
        '`conversation.answer`, `conversation.explain`, or `conversation.summarise`, '
        'plus `runtime.continue` or `runtime.wait_for_user`',
        '`conversation.answer`, `claim.propose_fact_patch`, plus `runtime.continue`',
        1,
    )

    with pytest.raises(
        MappingError,
        match='UPDATE changes semantic dimension through: claim',
    ):
        validate_mapping(_mapping_copy(tmp_path, text))
