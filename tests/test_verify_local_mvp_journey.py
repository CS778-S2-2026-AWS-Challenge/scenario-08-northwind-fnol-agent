from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository
from scripts.verify_local_mvp_journey import verify_local_mvp_journey


def test_journey_reuses_one_claim_across_app_restart_and_staff_projection() -> None:
    repository = FixtureRepository()

    result = verify_local_mvp_journey(lambda: create_app(Settings(), repository=repository))

    assert result.claim_id
    assert result.claimant_read is True
    assert result.staff_read is True
    assert result.restart_verified is True
    assert result.persistence_status == 'using_fixture'
    assert result.evidence_storage_status == 'using_fixture'
    assert repository.claim_count == 1
