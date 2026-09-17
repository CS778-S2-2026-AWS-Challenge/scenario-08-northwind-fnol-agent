"""Turn-scoped field authority shared by Prompt, provider schema, and Runtime validation."""

from typing import Literal

from pydantic import Field, model_validator

from backend.domain.models import ContractModel, FieldSelectionState, FormStatus

FieldValueType = Literal['boolean', 'enum', 'text', 'location', 'text_list', 'temporal']


class TurnFieldDefinition(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value_type: FieldValueType
    allowed_values: list[str] = Field(default_factory=list, max_length=100)
    selection_state: FieldSelectionState
    value_state: FormStatus


class TurnFieldContract(ContractModel):
    contract_id: str = Field(pattern=r'^tfc_[0-9a-f]{20}$')
    registry_version: str = Field(min_length=1, max_length=160)
    branch_rules_version: str = Field(min_length=1, max_length=160)
    branch_evaluation_revision: int = Field(ge=1)
    fields: list[TurnFieldDefinition] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def require_unique_fields(self) -> 'TurnFieldContract':
        codes = [item.field_code for item in self.fields]
        if len(codes) != len(set(codes)):
            raise ValueError('Turn field contract contains duplicate field codes.')
        return self

    @property
    def by_code(self) -> dict[str, TurnFieldDefinition]:
        return {item.field_code: item for item in self.fields}

    def prompt_projection(self) -> dict[str, object]:
        return {
            'contract_id': self.contract_id,
            'registry_version': self.registry_version,
            'branch_evaluation_revision': self.branch_evaluation_revision,
            'fields': [
                {
                    'code': item.field_code,
                    'type': item.value_type,
                    **({'allowed': item.allowed_values} if item.allowed_values else {}),
                }
                for item in self.fields
            ],
        }


class TurnFieldViolation(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    expected_value_type: str = Field(min_length=1, max_length=40)
    reason_code: Literal['field_not_allowed', 'invalid_value']


class TurnFieldContractViolation(ValueError):
    def __init__(self, violations: list[TurnFieldViolation]) -> None:
        super().__init__('The provider proposal violates the current turn field contract.')
        self.violations = tuple(violations)


RepairOutcome = Literal['corrected', 'failed']
