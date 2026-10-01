"""Replay-stable identities keep the v1 digests persisted by P17 and retention records."""

from hashlib import sha256

import pytest

from backend.domain.ids import stable_digest, stable_operation_id, stable_record_id
from backend.domain.retention import (
    retention_delete_authorization_id,
    retention_record_identity,
    retention_step_evidence_id,
    retention_tombstone_id,
)


def test_factory_reproduces_the_v1_digest_coordinates() -> None:
    material = 'clm_1|fup_1|v1|1'

    assert (
        stable_operation_id('fuo', material) == f'fuo_{sha256(material.encode()).hexdigest()[:24]}'
    )
    assert stable_record_id('rtg', material) == f'rtg_{sha256(material.encode()).hexdigest()[:32]}'
    assert stable_digest(material, 20) == sha256(material.encode()).hexdigest()[:20]
    # Retention identities are unchanged by routing them through the factory.
    assert retention_step_evidence_id('ret_1', 'rtg_1', 2) == (
        'rse_' + sha256(b'ret_1|rtg_1|2').hexdigest()[:32]
    )
    assert retention_delete_authorization_id('ret_1', 'rtg_1', 2) == (
        'rda_' + sha256(b'ret_1|rtg_1|2|delete-authorization').hexdigest()[:32]
    )
    assert retention_record_identity('idempotency', 'cus_1', '/route', 'key') == (
        'idempotency_' + sha256(b'idempotency|cus_1|/route|key').hexdigest()[:32]
    )


@pytest.mark.parametrize('length', [15, 65])
def test_digest_length_outside_the_supported_range_fails_closed(length: int) -> None:
    with pytest.raises(ValueError, match='16 to 64'):
        stable_digest('material', length)


def test_tombstone_identity_shares_its_target_digest_and_fails_closed() -> None:
    assert retention_tombstone_id('rtg_abc123') == 'rts_abc123'

    with pytest.raises(ValueError, match='rtg_'):
        retention_tombstone_id('evd_abc123')
