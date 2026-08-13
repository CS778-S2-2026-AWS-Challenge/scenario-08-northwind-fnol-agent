from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from backend.app import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEMO_MEDIA_TYPES = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
}
DEMO_STATIC_HEADERS = {'Cache-Control': 'no-store'}


def _required_directory(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_dir():
        raise RuntimeError(
            f'{description} was not found at {resolved}. Build the demo assets first.'
        )
    return resolved


def _frontend_response(root: Path, requested_path: str) -> FileResponse:
    candidate = (root / requested_path).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(
            candidate,
            media_type=DEMO_MEDIA_TYPES.get(candidate.suffix.lower()),
            headers=DEMO_STATIC_HEADERS,
        )
    return FileResponse(root / 'index.html', headers=DEMO_STATIC_HEADERS)


def create_demo_app(
    claimant_build: Path | None = None,
    employee_build: Path | None = None,
) -> FastAPI:
    """Create the temporary, single-origin presentation application."""
    claimant_root = _required_directory(
        claimant_build or REPOSITORY_ROOT / 'customer' / 'dist',
        'Claimant production build',
    )
    employee_root = _required_directory(
        employee_build or REPOSITORY_ROOT / 'employee',
        'Employee workbench build',
    )
    if not (claimant_root / 'index.html').is_file():
        raise RuntimeError(f'Claimant entry point was not found at {claimant_root / "index.html"}.')
    if not (employee_root / 'index.html').is_file():
        raise RuntimeError(f'Employee entry point was not found at {employee_root / "index.html"}.')

    app = create_app()

    @app.get('/api/health', include_in_schema=False)
    def demo_health() -> dict[str, str]:
        return {'status': 'ok'}

    @app.api_route('/api/{path:path}', methods=['GET', 'HEAD'], include_in_schema=False)
    def unknown_api_path(path: str) -> None:
        raise HTTPException(status_code=404, detail=f'API route /api/{path} was not found.')

    @app.get('/employee', include_in_schema=False)
    @app.get('/employee/{path:path}', include_in_schema=False)
    def employee_frontend(path: str = '') -> FileResponse:
        return _frontend_response(employee_root, path or 'index.html')

    @app.get('/', include_in_schema=False)
    @app.get('/{path:path}', include_in_schema=False)
    def claimant_frontend(path: str = '') -> FileResponse:
        return _frontend_response(claimant_root, path or 'index.html')

    return app
