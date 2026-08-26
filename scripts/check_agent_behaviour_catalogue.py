"""Validate the required structure of the FNOL Agent behaviour catalogue."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / 'docs' / 'agent-behaviour-catalogue.md'

REQUIRED_BEHAVIOURS = (
    'ordinary_intake',
    'multi_intent_intake',
    'explicit_command',
    'correction_confirmation',
    'human_support',
    'urgent_interruption',
    'status_query',
    'resume',
    'pending_evidence',
    'policy_or_history_lookup',
    'evidence_assistance',
    'professional_review_handoff',
    'claim_creation',
    'staff_agent_assistance',
    'unknown_or_unsafe_intent',
)

REQUIRED_CROSS_CUTTING_CONTRACTS = (
    'unknown_command',
    'provider_tool_failure',
)

REQUIRED_FIELDS = (
    'FNOL problem',
    'Trigger / intent',
    'Input context',
    'Output',
    'Target actions',
    'Authority',
    'Tool allow-list',
    'Permitted actions',
    'Prohibited actions',
    'Claim State effect',
    'Failure behaviour',
    'Visibility',
    'Claimant-visible response',
    'Handoff condition',
    'Proof',
    'Delivery level',
)

TARGET_ACTION_PATTERN = re.compile(
    r'`(?:conversation|claim|human|external|runtime)\.[a-z][a-z0-9_]*`'
)


class CatalogueError(ValueError):
    """Raised when the catalogue is missing a required behaviour or contract."""


def _sections(lines: list[str]) -> dict[str, list[str]]:
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r'### ([a-z0-9_]+)', line.strip())
        if match:
            headings.append((match.group(1), index))

    sections: dict[str, list[str]] = {}
    for position, (behaviour, start) in enumerate(headings):
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        if behaviour in sections:
            raise CatalogueError(f'duplicate behaviour heading: {behaviour}')
        sections[behaviour] = lines[start + 1 : end]
    return sections


def _field_value(section: list[str], field: str) -> str | None:
    prefix = f'- **{field}:**'
    for line in section:
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _cross_cutting_contracts(lines: list[str]) -> dict[str, list[str]]:
    try:
        start = lines.index('## Cross-Cutting Contracts')
    except ValueError as error:
        raise CatalogueError('missing Cross-Cutting Contracts section') from error

    table_rows: dict[str, list[str]] = {}
    for line in lines[start + 1 :]:
        if line.startswith('## '):
            break
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) != 6 or not cells[0].startswith('`'):
            continue
        contract = cells[0].strip('`')
        if contract in table_rows:
            raise CatalogueError(f'duplicate cross-cutting contract: {contract}')
        table_rows[contract] = cells
    return table_rows


def validate_catalogue(path: Path = CATALOGUE_PATH) -> None:
    lines = path.read_text(encoding='utf-8').splitlines()
    sections = _sections(lines)
    missing_behaviours = [
        behaviour for behaviour in REQUIRED_BEHAVIOURS if behaviour not in sections
    ]
    if missing_behaviours:
        raise CatalogueError(f'missing behaviours: {", ".join(missing_behaviours)}')

    for behaviour in REQUIRED_BEHAVIOURS:
        section_lines = sections[behaviour]
        missing_fields = [
            field for field in REQUIRED_FIELDS if not _field_value(section_lines, field)
        ]
        if missing_fields:
            raise CatalogueError(
                f'{behaviour} missing or empty fields: {", ".join(missing_fields)}'
            )
        target_actions = _field_value(section_lines, 'Target actions')
        if target_actions is None or not TARGET_ACTION_PATTERN.search(target_actions):
            raise CatalogueError(f'{behaviour} Target actions has no valid namespaced action')

    contracts = _cross_cutting_contracts(lines)
    missing_contracts = [
        contract for contract in REQUIRED_CROSS_CUTTING_CONTRACTS if contract not in contracts
    ]
    if missing_contracts:
        raise CatalogueError(f'missing cross-cutting contracts: {", ".join(missing_contracts)}')
    for contract in REQUIRED_CROSS_CUTTING_CONTRACTS:
        if any(not cell for cell in contracts[contract]):
            raise CatalogueError(f'{contract} has an empty table cell')

    catalogue = '\n'.join(lines)
    if 'ASK / HANDOFF / CREATE_CLAIM' in catalogue:
        raise CatalogueError('catalogue must not define the legacy eight-action baseline')


def main() -> int:
    try:
        validate_catalogue()
    except (OSError, CatalogueError) as error:
        print(f'Agent behaviour catalogue check failed: {error}', file=sys.stderr)
        return 1
    print(
        'Agent behaviour catalogue check passed: '
        f'{len(REQUIRED_BEHAVIOURS)} behaviours and '
        f'{len(REQUIRED_CROSS_CUTTING_CONTRACTS)} cross-cutting contracts.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
