"""Export or check the generated AuditEvent envelope JSON Schema snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_SNAPSHOT = Path('docs/contracts/audit-event.schema.json')


def current_schema() -> str:
    """Return the deterministic JSON Schema generated from the domain model."""

    from backend.domain.audit import AuditEventEnvelope

    return json.dumps(AuditEventEnvelope.model_json_schema(), indent=2, sort_keys=True) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help='compare against the committed snapshot instead of writing it',
    )
    parser.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args()

    schema = current_schema()
    if args.check:
        committed = args.snapshot.read_text(encoding='utf-8') if args.snapshot.exists() else None
        if committed != schema:
            print(
                'AuditEvent envelope shape changed; regenerate the snapshot and update '
                'docs/persistence-schema.md together '
                '(python scripts/export_audit_contract.py).',
                file=sys.stderr,
            )
            return 1
        print(f'AuditEvent envelope schema matches ({args.snapshot}).')
        return 0

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text(schema, encoding='utf-8')
    print(f'Wrote {args.snapshot}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
