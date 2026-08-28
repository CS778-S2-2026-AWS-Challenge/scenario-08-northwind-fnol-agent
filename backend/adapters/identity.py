from copy import deepcopy
from datetime import UTC, datetime
from hashlib import scrypt
from hmac import compare_digest

from backend.domain.identity import ClaimantAuthSessionRecord, CustomerAccountRecord
from backend.repositories.identity import IdentityRepository


def _password_hash(customer_id: str, password: str) -> str:
    return scrypt(
        password.encode(),
        salt=f'northwind-development-{customer_id}'.encode(),
        n=2**14,
        r=8,
        p=1,
    ).hex()


class FixtureIdentityRepository(IdentityRepository):
    """Development/test identities only; never a production identity provider."""

    def __init__(self) -> None:
        seeds = (
            ('cus_demo', 'claimant.one@example.invalid', 'northwind-demo-one', 'Demo Claimant One'),
            (
                'cus_other',
                'claimant.two@example.invalid',
                'northwind-demo-two',
                'Demo Claimant Two',
            ),
        )
        self._accounts = {
            customer_id: CustomerAccountRecord(
                customer_id=customer_id,
                email=email,
                password_hash=_password_hash(customer_id, password),
                display_name=display_name,
            )
            for customer_id, email, password, display_name in seeds
        }
        self._sessions: dict[str, ClaimantAuthSessionRecord] = {}

    def authenticate(self, email: str, password: str) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        for account in self._accounts.values():
            if account.email == normalized and compare_digest(
                account.password_hash, _password_hash(account.customer_id, password)
            ):
                return deepcopy(account)
        return None

    def get_account(self, customer_id: str) -> CustomerAccountRecord | None:
        account = self._accounts.get(customer_id)
        return deepcopy(account) if account else None

    def save_account(self, account: CustomerAccountRecord) -> None:
        if account.customer_id not in self._accounts:
            raise KeyError(account.customer_id)
        self._accounts[account.customer_id] = deepcopy(account)

    def save_session(self, session: ClaimantAuthSessionRecord) -> None:
        self._sessions[session.token_hash] = deepcopy(session)

    def get_session(self, token_hash: str) -> ClaimantAuthSessionRecord | None:
        session = self._sessions.get(token_hash)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= datetime.now(UTC)
        ):
            return None
        return deepcopy(session)

    def revoke_session(self, token_hash: str) -> bool:
        session = self._sessions.get(token_hash)
        if session is None or session.revoked_at is not None:
            return False
        session.revoked_at = datetime.now(UTC)
        return True
