"""backend/core/dev_secrets.py -- the local-development team secrets integration point.

Only pure logic is tested here: the bundle-parsing and configured-name-derivation functions
never make a network call. fetch_dev_model_secrets' own HTTP call is exercised with a stubbed
transport instead of a real request, so this suite runs offline like the rest of the backend
tests and is wired into CI, unlike the old orphaned PowerShell-only credential test it replaces.
"""

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from backend.core.dev_secrets import (
    configured_model_credential_names,
    fetch_dev_model_secrets,
    parse_secrets_bundle,
    resolve_secrets_token,
)


def test_parse_secrets_bundle_reads_key_value_lines_and_ignores_the_rest() -> None:
    bundle = 'NORTHWIND_MODEL_API_KEY=abc123\n\n# a comment line\nGEMINI_API_KEY=def456\nnot a line'
    assert parse_secrets_bundle(bundle) == {
        'NORTHWIND_MODEL_API_KEY': 'abc123',
        'GEMINI_API_KEY': 'def456',
    }


def test_parse_secrets_bundle_returns_empty_dict_for_no_matching_lines() -> None:
    assert parse_secrets_bundle('') == {}
    assert parse_secrets_bundle('not a key=value line at all') == {}


def test_configured_model_credential_names_matches_the_current_bindings_file() -> None:
    # Independently re-reads the real config/model-runtime-bindings.json rather than trusting
    # the function's own file read, so a regression in either the function or the fixture data
    # would show up as a mismatch instead of both silently agreeing with themselves.
    bindings_path = Path(__file__).resolve().parents[1] / 'config' / 'model-runtime-bindings.json'
    bindings = json.loads(bindings_path.read_text(encoding='utf-8'))
    expected = sorted(
        {
            entry['credential_environment_variable']
            for entry in bindings
            if entry.get('credential_environment_variable')
        }
    )
    assert configured_model_credential_names() == expected
    # The real bindings file is expected to configure at least the OpenRouter credential;
    # an empty result here would mean the derivation silently broke, not that nobody has one.
    assert 'NORTHWIND_MODEL_API_KEY' in configured_model_credential_names()


def test_configured_model_credential_names_reads_an_explicit_path(tmp_path: Path) -> None:
    custom_bindings = tmp_path / 'bindings.json'
    custom_bindings.write_text(
        json.dumps(
            [
                {'profile_id': 'a', 'credential_environment_variable': 'FOO_KEY'},
                {'profile_id': 'b', 'credential_environment_variable': None},
                {'profile_id': 'c', 'credential_environment_variable': 'FOO_KEY'},
            ]
        ),
        encoding='utf-8',
    )
    assert configured_model_credential_names(custom_bindings) == ['FOO_KEY']


def test_fetch_dev_model_secrets_rejects_an_empty_token() -> None:
    with pytest.raises(ValueError, match='secrets token is required'):
        fetch_dev_model_secrets('')


def _fake_response(status_code: int, text: str) -> httpx.Response:
    # raise_for_status() needs a request on the response, which a bare httpx.Response()
    # constructed for a test does not have by default.
    return httpx.Response(
        status_code, text=text, request=httpx.Request('GET', 'https://example.test')
    )


def test_fetch_dev_model_secrets_parses_a_successful_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        captured['url'] = url
        captured['headers'] = headers
        return _fake_response(200, 'NORTHWIND_MODEL_API_KEY=fake-key\nGEMINI_API_KEY=fake-gemini\n')

    monkeypatch.setattr('backend.core.dev_secrets.httpx.get', fake_get)
    secrets = fetch_dev_model_secrets('a-real-looking-token')

    assert secrets == {'NORTHWIND_MODEL_API_KEY': 'fake-key', 'GEMINI_API_KEY': 'fake-gemini'}
    assert captured['headers'] == {'Authorization': 'Bearer a-real-looking-token'}


def test_fetch_dev_model_secrets_rejects_an_empty_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.core.dev_secrets.httpx.get',
        lambda url, *, headers, timeout: _fake_response(200, ''),
    )
    with pytest.raises(ValueError, match='no KEY=VALUE lines'):
        fetch_dev_model_secrets('a-real-looking-token')


def test_fetch_dev_model_secrets_raises_on_an_http_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        'backend.core.dev_secrets.httpx.get',
        lambda url, *, headers, timeout: _fake_response(401, 'unauthorized'),
    )
    with pytest.raises(httpx.HTTPStatusError):
        fetch_dev_model_secrets('a-wrong-token')


def test_resolve_secrets_token_prefers_the_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_SECRETS_TOKEN', 'env-token')

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError('gh should not be invoked when the env override is set')

    monkeypatch.setattr('backend.core.dev_secrets.subprocess.run', fail_if_called)
    assert resolve_secrets_token() == 'env-token'


def test_resolve_secrets_token_falls_back_to_gh_auth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NORTHWIND_SECRETS_TOKEN', raising=False)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ['gh', 'auth', 'token']
        return subprocess.CompletedProcess(args, 0, stdout='gh-token\n', stderr='')

    monkeypatch.setattr('backend.core.dev_secrets.subprocess.run', fake_run)
    assert resolve_secrets_token() == 'gh-token'


def test_resolve_secrets_token_raises_when_gh_auth_token_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NORTHWIND_SECRETS_TOKEN', raising=False)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout='', stderr='not logged in')

    monkeypatch.setattr('backend.core.dev_secrets.subprocess.run', fake_run)
    with pytest.raises(RuntimeError, match='gh auth login'):
        resolve_secrets_token()


def test_resolve_secrets_token_raises_when_gh_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NORTHWIND_SECRETS_TOKEN', raising=False)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError('gh not found')

    monkeypatch.setattr('backend.core.dev_secrets.subprocess.run', fake_run)
    with pytest.raises(RuntimeError, match='gh auth login'):
        resolve_secrets_token()
