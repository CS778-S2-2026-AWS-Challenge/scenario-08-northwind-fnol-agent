"""Serve the journey runtime in the state a poster screen shows, and photograph it.

    python -m tests.journey_runs.capture --list
    python -m tests.journey_runs.capture --screen claimant-claim-created --out DIR

The evidence pack's poster list names thirteen screens and the journey behind each (#960,
#964). For one screen this module builds the application the runners build, serves it, drives
the journey into the screen's state, checks that state through the API, and, with `--out`, has
`screenshot.py` photograph it only if the page renders that state too. Three constraints shape it:

- Failure-lifecycle states come from a scripted assessor adapter injected when the application is
  built, so the harness serves its own application object rather than attaching to a server.
- `engine.upload_pack` writes fixture bytes into that object's evidence storage directly, so the
  driving client holds the same object.
- The claimant application refuses the journeys' synthetic bearer at the account boundary, and an
  anonymous browser session cannot upload, so both sides act as the development identity
  adapter's synthetic account. Its short-lived credential goes to the browser and is not printed.

The runtime, runners, and engine are unchanged; the states come from the functions that write the
run records.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from sys import stderr
from typing import Any, Literal

import httpx
import uvicorn
from fastapi import FastAPI

from backend.adapters.claims_service import MockAssessorServiceAdapter
from backend.app import create_app
from backend.repositories.fixture import FixtureRepository
from backend.services.demo_seed import DEMO_CLAIMANT_EMAIL, DEMO_CLAIMANT_PASSWORD

from . import engine, screenshot
from .assessor_failures import FAILURE_CASES
from .engine import Journey, journey_settings
from .household import _drive as _household_drive
from .household import household_run_cases
from .motor_collision import (
    MOTOR_COLLISION_PACK,
    _drive_multi_turn,
    _drive_to_assessor_consent,
    _motor_input,
)

DEFAULT_PORT = 8000
APPLICATION_ORIGINS = {
    'claimant': 'http://127.0.0.1:5173',
    'workbench': 'http://127.0.0.1:5174/workbench/',
}
CLAIMANT_STORAGE_KEY = 'northwind.claimantToken'
WORKBENCH_STORAGE_KEY = 'northwind.workbench.session'
# FixtureStaffIdentityRepository's synthetic account (backend/adapters/staff_identity.py).
STAFF_EMAIL = 'staff.one@example.invalid'
STAFF_PASSWORD = 'northwind-demo-staff'
# The recorded AT-01 journey grants consent through its route and never shows the claimant a
# permission card; only the Agent's assessor offer does. This is the input that offer's tests
# use (tests/test_external_service_offers.py, ASSESSMENT_REQUEST).
ASSESSMENT_REQUEST = (
    "My car was rear-ended on Symonds Street. It's 8 o'clock in the morning now and "
    'the traffic is very heavy. Could you help me get a damage assessment for the repairs?'
)

State = dict[str, Any]
Step = tuple[str, Any]


class _StopAfter(Journey):
    """A journey that stops once a named step has run, to hold the state that step leaves.

    `Journey.step` already refuses to act once the journey has stopped, so a driver keeps its own
    sequence and the screen shows a state the recorded journey passes through, not a shorter
    journey written for the picture.
    """

    def __init__(self, client: Any, stop_after: str | None = None) -> None:
        super().__init__(client)
        self._stop_after = stop_after
        self._reached = False
        self.session_id: str | None = None

    @property
    def stopped(self) -> bool:
        return self._reached or super().stopped

    def create_working_claim(self, family: str | None) -> str | None:
        self.session_id = super().create_working_claim(family)
        return self.session_id

    def step(
        self, name: str, method: str, path: str, expected: int, actor: str, body: Any = None
    ) -> dict[str, Any] | None:
        result = super().step(name, method, path, expected, actor, body)
        if name == self._stop_after:
            self._reached = True
        return result


@dataclass(frozen=True)
class Screen:
    """One poster screen: where it is shown, how its state is reached, and how it is proved."""

    application: Literal['claimant', 'workbench']
    shows: str
    journey: str
    drive: Callable[[Journey], object]
    reached: Callable[[State], bool]
    marker: str
    open_steps: tuple[Step, ...] = ()
    section: str = ''
    adapter: Callable[[], MockAssessorServiceAdapter] = MockAssessorServiceAdapter
    stop_after: str | None = None


def _claimant_steps(family: str, *rest: Step) -> tuple[Step, ...]:
    """Open the claim from the claimant application's history, as a claimant would."""

    return (
        ('click', 'View conversation history'),
        ('wait', 1),
        ('click', f'Open {family} claim'),
        ('wait', 3),
        ('click', 'Close third-party services'),
        ('wait', 1),
        *rest,
    )


def _to_consent(journey: Journey) -> None:
    _drive_to_assessor_consent(journey, _motor_input('AT-01', 0), MOTOR_COLLISION_PACK)


def _route(journey: Journey, expected: int) -> None:
    claim = f'/api/v1/claims/{journey.claim_id}'
    journey.step('route the assessor', 'POST', f'{claim}/assessor-routing', expected, 'claimant')


def _assessment_offer(journey: Journey) -> None:
    session = journey.create_working_claim('motor')
    if session is not None:
        journey.say('request the assessor offer', session, ASSESSMENT_REQUEST)


def _pres01(journey: Journey) -> None:
    _drive_multi_turn(journey, _motor_input('PRES-01', 0), MOTOR_COLLISION_PACK)


def _routed(journey: Journey) -> None:
    _to_consent(journey)
    _route(journey, 201)


def _action(*statuses: str) -> Callable[[State], bool]:
    return lambda state: (state.get('external_service_action') or {}).get('status') in statuses


def _next_step(status: str) -> Callable[[State], bool]:
    return lambda state: (state.get('customer_next_step') or {}).get('status') == status


def _request(status: str) -> Callable[[State], bool]:
    return lambda state: status in {item['status'] for item in state.get('external_requests', [])}


def _allowed(code: str) -> Callable[[State], bool]:
    return lambda state: code in state.get('allowed_actions', [])


def _failure(
    case_id: str,
    application: Literal['claimant', 'workbench'],
    shows: str,
    reached: Callable[[State], bool],
    marker: str,
    open_steps: tuple[Step, ...],
    section: str = 'external-services',
) -> Screen:
    """A screen held at the moment one assessor failure case's routing has just failed."""

    case = FAILURE_CASES[case_id]

    def drive(journey: Journey) -> None:
        _to_consent(journey)
        _route(journey, case.route_status)

    return Screen(
        application, shows, case_id, drive, reached, marker, open_steps, section,
        case.adapter, 'route the assessor',
    )  # fmt: skip


_EXTERNAL = _claimant_steps('Motor', ('click', 'External services'), ('wait', 2))
_OPEN_REQUEST: Step = ('open', 'Vehicle Damage Assessment Routing')

SCREENS: dict[str, Screen] = {
    'claimant-assessor-permission': Screen(
        'claimant', 'external_service_action.status consent_required', 'the Agent assessor offer',
        _assessment_offer,
        lambda state: 'consent_required' in state.get('message_action_statuses', []),
        'Permission needed', _claimant_steps('Motor'),
    ),
    'claimant-request-routed': Screen(
        'claimant', 'the assessor request queued or assigned', 'AT-01 after routing', _routed,
        _action('queued', 'assigned'), 'Assessor assigned', _EXTERNAL,
    ),
    'claimant-retry-offered': _failure(
        'retryable-unavailable', 'claimant', 'retryable_failure with can_request true',
        lambda state: _action('retryable_failure')(state)
        and (state.get('external_service_action') or {}).get('can_request') is True,
        'Request did not complete', _EXTERNAL,
    ),
    'claimant-northwind-reviewing': _failure(
        'terminal-access-denied', 'claimant', 'terminal_failure',
        _action('terminal_failure'), 'Northwind review needed', _EXTERNAL,
    ),
    'claimant-outcome-not-confirmed': _failure(
        'unknown-outcome', 'claimant', 'awaiting_reconciliation',
        _action('awaiting_reconciliation'), 'Outcome not confirmed', _EXTERNAL,
    ),
    'claimant-claim-created': Screen(
        'claimant', 'the claim number and expected timeline', 'home water ingress',
        lambda journey: _household_drive(journey, household_run_cases('home')[0]),
        lambda state: bool(state.get('claim_number')), 'Claim {claim_number} created',
        _claimant_steps('Home', ('scroll', 'Claim {claim_number} created')),
    ),
    'claimant-more-information-needed': Screen(
        'claimant', 'intake stopped at contents.items', 'contents damaged item',
        lambda journey: _household_drive(journey, household_run_cases('contents')[0]),
        lambda state: 'contents.items'
        in ((state.get('customer_next_step') or {}).get('required_items') or []),
        'Tell me about one damaged', _claimant_steps('Contents'),
    ),
    'claimant-human-support-queued': Screen(
        'claimant', 'human_support_queued', 'PRES-01',
        _pres01,
        _next_step('human_support_queued'), 'Staff assistance active', _claimant_steps('Motor'),
    ),
    'workbench-queue-item': _failure(
        'unknown-outcome', 'workbench', 'the external wait and attention signals',
        _request('unknown_outcome'), 'Claim queue', (), section='queue',
    ),
    'workbench-external-service-records': _failure(
        'retryable-unavailable', 'workbench',
        'a lifecycle row with its pending owner and attention',
        _request('retryable_failure'), 'Connected participants',
        (_OPEN_REQUEST, ('scroll', 'Pending owner')),
    ),
    'workbench-accept-review': _failure(
        'terminal-access-denied', 'workbench', 'external.accept_review for a terminal failure',
        _allowed('external.accept_review'), 'Accept external-service review',
        (_OPEN_REQUEST, ('scroll', 'Accept external-service review')),
    ),
    'workbench-reconcile': _failure(
        'unknown-outcome', 'workbench', 'external.reconcile_response for an unknown outcome',
        _allowed('external.reconcile_response'), 'Reconcile external outcome',
        (_OPEN_REQUEST, ('scroll', 'Reconcile external outcome')),
    ),
    'workbench-missing-information': _failure(
        'terminal-access-denied', 'workbench', 'the responsible party for each missing item',
        lambda state: bool(state.get('missing_information')), 'Operational context',
        (('scroll', 'Operational context'),), section='',
    ),
}  # fmt: skip


def _serve(app: FastAPI, port: int) -> uvicorn.Server:
    """Serve the application on a background thread; uvicorn skips signals off the main thread."""

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(300):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError('the capture runtime did not start')


def _session(client: httpx.Client, route: str, email: str, password: str) -> dict[str, Any]:
    created = client.post(route, json={'email': email, 'password': password})
    if created.status_code != 201:
        raise RuntimeError(f'{route} refused the synthetic account: {created.text}')
    return dict(created.json())


def _claimant_state(client: httpx.Client, journey: _StopAfter, token: str) -> State:
    """The claimant projection a claimant screen renders."""

    headers = {'Authorization': f'Bearer {token}'}
    body = client.get(f'/api/v1/claims/{journey.claim_id}', headers=headers).json()
    messages: list[dict[str, Any]] = []
    if journey.session_id:
        messages = (
            client.get(
                f'/api/v1/claims/{journey.claim_id}/sessions/{journey.session_id}/messages?limit=100',
                headers=headers,
            )
            .json()
            .get('items')
            or []
        )
    action = body.get('external_service_action') or {}
    return {
        'workflow_state': body.get('workflow_state'),
        'claim_number': (body.get('external_claim') or {}).get('claim_number'),
        'customer_next_step': body.get('customer_next_step'),
        'external_service_action': {
            field: action.get(field)
            for field in ('status', 'status_label', 'pending_owner', 'next_action', 'can_request')
        }
        if action
        else None,
        'message_action_statuses': [
            item.get('status')
            for message in messages
            for item in message.get('message_actions') or []
        ],
    }  # fmt: skip


def _workbench_state(client: httpx.Client, claim_id: str, token: str) -> State:
    """The staff projection and external-request rows a Workbench screen renders."""

    headers = {'Authorization': f'Bearer {token}'}
    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=headers).json()
    requests = client.get(
        f'/api/v1/workbench/claims/{claim_id}/external-requests?limit=100', headers=headers
    ).json()
    work = detail.get('work_summary') or {}
    return {
        'queue_key': work.get('queue_key'),
        'allowed_actions': [
            item.get('action_code') for item in detail.get('allowed_actions') or []
        ],
        'external_requests': [
            {
                'status': (item.get('task') or {}).get('status'),
                'pending_owner': (item.get('lifecycle') or {}).get('pending_owner'),
                'needs_attention': (item.get('lifecycle') or {}).get('needs_attention'),
            }
            for item in requests.get('items') or []
        ],
        'missing_information': [
            {field: gap.get(field) for field in ('label', 'status', 'responsible_party')}
            for gap in work.get('missing_information') or []
        ],
    }  # fmt: skip


def _fill(value: Any, state: State) -> Any:
    """Put the run's own claim number into a marker or step that names it."""

    if isinstance(value, str) and '{claim_number}' in value:
        return value.replace('{claim_number}', str(state.get('claim_number') or ''))
    return value


def _url(screen: Screen, claim_id: str, override: str | None) -> str:
    base = (override or APPLICATION_ORIGINS[screen.application]).rstrip('/')
    if screen.application == 'claimant':
        return base
    if screen.section == 'queue':
        return f'{base}/'
    return f'{base}/claims/{claim_id}' + (f'/{screen.section}' if screen.section else '')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen', choices=sorted(SCREENS))
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--app', help='override the application origin; its Vite app must run')
    parser.add_argument('--out', type=Path, help='photograph the screen into DIR and exit')
    parser.add_argument('--list', action='store_true', help='print the screens and exit')
    arguments = parser.parse_args(argv)
    if arguments.list:
        for screen_id, screen in sorted(SCREENS.items()):
            print(f'{screen_id}\n  {screen.application}: {screen.shows}\n  from {screen.journey}')
        return 0
    if arguments.screen is None:
        parser.error('--screen is required unless --list is given')

    screen = SCREENS[arguments.screen]
    app = create_app(
        journey_settings(),
        repository=FixtureRepository(),
        assessor_service_adapter=screen.adapter(),
    )
    server = _serve(app, arguments.port)
    client = httpx.Client(base_url=f'http://127.0.0.1:{arguments.port}', timeout=60)
    client.app = app  # type: ignore[attr-defined]
    previous = engine.PRINCIPALS.get('claimant')
    try:
        token = _session(
            client, '/api/v1/auth/sessions', DEMO_CLAIMANT_EMAIL, DEMO_CLAIMANT_PASSWORD
        )
        engine.PRINCIPALS['claimant'] = {'Authorization': f'Bearer {token["access_token"]}'}
        journey = _StopAfter(client, screen.stop_after)
        screen.drive(journey)
        if not journey.claim_id:
            print(f'{arguments.screen}: the journey reached no claim', file=stderr)
            return 2
        store: dict[str, Any] = {CLAIMANT_STORAGE_KEY: token['access_token']}
        state = _claimant_state(client, journey, token['access_token'])
        if screen.application == 'workbench':
            staff = _session(client, '/api/v1/staff/auth/sessions', STAFF_EMAIL, STAFF_PASSWORD)
            store = {WORKBENCH_STORAGE_KEY: staff}
            state = _workbench_state(client, journey.claim_id, str(staff['access_token']))
        if not screen.reached(state):
            raise RuntimeError(
                f'{arguments.screen} did not reach the API state it claims to show: '
                f'{json.dumps(state, sort_keys=True)}'
            )
        image = None
        if arguments.out is not None:
            image = screenshot.capture(
                url=_url(screen, journey.claim_id, arguments.app),
                local_storage=store,
                open_steps=[(action, _fill(value, state)) for action, value in screen.open_steps],
                expected_text=_fill(screen.marker, state),
                destination=arguments.out / f'{arguments.screen}.png',
            )
        print(
            json.dumps(
                {
                    'screen': arguments.screen,
                    'application': screen.application,
                    'principal': f'synthetic {screen.application} account',
                    'shows': screen.shows,
                    'journey': screen.journey,
                    'head': engine.current_head(),
                    'claim_id': journey.claim_id,
                    'steps': len(journey.steps),
                    'refused_steps': [
                        step.name for step in journey.steps if step.outcome.value != 'succeeded'
                    ],
                    'api_state': state,
                    'image': str(image) if image else None,
                },
                indent=1,
            ),
            flush=True,
        )
        while arguments.out is None:
            time.sleep(5)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if previous is None:
            engine.PRINCIPALS.pop('claimant', None)
        else:
            engine.PRINCIPALS['claimant'] = previous
        client.close()
        server.should_exit = True


if __name__ == '__main__':
    raise SystemExit(main())
