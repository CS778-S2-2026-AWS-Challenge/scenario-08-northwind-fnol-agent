"""The record one complete-journey run leaves behind.

`sprint/sprint4.md` section 7 lists what every run must record, and
`docs/fixtures_convention.md` says a run record is verification evidence, not a fixture.
This model is that record. Its result class is not the runner's opinion: it is derived
from the steps, materials, and seam checks the record already holds, and a record whose
declared class disagrees with them is rejected, so a run cannot be reported as more
complete than its own evidence.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RECORD_SCHEMA: Final = 'northwind-journey-run/1'


class ResultClass(StrEnum):
    """The Sprint 4 result classes, from most to least severe."""

    FAILED = 'failed'
    BLOCKED = 'blocked'
    UNAVAILABLE = 'unavailable'
    PARTIAL = 'partial'
    FIXTURE_ONLY = 'fixture-only'
    COMPLETED = 'completed'


class StepOutcome(StrEnum):
    SUCCEEDED = 'succeeded'
    BLOCKED = 'blocked'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'


class Arrival(StrEnum):
    """How a pack material actually reached the Claim, if it did."""

    CLAIMANT_UPLOAD = 'claimant_upload'
    CONSENT_ROUTE = 'consent_route'
    SIMULATED_PROVIDER_RESULT = 'simulated_provider_result'
    NO_ROUTE = 'no_route'


class SeamVerdict(StrEnum):
    CONSISTENT = 'consistent'
    CONTRADICTORY = 'contradictory'
    MISSING = 'missing'
    UNAVAILABLE = 'unavailable'


_DISAGREEMENT = {SeamVerdict.CONTRADICTORY, SeamVerdict.MISSING}


class _Record(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class RunConfiguration(_Record):
    head: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    runtime: Literal['fixture', 'deployed']
    provider_mode: Literal['simulated', 'live']
    agent_runtime_profile: str
    model_profile_id: str
    evidence_level: str = Field(min_length=1)


class InputMaterial(_Record):
    path: str
    material_class: str
    condition: str
    provided_by: str
    arrival: Arrival
    evidence_kind: str | None = None
    evidence_id: str | None = None
    note: str | None = None


class RunStep(_Record):
    name: str
    route: str
    http_status: int | None
    outcome: StepOutcome
    claim_revision: int | None = None
    detail: str | None = None


class SeamCheck(_Record):
    """One question both ends must answer the same way."""

    seam: str
    question: str
    claimant: str
    staff: str
    verdict: SeamVerdict
    defect_ref: str | None = None

    @model_validator(mode='after')
    def _disagreement_names_its_defect(self) -> Self:
        if self.verdict in _DISAGREEMENT and not self.defect_ref:
            raise ValueError(
                f"{self.seam}: a {self.verdict} check must name a defect reference or 'untracked'"
            )
        return self


class FinalState(_Record):
    claim_id: str
    claim_number: str | None
    expected_by: datetime | None
    workflow_state: str | None
    lifecycle_state: str | None
    queue_key: str | None
    customer_next_step: str | None
    next_step_responsible_party: str | None
    evidence_ids: list[str]
    external_task_statuses: list[str]
    handoff_status: str | None


class ClaimantEffort(_Record):
    messages: int = Field(ge=0)
    confirmations: int = Field(ge=0)
    uploads: int = Field(ge=0)
    consents: int = Field(ge=0)


def classify(
    steps: list[RunStep],
    materials: list[InputMaterial],
    seam_checks: list[SeamCheck],
    configuration: RunConfiguration,
) -> ResultClass:
    """Derive the result class from the evidence, most severe first.

    - `failed`: a step errored in a way the journey did not expect.
    - `blocked`: the system refused a step the journey needs, for a known reason.
    - `unavailable`: a step the journey needs has no implemented capability.
    - `partial`: every step succeeded, but a pack material had no route in, or claimant
      and staff disagree (a `contradictory` or `missing` seam check).
    - `fixture-only`: everything was exercised and agrees, but on the fixture runtime, a
      simulated provider, or a simulated provider result.
    - `completed`: the same, on a deployed runtime with live providers.
    """

    outcomes = {step.outcome for step in steps}
    for outcome, result in (
        (StepOutcome.FAILED, ResultClass.FAILED),
        (StepOutcome.BLOCKED, ResultClass.BLOCKED),
        (StepOutcome.UNAVAILABLE, ResultClass.UNAVAILABLE),
    ):
        if outcome in outcomes:
            return result
    if any(material.arrival is Arrival.NO_ROUTE for material in materials) or any(
        check.verdict in _DISAGREEMENT for check in seam_checks
    ):
        return ResultClass.PARTIAL
    if (
        configuration.runtime == 'fixture'
        or configuration.provider_mode == 'simulated'
        or any(material.arrival is Arrival.SIMULATED_PROVIDER_RESULT for material in materials)
    ):
        return ResultClass.FIXTURE_ONLY
    return ResultClass.COMPLETED


class JourneyRunRecord(_Record):
    record_schema: Literal['northwind-journey-run/1'] = RECORD_SCHEMA
    run_id: str
    scenario_id: str
    family: Literal['motor', 'home', 'contents']
    pack_id: str
    rubric_refs: list[str]
    configuration: RunConfiguration
    materials: list[InputMaterial]
    steps: list[RunStep] = Field(min_length=1)
    seam_checks: list[SeamCheck]
    final_state: FinalState
    effort: ClaimantEffort
    result_class: ResultClass
    result_reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def _class_follows_the_evidence(self) -> Self:
        derived = classify(self.steps, self.materials, self.seam_checks, self.configuration)
        if self.result_class is not derived:
            raise ValueError(
                f'result_class {self.result_class} contradicts the recorded evidence, '
                f'which classifies as {derived}'
            )
        return self
