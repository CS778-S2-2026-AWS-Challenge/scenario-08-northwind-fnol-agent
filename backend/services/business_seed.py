"""Validated synthetic business data shared by durable and in-memory adapters."""

from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.identity import ProfileEmail, ProfileName
from backend.domain.models import ContractModel, FormStatus, SessionRecord, WorkingClaim
from backend.domain.retrieval import PolicyFacts, RetrievalUncertainty, SeededPolicyRecord
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository

BUSINESS_SEED_PATH = Path(__file__).resolve().parents[2] / 'config' / 'business-seed.json'


def _midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, UTC)


class SeedCustomer(ContractModel):
    customer_id: str = Field(min_length=1, max_length=100)
    email: ProfileEmail
    display_name: ProfileName
    synthetic_password: str = Field(min_length=1, max_length=256, repr=False)


class SeedPolicy(ContractModel):
    policy_number: str = Field(min_length=1, max_length=200)
    customer_id: str = Field(min_length=1, max_length=100)
    family: str = Field(min_length=1, max_length=100)
    effective_from: date | None
    effective_to: date | None
    excess_nzd: float | None = Field(ge=0)
    status: str = Field(min_length=1, max_length=100)
    coverage_sections: list[str] = Field(max_length=100)
    uncertainty: list[str] = Field(max_length=100)

    @model_validator(mode='after')
    def validate_period(self) -> 'SeedPolicy':
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError('Seed policy period must not end before it starts.')
        if any(not code.strip() for code in self.uncertainty):
            raise ValueError('Seed policy uncertainty codes must not be empty.')
        return self

    def policy_facts(self) -> PolicyFacts:
        """Map corpus policy fields into the existing retrieval contract.

        Returns:
            Allow-listed synthetic policy facts, without an inferred coverage result.
        """
        return PolicyFacts(
            policy_reference=self.policy_number,
            product=self.family,
            status=self.status,
            effective_from=_midnight(self.effective_from) if self.effective_from else None,
            effective_to=_midnight(self.effective_to) if self.effective_to else None,
            excess_amount=self.excess_nzd,
            currency='NZD',
            coverage_sections=self.coverage_sections,
        )

    def policy_record(self) -> SeededPolicyRecord:
        """Convert one synthetic policy with ownership and uncertainty preserved.

        Returns:
            The persistence and adapter contract consumed by policy lookup.
        """
        return SeededPolicyRecord(
            customer_id=self.customer_id,
            facts=self.policy_facts(),
            uncertainty=[
                RetrievalUncertainty(code=code, detail=f'Policy source reports {code}.')
                for code in self.uncertainty
            ],
        )


class SeedSubmittedClaim(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    family: str = Field(min_length=1, max_length=100)
    incident_date: date
    submitted_date: date
    claim_number: str = Field(min_length=1, max_length=100)
    incident_description: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def validate_submission(self) -> 'SeedSubmittedClaim':
        if self.incident_date > self.submitted_date:
            raise ValueError('Seed incident must not occur after submission.')
        return self


class SeedDemoField(ContractModel):
    value: Any
    status: FormStatus


class SeedDemoCase(ContractModel):
    case_id: str = Field(pattern=r'^case_[a-f0-9]+$')
    customer_id: str = Field(min_length=1, max_length=100)
    family: Literal['motor', 'home', 'contents']
    recorded_at: datetime
    fields: dict[str, SeedDemoField]
    messages: list[str] = Field(min_length=1, max_length=20)
    contents_descriptions: list[str] = Field(max_length=20)

    @model_validator(mode='after')
    def validate_fields(self) -> 'SeedDemoCase':
        if not set(self.fields).issubset(REGISTERED_FIELD_CODES):
            raise ValueError('Demo case fields must use registered domain field codes.')
        if self.recorded_at.tzinfo is None:
            raise ValueError('Demo case recorded_at must include a timezone.')
        if self.family != 'contents' and self.contents_descriptions:
            raise ValueError('Only contents cases may supply contents items.')
        return self


class BusinessSeed(ContractModel):
    version: Literal['1']
    primary_customer_id: str | None
    customers: list[SeedCustomer]
    policies_in_system: list[SeedPolicy]
    prior_submitted_claims: list[SeedSubmittedClaim]
    demo_cases: list[SeedDemoCase]

    @model_validator(mode='after')
    def validate_links(self) -> 'BusinessSeed':
        identities = [item.customer_id for item in self.customers]
        emails = [item.email for item in self.customers]
        policy_ids = [item.policy_number for item in self.policies_in_system]
        claim_ids = [item.claim_id for item in self.prior_submitted_claims]
        session_ids = [item.session_id for item in self.prior_submitted_claims]
        for values in (identities, emails, policy_ids, claim_ids, session_ids):
            if len(values) != len(set(values)):
                raise ValueError('Business seed identifiers and emails must be unique.')
        owners = {item.customer_id for item in self.policies_in_system}
        owners.update(item.customer_id for item in self.prior_submitted_claims)
        owners.update(item.customer_id for item in self.demo_cases)
        case_ids = [item.case_id for item in self.demo_cases]
        families = [item.family for item in self.demo_cases]
        if len(case_ids) != len(set(case_ids)) or len(families) != len(set(families)):
            raise ValueError('Demo cases must have unique identifiers and material families.')
        if not owners.issubset(identities):
            raise ValueError('Business seed records must refer to declared customers.')
        if self.primary_customer_id is not None and self.primary_customer_id not in identities:
            raise ValueError('Primary customer must refer to a declared customer.')
        return self


def load_business_seed(path: str | Path) -> BusinessSeed:
    """Load exactly the selected manifest without substituting another source.

    Args:
        path: Explicit manifest path.
    Returns:
        Validated, versioned synthetic records.
    Raises:
        OSError: The selected manifest is unavailable.
        ValueError: Its schema, version, or record relationships are invalid.
    """
    return BusinessSeed.model_validate_json(Path(path).read_text(encoding='utf-8'))


def provision_business_identities(repository: IdentityRepository, seed: BusinessSeed) -> None:
    """Create missing fixed identities while preserving existing user edits.

    Args:
        repository: Selected identity adapter.
        seed: Validated manifest.
    Raises:
        ValueError: A fixed ID or email belongs to another identity.
    """
    existing_by_email = {account.email: account for account in repository.list_accounts()}
    for account in seed.customers:
        existing = existing_by_email.get(account.email)
        if existing is not None and existing.customer_id != account.customer_id:
            raise ValueError(
                'Business seed email belongs to another customer. No identities were provisioned. '
                'Preserve the existing identity database and business dataset; select a fresh '
                'NORTHWIND_IDENTITY_DB_PATH and a fresh business database for this seed, or '
                'explicitly align the manifest with existing ownership. See README.md, '
                'Business seed and existing local identities. Email is not ownership authority.'
            )
    for account in seed.customers:
        repository.ensure_seed_account(
            account.customer_id, account.email, account.synthetic_password, account.display_name
        )


def provision_business_policies(repository: PersistenceRepository, seed: BusinessSeed) -> None:
    """Insert absent owned policy facts using the selected persistence adapter.

    Args:
        repository: Selected business persistence adapter.
        seed: Validated manifest.
    """
    for policy in seed.policies_in_system:
        repository.ensure_seed_policy(policy.policy_record())


def build_seed_claim(record: SeedSubmittedClaim) -> tuple[WorkingClaim, SessionRecord]:
    """Build a minimal submitted synthetic Claim using the formal domain schema.

    Args:
        record: One manifest entry with fixed IDs and dates.
    Returns:
        A valid Claim and its owning Session for atomic repository creation.
    """
    submitted_at = _midnight(record.submitted_date)
    actor = {'actor_type': 'system', 'actor_id': 'business_seed'}
    form = {}
    for code, value in {
        'claim.product_family': record.family,
        'incident.occurred_at': {
            'date': record.incident_date.isoformat(),
            'precision': 'partial',
        },
        'incident.description': record.incident_description,
    }.items():
        form[code] = {
            'value': value,
            'source': 'claimant',
            'source_refs': [f'business-seed:1:{record.claim_id}'],
            'status': 'confirmed',
            'needed_for': 'current_action',
            'updated_at': submitted_at,
            'updated_by': actor,
        }
    claim = WorkingClaim.model_validate(
        {
            'claim_id': record.claim_id,
            'customer_id': record.customer_id,
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': record.family,
            'claim_state': {'workflow_state': 'created', 'next_action': 'PROCEED'},
            'form': form,
            'active_session_id': record.session_id,
            'external_claim': {
                'external_claim_id': f'ext_seed_{record.claim_id}',
                'claim_number': record.claim_number,
                'creation_status': 'created',
                'route': f'standard_{record.family}_intake',
                'next_step': 'Keep your claim number for future enquiries.',
                'source': 'fixture',
                'created_at': submitted_at,
            },
            'terminal_disposition': {
                'value': 'completed',
                'reason_code': 'CLAIM_CREATED',
                'source_refs': [f'business-seed:1:{record.claim_id}'],
                'recorded_by': actor,
                'recorded_at': submitted_at,
                'recorded_revision': 1,
            },
            'customer_next_step': {
                'status': 'created',
                'summary': 'Your claim has been submitted.',
                'responsible_party': 'system',
            },
            'created_at': submitted_at,
            'updated_at': submitted_at,
        }
    )
    session = SessionRecord(
        session_id=record.session_id,
        claim_id=record.claim_id,
        customer_id=record.customer_id,
        started_at=submitted_at,
        last_active_at=submitted_at,
    )
    return claim, session


def provision_business_claims(repository: PersistenceRepository, seed: BusinessSeed) -> None:
    """Insert absent Claim/Session pairs through the atomic creation boundary.

    Args:
        repository: Selected business persistence adapter.
        seed: Validated manifest.
    Raises:
        ValueError: A fixed Claim ID belongs to a different customer.
        IdempotencyConflict: A fixed Session ID conflicts with another graph.
    """
    for record in seed.prior_submitted_claims:
        existing = repository.get_claim_internal(record.claim_id)
        if existing is None:
            claim, session = build_seed_claim(record)
            try:
                repository.create_claim(claim, session)
            except IdempotencyConflict:
                # Another startup may have inserted the complete atomic pair.
                existing = repository.get_claim_internal(record.claim_id)
                if existing is None:
                    raise
        if existing is not None and existing.customer_id != record.customer_id:
            raise ValueError('Business seed Claim ID belongs to another customer.')
