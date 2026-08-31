"""Export the FastAPI OpenAPI schema for snapshot comparison.

Writes the schema as sorted, indented JSON to the snapshot path. With
--check, compares the current schema against the committed snapshot and
exits non-zero on drift. The snapshot is a mechanical sentinel only;
docs/api.md remains the human-readable API authority.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_SNAPSHOT = Path('docs/openapi.snapshot.json')


def current_schema() -> str:
    from backend.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n'


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
                'API shape changed; update the snapshot and docs/api.md together '
                '(python scripts/export_openapi.py).',
                file=sys.stderr,
            )
            return 1
        print(f'OpenAPI snapshot matches ({args.snapshot}).')
        return 0

    args.snapshot.write_text(schema, encoding='utf-8')
    print(f'Wrote {args.snapshot}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
