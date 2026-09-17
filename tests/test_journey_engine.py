"""Focused evidence-integrity checks for the complete-journey HTTP recorder."""

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from journey_runs.engine import Journey
from journey_runs.record import RECORD_SCHEMA, JourneyRunRecord, StepOutcome


def _plain_app(status_code: int) -> FastAPI:
    app = FastAPI()

    async def plain_response() -> PlainTextResponse:
        return PlainTextResponse('not json', status_code=status_code)

    app.add_api_route(
        '/plain',
        plain_response,
        methods=['GET'],
    )
    return app


def test_an_expected_non_json_http_failure_is_recorded_without_a_decode_crash() -> None:
    """A provider-side 500 remains observable even when it has no JSON envelope."""

    with TestClient(_plain_app(500), raise_server_exceptions=False) as client:
        journey = Journey(client)
        payload = journey.step('observe failure', 'GET', '/plain', 500, 'claimant')

    assert payload == {}
    assert journey.steps[0].http_status == 500
    assert journey.steps[0].response_body_valid is False
    assert journey.steps[0].outcome is StepOutcome.SUCCEEDED
    assert journey.steps[0].detail == 'HTTP 500 returned a non-JSON response.'


def test_a_non_json_success_response_cannot_be_recorded_as_successful_evidence() -> None:
    """A 2xx response must still satisfy the route's documented JSON contract."""

    with TestClient(_plain_app(200)) as client:
        journey = Journey(client)
        payload = journey.step('read JSON resource', 'GET', '/plain', 200, 'claimant')

    assert payload is None
    assert journey.steps[0].http_status == 200
    assert journey.steps[0].response_body_valid is False
    assert journey.steps[0].outcome is StepOutcome.FAILED
    assert journey.steps[0].detail == 'HTTP 200 returned a non-JSON response.'


def test_response_body_validity_has_a_new_record_schema_revision() -> None:
    """Serialized response-validity evidence is declared as a breaking schema revision."""

    assert RECORD_SCHEMA == 'northwind-journey-run/5'
    assert JourneyRunRecord.model_fields['record_schema'].default == RECORD_SCHEMA
