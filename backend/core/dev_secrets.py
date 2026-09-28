"""Local-development integration point for the team secrets endpoint on Cloudflare.

This is the one place that fetches model credentials for a developer running the app
locally through scripts/start-dev.ps1 -- the launcher calls scripts/fetch_secrets.py,
which calls the functions here; it does not own or duplicate this logic itself. Not used
by the deployed backend at runtime: production and CI/test environments inject model
credentials through their own approved secret mechanism, never through this endpoint.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

TEAM_SECRETS_ENDPOINT = 'https://ysoseri.us/secret/northwind-dev'
_BINDINGS_PATH = Path(__file__).resolve().parents[2] / 'config' / 'model-runtime-bindings.json'
_KEY_VALUE_LINE = re.compile(r'^([A-Z][A-Z0-9_]*)=(.*)$')


def configured_model_credential_names(bindings_path: Path = _BINDINGS_PATH) -> list[str]:
    """Every credential_environment_variable name the shared model bindings configure.

    The single source of truth for "which environment variable names carry a model
    credential and must never reach a claimant/staff/admin frontend process" -- derived
    from the bindings file itself, so a new or changed binding's credential name is
    picked up automatically instead of depending on a hand-maintained list elsewhere
    that can silently drift.
    """
    bindings = json.loads(bindings_path.read_text(encoding='utf-8'))
    names = {
        entry['credential_environment_variable']
        for entry in bindings
        if entry.get('credential_environment_variable')
    }
    return sorted(names)


def parse_secrets_bundle(bundle_text: str) -> dict[str, str]:
    """Parse the endpoint's KEY=VALUE-per-line response body into a dict."""
    values: dict[str, str] = {}
    for line in bundle_text.splitlines():
        match = _KEY_VALUE_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def fetch_dev_model_secrets(token: str) -> dict[str, str]:
    """Fetch and parse the current model-credential bundle from the team secrets endpoint.

    Raises ValueError if the token is empty or the endpoint returns no usable lines --
    the caller (scripts/fetch_secrets.py) turns either into a clear message for the
    developer instead of a bare stack trace.
    """
    if not token:
        raise ValueError('A secrets token is required.')
    response = httpx.get(
        TEAM_SECRETS_ENDPOINT,
        headers={'Authorization': f'Bearer {token}'},
        timeout=15.0,
    )
    response.raise_for_status()
    secrets = parse_secrets_bundle(response.text)
    if not secrets:
        raise ValueError(
            'The secrets endpoint returned no KEY=VALUE lines; the token may be wrong or revoked.'
        )
    return secrets
