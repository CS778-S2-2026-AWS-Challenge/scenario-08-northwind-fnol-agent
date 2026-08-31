"""Validate semantic dimensions in the legacy-to-target Agent action mapping."""

from __future__ import annotations

import re
import sys
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / 'docs'
    / 'design'
    / 'agent-runtime'
    / 'agent-runtime-migration.md'
)

EXPECTED_NAMESPACE_RULES = {
    'ASK': ({'conversation', 'runtime'}, {'conversation', 'runtime'}),
    'CLARIFY': ({'conversation', 'runtime'}, {'conversation', 'runtime'}),
    'CONFIRM': ({'conversation', 'runtime'}, {'conversation', 'runtime'}),
    'UPDATE': ({'conversation', 'runtime'}, {'conversation', 'runtime'}),
    'PROCEED': ({'runtime'}, {'runtime'}),
    'HANDOFF': ({'human', 'runtime'}, {'human', 'runtime'}),
    'URGENT_HANDOFF': ({'human', 'runtime'}, {'human', 'runtime'}),
    'CREATE_CLAIM': ({'claim', 'runtime'}, {'claim', 'runtime'}),
}

ACTION_PATTERN = re.compile(
    r'`(?P<namespace>conversation|claim|human|external|runtime)\.'
    r'(?P<action>[a-z][a-z0-9_]*)`'
)


class MappingError(ValueError):
    """Raised when the compatibility mapping changes an action dimension."""


def _mapping_rows(lines: list[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) != 3 or not cells[0].startswith('`'):
            continue
        compatibility_value = cells[0].strip('`')
        if compatibility_value not in EXPECTED_NAMESPACE_RULES:
            continue
        if compatibility_value in rows:
            raise MappingError(f'duplicate compatibility mapping: {compatibility_value}')
        rows[compatibility_value] = cells[1]
    return rows


def validate_mapping(path: Path = MIGRATION_PATH) -> None:
    rows = _mapping_rows(path.read_text(encoding='utf-8').splitlines())
    missing = [value for value in EXPECTED_NAMESPACE_RULES if value not in rows]
    if missing:
        raise MappingError(f'missing compatibility mappings: {", ".join(missing)}')

    for value, (required, allowed) in EXPECTED_NAMESPACE_RULES.items():
        namespaces = {match.group('namespace') for match in ACTION_PATTERN.finditer(rows[value])}
        missing_namespaces = required - namespaces
        if missing_namespaces:
            raise MappingError(
                f'{value} missing target namespaces: {", ".join(sorted(missing_namespaces))}'
            )
        disallowed_namespaces = namespaces - allowed
        if disallowed_namespaces:
            raise MappingError(
                f'{value} changes semantic dimension through: '
                f'{", ".join(sorted(disallowed_namespaces))}'
            )


def main() -> int:
    try:
        validate_mapping()
    except (OSError, MappingError) as error:
        print(f'Agent runtime mapping check failed: {error}', file=sys.stderr)
        return 1
    print(f'Agent runtime mapping check passed: {len(EXPECTED_NAMESPACE_RULES)} values.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
