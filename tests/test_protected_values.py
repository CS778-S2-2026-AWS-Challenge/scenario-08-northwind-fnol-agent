import base64
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from pydantic import ValidationError

from backend.domain.account_data import (
    CreatePaymentDestinationRequest,
    IdentityDocumentRecord,
    IdentityDocumentType,
    PolicyNumberRecord,
    UpdateIdentityDocumentRequest,
    UpdatePaymentDestinationRequest,
    UpdatePolicyNumberRequest,
)
from backend.services.protected_values import (
    FernetProtectedValueAdapter,
    ProtectedValueError,
    UnavailableProtectedValueAdapter,
    masked_value,
    protected_value_adapter_for,
)


def _key(seed: bytes = b'protected-value-test') -> bytes:
    return base64.urlsafe_b64encode(sha256(seed).digest())


def test_fernet_adapter_round_trips_without_exposing_plaintext() -> None:
    adapter = FernetProtectedValueAdapter(_key())
    protected = adapter.seal('  PA-SYNTH-1234  ')

    assert protected != 'PA-SYNTH-1234'
    assert 'PA-SYNTH-1234' not in protected
    assert adapter.resolve(protected) == 'PA-SYNTH-1234'
    assert masked_value('12-3456-1234567-00') == '****6700'


def test_protected_adapter_rejects_invalid_keys_values_and_ciphertext() -> None:
    with pytest.raises(ProtectedValueError):
        FernetProtectedValueAdapter(b'not-a-fernet-key')
    adapter = FernetProtectedValueAdapter(_key())
    with pytest.raises(ProtectedValueError):
        adapter.seal('   ')
    with pytest.raises(ProtectedValueError):
        adapter.resolve('not-authenticated-ciphertext')
    unavailable = UnavailableProtectedValueAdapter()
    with pytest.raises(ProtectedValueError):
        unavailable.resolve('opaque')


def test_adapter_factory_uses_configured_key_and_fails_closed_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_PROTECTED_DATA_KEY', _key(b'configured').decode())
    configured = protected_value_adapter_for('production')
    protected = configured.seal('DL-1234')
    assert configured.resolve(protected) == 'DL-1234'

    monkeypatch.delenv('NORTHWIND_PROTECTED_DATA_KEY')
    unavailable = protected_value_adapter_for('production')
    with pytest.raises(ProtectedValueError):
        unavailable.seal('DL-1234')


def test_protected_account_models_reject_invalid_numbers_timestamps_and_empty_updates() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        CreatePaymentDestinationRequest(account_type='cheque', account_number='----')
    with pytest.raises(ValidationError):
        PolicyNumberRecord(
            policy_id='pol_00000000000000000001',
            customer_id='cus_owner',
            policy_number='NW-SYNTHETIC',
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        IdentityDocumentRecord(
            identity_id='idn_00000000000000000001',
            customer_id='cus_owner',
            document_type=IdentityDocumentType.PASSPORT,
            protected_value='opaque',
            masked_value='****1234',
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )
    for request_type in (
        UpdatePolicyNumberRequest,
        UpdatePaymentDestinationRequest,
        UpdateIdentityDocumentRequest,
    ):
        with pytest.raises(ValidationError):
            request_type()
    with pytest.raises(ValidationError):
        UpdateIdentityDocumentRequest(document_type=None)
