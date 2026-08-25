"""Validate the required structure of the FNOL Agent behaviour catalogue."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'agent-behaviour-catalogue.md'

REQUIRED_ROUTES = (
    'ordinary_intake',
    'multi_intent_intake',
    'explicit_command',
    'human_support',
    'urgent_interruption',
    'status_query',
    'resume',
    'pending_evidence',
    'policy_or_history_lookup',
    'evidence_assistance',
    'claim_creation',
    'staff_agent_assistance',
    'unknown_or_unsafe_intent',
)

REQUIRED_FIELDS = (
    'FNOL problem',
    'Trigger / intent',
    'Input context',
    'Output',
    'Target actions',
    'Permitted actions',
    'Prohibited actions',
    'Claim State effect',
    'Failure behaviour',
    'Visibility',
    'Proof',
    'Delivery level',
)


class CatalogueError(ValueError):
    """Raised when the catalogue is missing a required route or field."""


def _sections(lines: list[str]) -> dict[str, list[str]]:
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r'### ([a-z0-9_]+)', line.strip())
        if match:
            headings.append((match.group(1), index))

    sections: dict[str, list[str]] = {}
    for position, (route, start) in enumerate(headings):
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        if route in sections:
            raise CatalogueError(f'duplicate behaviour heading: {route}')
        sections[route] = lines[start + 1 : end]
    return sections


def validate_catalogue(path: Path = CATALOGUE_PATH) -> None:
    lines = path.read_text(encoding='utf-8').splitlines()
    sections = _sections(lines)
    missing_routes = [route for route in REQUIRED_ROUTES if route not in sections]
    if missing_routes:
        raise CatalogueError(f'missing behaviour routes: {", ".join(missing_routes)}')

    for route in REQUIRED_ROUTES:
        section = '\n'.join(sections[route])
        missing_fields = [field for field in REQUIRED_FIELDS if f'- **{field}:**' not in section]
        if missing_fields:
            raise CatalogueError(f'{route} missing fields: {", ".join(missing_fields)}')
        if not re.search(r'`(?:conversation|claim|human|external|runtime)\.[^`]+`', section):
            raise CatalogueError(f'{route} has no namespaced target action')

    catalogue = '\n'.join(lines)
    if 'ASK / HANDOFF / CREATE_CLAIM' in catalogue:
        raise CatalogueError('catalogue must not define the legacy eight-action baseline')


def main() -> int:
    try:
        validate_catalogue()
    except (OSError, CatalogueError) as error:
        print(f'Agent behaviour catalogue check failed: {error}', file=sys.stderr)
        return 1
    print(f'Agent behaviour catalogue check passed: {len(REQUIRED_ROUTES)} routes.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
