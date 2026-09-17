"""Provider-neutral claimant asset and immutable Claim snapshot contracts."""

from datetime import datetime
from enum import Enum
from typing import Annotated, cast

from pydantic import Field, StringConstraints, model_validator
from pydantic_core import PydanticUndefined

from backend.domain.models import ContractModel, PageInfo, StructuredFormField

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class AssetType(str, Enum):
    VEHICLE = 'vehicle'
    PROPERTY = 'property'
    CONTENTS = 'contents'


class VehicleAssetDetails(ContractModel):
    registration: ShortText
    registered_owner: ShortText | None = None
    make: ShortText | None = None
    model: ShortText | None = None
    year: int | None = Field(default=None, ge=1886, le=2200)


class PropertyAssetDetails(ContractModel):
    address: ShortText
    owner_name: ShortText | None = None
    property_type: ShortText | None = None


class ContentsAssetDetails(ContractModel):
    description: ShortText
    category: ShortText | None = None
    brand: ShortText | None = None
    model: ShortText | None = None
    serial_number: ShortText | None = None


AssetDetails = VehicleAssetDetails | PropertyAssetDetails | ContentsAssetDetails


def _omitted_short_text() -> str:
    return cast(str, PydanticUndefined)


def _omitted_asset_details() -> AssetDetails:
    return cast(AssetDetails, PydanticUndefined)


class AssetRecord(ContractModel):
    asset_id: str = Field(pattern=r'^ast_[a-f0-9]{20}$')
    customer_id: str = Field(min_length=1, max_length=200)
    asset_type: AssetType
    display_name: ShortText
    details: AssetDetails
    revision: int = Field(default=1, ge=1)
    active: bool = True
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_type_boundaries(self) -> 'AssetRecord':
        expected = {
            AssetType.VEHICLE: VehicleAssetDetails,
            AssetType.PROPERTY: PropertyAssetDetails,
            AssetType.CONTENTS: ContentsAssetDetails,
        }[self.asset_type]
        if not isinstance(self.details, expected):
            raise ValueError('Asset details must match asset_type.')
        if self.updated_at < self.created_at:
            raise ValueError('An asset cannot be updated before it is created.')
        return self


class AssetProjection(ContractModel):
    asset_id: str
    asset_type: AssetType
    display_name: str
    details: AssetDetails
    revision: int
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateAssetRequest(ContractModel):
    asset_type: AssetType
    display_name: ShortText
    details: AssetDetails

    @model_validator(mode='after')
    def validate_request(self) -> 'CreateAssetRequest':
        # Reuse the authoritative record validator without inventing a second rule set.
        AssetRecord(
            asset_id='ast_00000000000000000000',
            customer_id='validation',
            revision=1,
            active=True,
            created_at=datetime.min,
            updated_at=datetime.min,
            **self.model_dump(),
        )
        return self


class UpdateAssetRequest(ContractModel):
    # A default factory keeps each PATCH field optional without making explicit null valid.
    display_name: ShortText = Field(default_factory=_omitted_short_text)
    details: AssetDetails = Field(default_factory=_omitted_asset_details)

    @model_validator(mode='after')
    def require_change(self) -> 'UpdateAssetRequest':
        if not self.model_fields_set:
            raise ValueError('At least one asset field must be supplied.')
        return self


class AssetListResponse(ContractModel):
    items: list[AssetProjection]
    page: PageInfo


class ClaimAssetSnapshot(ContractModel):
    snapshot_id: str = Field(pattern=r'^cas_[a-f0-9]{20}$')
    claim_id: str = Field(min_length=1, max_length=200)
    customer_id: str = Field(min_length=1, max_length=200)
    asset_id: str = Field(pattern=r'^ast_[a-f0-9]{20}$')
    asset_revision: int = Field(ge=1)
    asset_type: AssetType
    display_name: ShortText
    details: AssetDetails
    captured_at: datetime
    resulting_claim_revision: int = Field(ge=1)
    source_refs: list[str] = Field(min_length=1, max_length=10)


class ClaimAssetSnapshotProjection(ContractModel):
    snapshot_id: str
    claim_id: str
    asset_id: str
    asset_revision: int
    asset_type: AssetType
    display_name: str
    details: AssetDetails
    captured_at: datetime
    resulting_claim_revision: int
    source_refs: list[str]


class SelectClaimAssetRequest(ContractModel):
    asset_id: str = Field(pattern=r'^ast_[a-f0-9]{20}$')


class ClaimAssetSelectionResponse(ContractModel):
    claim_id: str
    revision: int
    proposed_fields: dict[str, StructuredFormField]
    snapshot: ClaimAssetSnapshotProjection


class ClaimAssetSnapshotListResponse(ContractModel):
    items: list[ClaimAssetSnapshotProjection]
    page: PageInfo


def project_asset(asset: AssetRecord) -> AssetProjection:
    return AssetProjection.model_validate(asset.model_dump(exclude={'customer_id'}))


def project_snapshot(snapshot: ClaimAssetSnapshot) -> ClaimAssetSnapshotProjection:
    return ClaimAssetSnapshotProjection.model_validate(snapshot.model_dump(exclude={'customer_id'}))
