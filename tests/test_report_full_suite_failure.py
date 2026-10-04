import json
import shutil
import subprocess
from typing import Any

import pytest

from scripts import report_full_suite_failure as reporter


def _fake_api(
    monkeypatch: pytest.MonkeyPatch, open_issues: list[dict[str, Any]]
) -> list[tuple[str, str, Any]]:
    calls: list[tuple[str, str, Any]] = []

    def request(method: str, path: str, _token: str, payload: object | None = None) -> object:
        calls.append((method, path, payload))
        if method == 'GET':
            return open_issues
        return {'html_url': 'https://github.com/o/r/issues/9'}

    monkeypatch.setattr(reporter, '_request', request)
    return calls


def test_first_failure_opens_the_tracking_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_api(monkeypatch, [{'title': 'Unrelated', 'number': 1}])

    reporter.report('o/r', 't', commit='abc', build_url='https://ci/1', trigger='merge to main')

    method, path, payload = calls[-1]
    assert (method, path) == ('POST', '/repos/o/r/issues')
    assert payload['title'] == reporter.TITLE
    assert 'https://ci/1' in payload['body']


def test_later_failure_comments_on_the_open_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    open_issue = {
        'title': reporter.TITLE,
        'number': 7,
        'html_url': 'https://github.com/o/r/issues/7',
    }
    calls = _fake_api(monkeypatch, [open_issue])

    url = reporter.report(
        'o/r', 't', commit='def', build_url='https://ci/2', trigger='daily schedule'
    )

    assert url == open_issue['html_url']
    assert calls[-1][:2] == ('POST', '/repos/o/r/issues/7/comments')


@pytest.mark.skipif(shutil.which('node') is None, reason='node is required for the issue policy')
def test_issue_body_passes_the_repository_issue_policy() -> None:
    body = reporter.issue_body(commit='abc', build_url='https://ci/1', trigger='merge to main')
    script = (
        "const {validateIssueBody} = require('./.github/scripts/issue_policy.cjs');"
        'process.stdout.write(JSON.stringify(validateIssueBody({body: process.argv[1]}).errors));'
    )

    result = subprocess.run(
        ['node', '-e', script, body], check=True, capture_output=True, text=True
    )

    assert json.loads(result.stdout) == []
