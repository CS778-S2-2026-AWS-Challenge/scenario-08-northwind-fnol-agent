from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.identity import (
    ClaimAutoFillAction,
    ClaimAutoFillCategory,
    ClaimAutoFillSuggestion,
    ClaimAutoFillSuggestionManifest,
)
from backend.repositories.account_data import AccountDataRepository
from backend.repositories.assets import AssetRepository
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import PersistenceRepository


def claim_auto_fill_suggestions(
    persistence: PersistenceRepository,
    account_data: AccountDataRepository,
    assets: AssetRepository,
    identities: IdentityRepository,
    principal: Principal,
    claim_id: str,
) -> ClaimAutoFillSuggestionManifest:
    """Project preference-gated availability without exposing or copying saved values."""
    claim = persistence.get_claim(claim_id, principal.subject)
    account = identities.get_account(principal.subject)
    if claim is None or account is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )

    policies, _ = account_data.list_policies(
        principal.subject, include_inactive=False, after=None, limit=1
    )
    payment_destinations, _ = account_data.list_payment_destinations(
        principal.subject, include_inactive=False, after=None, limit=1
    )
    identity_documents, _ = account_data.list_identity_documents(
        principal.subject, include_inactive=False, after=None, limit=1
    )
    saved_assets, _ = assets.list_assets(
        principal.subject, include_inactive=False, offset=0, limit=1
    )
    available = {
        ClaimAutoFillCategory.PERSONAL_DETAILS: bool(
            account.legal_name.strip() and account.email.strip()
        ),
        ClaimAutoFillCategory.POLICY_NUMBER: bool(policies),
        ClaimAutoFillCategory.SAVED_ASSETS: bool(saved_assets),
        ClaimAutoFillCategory.PAYMENT_DETAILS: bool(payment_destinations),
        ClaimAutoFillCategory.IDENTITY_INFORMATION: bool(identity_documents),
    }
    actions = {
        ClaimAutoFillCategory.PERSONAL_DETAILS: ClaimAutoFillAction.REVIEW_AND_CONFIRM,
        ClaimAutoFillCategory.POLICY_NUMBER: ClaimAutoFillAction.SELECT_POLICY,
        ClaimAutoFillCategory.SAVED_ASSETS: ClaimAutoFillAction.SELECT_ASSET,
        ClaimAutoFillCategory.PAYMENT_DETAILS: ClaimAutoFillAction.CONFIRM_SEPARATELY,
        ClaimAutoFillCategory.IDENTITY_INFORMATION: ClaimAutoFillAction.CONFIRM_SEPARATELY,
    }
    suggestions = []
    for category in ClaimAutoFillCategory:
        enabled = bool(account.claim_auto_fill_preferences[category.value])
        suggestions.append(
            ClaimAutoFillSuggestion(
                category=category,
                enabled=enabled,
                available=available[category],
                eligible=enabled and available[category],
                action=actions[category],
            )
        )
    return ClaimAutoFillSuggestionManifest(
        claim_id=claim.claim_id,
        claim_revision=claim.revision,
        account_revision=account.revision,
        suggestions=suggestions,
    )
