from pathlib import Path

from fastapi.testclient import TestClient

from backend.demo import create_demo_app


def _write_frontends(root: Path) -> tuple[Path, Path]:
    claimant = root / 'claimant'
    employee = root / 'employee'
    (claimant / 'assets').mkdir(parents=True)
    employee.mkdir()
    (claimant / 'index.html').write_text('claimant application', encoding='utf-8')
    (claimant / 'assets' / 'app.js').write_text('console.log("claimant")', encoding='utf-8')
    (employee / 'index.html').write_text('employee application', encoding='utf-8')
    return claimant, employee


def test_demo_app_serves_both_frontends_and_spa_fallbacks(tmp_path: Path) -> None:
    claimant, employee = _write_frontends(tmp_path)
    client = TestClient(create_demo_app(claimant, employee))

    assert client.get('/').text == 'claimant application'
    assert client.get('/claim/deep-link').text == 'claimant application'
    assert client.get('/assets/app.js').text == 'console.log("claimant")'
    assert client.get('/employee/').text == 'employee application'
    assert client.get('/employee/claim/deep-link').text == 'employee application'


def test_demo_app_keeps_api_routes_ahead_of_static_fallback(tmp_path: Path) -> None:
    claimant, employee = _write_frontends(tmp_path)
    client = TestClient(create_demo_app(claimant, employee))

    assert client.get('/api/health').json() == {'status': 'ok'}
    assert client.get('/health/live').json() == {'status': 'ok'}
    assert client.get('/api/not-a-route').status_code == 404
