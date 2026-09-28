"""CLI wrapper scripts/start-dev.ps1 calls to fetch dev model credentials.

The fetch and parse logic itself lives in backend/core/dev_secrets.py, a config-layer
integration point alongside config/model-runtime-bindings.json; this script only reads
the bootstrap token from the environment, calls that function, and prints the result as
JSON on stdout so the PowerShell launcher can consume it without owning any of this logic.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.dev_secrets import configured_model_credential_names, fetch_dev_model_secrets


def main() -> int:
    token = os.environ.get('NORTHWIND_SECRETS_TOKEN', '')
    if not token:
        print(
            'NORTHWIND_SECRETS_TOKEN is not set. Ask a teammate for the dev secrets token and '
            'set it once for your user: [Environment]::SetEnvironmentVariable('
            '"NORTHWIND_SECRETS_TOKEN", "<token>", "User"), then open a new terminal.',
            file=sys.stderr,
        )
        return 1
    try:
        secrets = fetch_dev_model_secrets(token)
    except Exception as error:  # surfaced to the developer as a plain message
        print(str(error), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                'secrets': secrets,
                'configured_credential_names': configured_model_credential_names(),
            }
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
