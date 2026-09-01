import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings

ADMIN_APP = Path(__file__).parents[1] / 'admin' / 'app.js'


def _console_collection_path() -> str:
    source = ADMIN_APP.read_text(encoding='utf-8')
    base_match = re.search(
        r"NORTHWIND_ADMIN_API_BASE \|\| '([^']+)'",
        source,
    )
    path_match = re.search(
        r"async function adminRequest\(path = '([^']+)'\)",
        source,
    )
    assert base_match is not None, 'The console must declare a default Admin API base URL.'
    assert path_match is not None, 'The console must declare its default collection path.'
    return f'{urlsplit(base_match.group(1)).path}{path_match.group(1)}'


def test_console_default_request_reaches_authenticated_admin_api() -> None:
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    with TestClient(create_app(settings)) as client:
        response = client.get(
            _console_collection_path(),
            headers={'Authorization': 'Bearer synthetic-admin'},
        )

    assert response.status_code == 200
    assert response.json() == {'items': [], 'page': {'next_cursor': None}}


def test_console_default_request_rejects_non_admin_principal() -> None:
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    with TestClient(create_app(settings)) as client:
        response = client.get(
            _console_collection_path(),
            headers={'Authorization': 'Bearer synthetic-staff'},
        )

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'


def test_console_synthetic_admin_is_rejected_outside_developer_mode() -> None:
    settings = Settings(environment='test', identity_mode=IdentityMode.NORMAL)
    with TestClient(create_app(settings)) as client:
        response = client.get(
            _console_collection_path(),
            headers={'Authorization': 'Bearer synthetic-admin'},
        )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'
