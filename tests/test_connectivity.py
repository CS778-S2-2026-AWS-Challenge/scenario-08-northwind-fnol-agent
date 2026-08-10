import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


FIXTURE = Path(__file__).parent / "fixtures" / "connectivity-message.json"


class ConnectivitySmokeTest(unittest.TestCase):
    """Temporary smoke coverage for the existing frontend-backend shell."""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint_responds(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_message_endpoint_accepts_fixture(self):
        request_body = json.loads(FIXTURE.read_text(encoding="utf-8"))

        response = self.client.post("/api/claims/message", json=request_body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["received_message"], request_body["message"])


if __name__ == "__main__":
    unittest.main()
