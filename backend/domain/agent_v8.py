"""Unified claimant turn contract for Agent Context Runtime v8."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from backend.domain.models import (
    ContentsLossType,
    ContentsOwnership,
    ContractModel,
    FactPrecision,
)

# How the model accounts for one required fact this turn.
#   value                 - a value the claimant supplied (possibly approximate).
#   claimant_will_supply  - the claimant said they do not know yet / will send later.
#   third_party_pending   - the fact should come from an assessor, the police, etc.
FieldDisposition = Literal['value', 'claimant_will_supply', 'third_party_pending']

TurnAction = Literal[
    'record_and_ask',
    'clarify',
    'offer_service',
    'request_document',
    'obtain_document',
    'summarize',
    'propose_submit',
    'escalate',
    'answer_only',
]


class V8FieldChange(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any = None
    reported_text: str | None = Field(default=None, max_length=200)
    precision: FactPrecision = FactPrecision.EXACT
    disposition: FieldDisposition = 'value'
    # Present only for third_party_pending: which registered service owns the fact.
    service_identity: str | None = Field(default=None, max_length=100)
    # Present only for the media profile.  The text profile's bound provider
    # schema omits it, while keeping the optional field here lets the Runtime
    # use one parser for both profile variants.
    source_evidence_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode='after')
    def _value_matches_disposition(self) -> 'V8FieldChange':
        if self.disposition == 'value' and self.value is None:
            raise ValueError('A supplied fact needs a value.')
        if self.disposition == 'third_party_pending' and not self.service_identity:
            raise ValueError('A third-party fact names the service that will supply it.')
        return self


class V8MoneyAmount(ContractModel):
    amount: float = Field(ge=0, le=10_000_000, allow_inf_nan=False)
    currency: str = Field(pattern=r'^[A-Z]{3}$')


class V8ContentsItemChange(ContractModel):
    item_id: str | None = Field(default=None, min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1, le=999)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    loss_type: ContentsLossType
    ownership: ContentsOwnership
    estimated_value: V8MoneyAmount | None = None
    reported_text: str | None = Field(default=None, max_length=200)


class V8NextQuestion(ContractModel):
    field_codes: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=1, max_length=3
    )
    wording: str = Field(min_length=1, max_length=250)
    reason: Literal[
        'safety_first',
        'branch_just_activated',
        'blocks_creation',
        'clarify_conflict',
        'natural_follow_up',
    ]


class V8ServiceSuggestion(ContractModel):
    service_identity: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=150)


class V8PolicyJudgmentProposal(ContractModel):
    """Advisory policy application proposal for staff adjudication."""

    kind: Literal[
        'liability_split', 'excess_multiplicity', 'driver_permission_status',
        'unsafe_use_applicability', 'gradual_damage_discoverability',
        'natural_hazard_allocation', 'occupancy_change_applicability',
        'theft_circumstance', 'unsecured_property_dispute',
        'multi_event_dispute', 'item_classification_dispute',
    ]
    assessment: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=500)
    source_refs: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=10
    )


class V8DocumentRequest(ContractModel):
    """The model asks for a document this kind of report should carry."""

    document_kind: str = Field(min_length=1, max_length=100)
    from_party: Literal['claimant', 'third_party']
    service_identity: str | None = Field(default=None, max_length=100)


class V8EvidenceInterpretation(ContractModel):
    """What the model understood a received file to be."""

    evidence_id: str = Field(min_length=1, max_length=100)
    document_kind: str = Field(min_length=1, max_length=100)


class V8StateProposal(ContractModel):
    path: Literal['claim_state.urgency', 'claim_state.customer_support']
    to: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=150)


class V8Escalation(ContractModel):
    kind: Literal[
        'urgent_safety',
        'human_requested',
        'accessibility',
        'distress',
        'professional_review',
    ]
    reason: str = Field(min_length=1, max_length=150)


class V8TurnProposal(ContractModel):
    action: TurnAction = 'record_and_ask'
    reply: str = Field(min_length=1, max_length=500)
    reason_codes: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=5
    )
    field_changes: list[V8FieldChange] = Field(default_factory=list, max_length=8)
    contents_item_changes: list[V8ContentsItemChange] = Field(default_factory=list, max_length=6)
    # Any action may leave this None: the model decides whether this turn asks.
    next_question: V8NextQuestion | None = None
    service_suggestions: list[V8ServiceSuggestion] = Field(default_factory=list, max_length=3)
    policy_judgment_proposals: list[V8PolicyJudgmentProposal] = Field(
        default_factory=list, max_length=3
    )
    document_requests: list[V8DocumentRequest] = Field(default_factory=list, max_length=2)
    evidence_interpretations: list[V8EvidenceInterpretation] = Field(
        default_factory=list, max_length=4
    )
    # Required when action == 'summarize': the fields the reply read back to the
    # claimant. Runtime binds the confirmation request to exactly this set.
    summary_fields: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(
        default=None, max_length=30
    )
    state_proposals: list[V8StateProposal] = Field(default_factory=list, max_length=2)
    escalation: V8Escalation | None = None
    ready_to_create: bool = False
    confirms_batch: bool = False
