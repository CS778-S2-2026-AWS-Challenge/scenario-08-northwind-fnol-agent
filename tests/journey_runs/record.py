"""The record one complete-journey run leaves behind.

`sprint/sprint4.md` section 7 lists what every run must record, and
`docs/fixtures_convention.md` says a run record is verification evidence, not a fixture.
This model is that record. Its result class is not the runner's opinion: it is derived
from the steps, materials, seam checks, and visibility checks the record already holds, and
each step's outcome is in turn derived from its HTTP status. A record whose declared class or
outcome disagrees with that evidence is rejected, so a run cannot be reported as more
complete than it was.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RECORD_SCHEMA: Final = 'northwind-journey-run/3'
ORACLE_FAILURE: Final = 'Fixture oracle failed'


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
    """How a pack material actually reached the Claim, if it did.

    `no_route`: nothing in the system could deliver it. `not_delivered`: a route exists, but
    the run did not get the material in, because its step failed or was never reached.
    """

    CLAIMANT_UPLOAD = 'claimant_upload'
    CONSENT_ROUTE = 'consent_route'
    SIMULATED_PROVIDER_RESULT = 'simulated_provider_result'
    NO_ROUTE = 'no_route'
    NOT_DELIVERED = 'not_delivered'


_UNDELIVERED = {Arrival.NO_ROUTE, Arrival.NOT_DELIVERED}


class SeamVerdict(StrEnum):
    CONSISTENT = 'consistent'
    CONTRADICTORY = 'contradictory'
    MISSING = 'missing'
    UNAVAILABLE = 'unavailable'


_DISAGREEMENT = {SeamVerdict.CONTRADICTORY, SeamVerdict.MISSING}


def step_outcome(http_status: int | None, expected_status: int) -> StepOutcome:
    """The only outcome a step's status evidence supports."""

    if http_status is None:
        return StepOutcome.FAILED
    if http_status == expected_status:
        return StepOutcome.SUCCEEDED
    if http_status in {403, 409, 422}:
        return StepOutcome.BLOCKED
    if http_status in {404, 501, 503}:
        return StepOutcome.UNAVAILABLE
    return StepOutcome.FAILED


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
    """One pack material. `pack_condition` is what the pack declares the material to be;
    `arrival` and `delivered_at_step` are what the run observed."""

    path: str
    material_class: str
    pack_condition: str
    provided_by: str
    arrival: Arrival
    delivered_at_step: str | None = None
    evidence_kind: str | None = None
    evidence_id: str | None = None
    note: str | None = None

    @model_validator(mode='after')
    def _delivery_names_its_step(self) -> Self:
        undelivered = self.arrival in _UNDELIVERED
        if undelivered == (self.delivered_at_step is not None):
            raise ValueError(
                f'{self.path}: a {self.arrival} material '
                + ('cannot name' if undelivered else 'must name')
                + ' the step that delivered it'
            )
        if self.arrival is Arrival.CLAIMANT_UPLOAD and not self.evidence_id:
            raise ValueError(f'{self.path}: an uploaded material must name its evidence')
        return self


class RunStep(_Record):
    """One route call, by whom, and what its status supports. `http_status` is None when no
    response arrived."""

    name: str
    actor: Literal['claimant', 'staff', 'integration']
    route: str
    expected_status: int
    http_status: int | None
    outcome: StepOutcome
    claim_revision: int | None = None
    detail: str | None = None

    @model_validator(mode='after')
    def _outcome_follows_the_status(self) -> Self:
        supported = step_outcome(self.http_status, self.expected_status)
        if self.outcome is not supported:
            raise ValueError(
                f'{self.name}: outcome {self.outcome} contradicts HTTP {self.http_status} '
                f'(expected {self.expected_status}), which supports {supported}'
            )
        return self


class AgentTurn(_Record):
    """One claimant message, what the Agent proposed, and what the Runtime did with it.

    Tool calls and Runtime decisions are `None` when the run's evidence level cannot observe
    them, and then `trace_limitation` must say why, so an unseen trace is never read as empty.
    """

    step: str
    claimant_input: str
    agent_reply: str | None
    proposed_action: str | None
    action_code: str | None = None
    reason_codes: list[str]
    next_step: str | None
    tool_calls: list[str] | None = None
    runtime_decisions: list[str] | None = None
    trace_limitation: str | None = None

    @model_validator(mode='after')
    def _unseen_trace_says_why(self) -> Self:
        unseen = self.tool_calls is None or self.runtime_decisions is None
        if unseen and not self.trace_limitation:
            raise ValueError(
                f'{self.step}: unobserved tool calls or Runtime decisions need a trace_limitation'
            )
        return self


class ConsentRecord(_Record):
    """A permission the claimant gave or refused. `disclosed_fields` is None when not observable."""

    purpose: str
    granted: bool
    step: str
    claim_revision: int | None
    disclosed_fields: list[str] | None = None


class VisibilityCheck(_Record):
    """Whether one audience can see something it should, or cannot see something it should not."""

    audience: Literal['claimant', 'staff']
    subject: str
    expected_visible: bool
    observed_visible: bool

    @property
    def holds(self) -> bool:
        return self.expected_visible == self.observed_visible


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
    session_id: str | None
    session_status: str | None
    active_session_id: str | None
    evidence_ids: list[str]
    external_task_statuses: list[str]
    handoff_status: str | None


class UnavailableCapability(_Record):
    """A capability the journey needs that this runtime does not provide.

    `needed_for` names the step the run could not attempt without it, and `evidence` says how
    that is known: an observation from the run and the document that sets the boundary.
    """

    capability: str = Field(min_length=1)
    needed_for: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class ClaimantEffort(_Record):
    messages: int = Field(ge=0)
    confirmations: int = Field(ge=0)
    uploads: int = Field(ge=0)
    consents: int = Field(ge=0)


def classify(
    *,
    steps: list[RunStep],
    materials: list[InputMaterial],
    seam_checks: list[SeamCheck],
    visibility_checks: list[VisibilityCheck],
    configuration: RunConfiguration,
    unavailable_capabilities: Sequence[UnavailableCapability] = (),
) -> ResultClass:
    """Derive the result class from the evidence, most severe first.

    - `failed`: a step errored in a way the journey did not expect, a fixture oracle disagreed
      with an observed response, or an audience could see what it must not (or could not see
      what it must).
    - `blocked`: the system refused a step the journey needs, for a known reason.
    - `unavailable`: a step the journey needs has no implemented capability, or the run records
      a capability this runtime does not provide.
    - `partial`: every step succeeded, but a pack material had no route in or was not
      delivered, or claimant and staff disagree (a `contradictory` or `missing` seam check).
    - `fixture-only`: everything was exercised and agrees, but on the fixture runtime, a
      simulated provider, or a simulated provider result.
    - `completed`: the same, on a deployed runtime with live providers.
    """

    outcomes = {step.outcome for step in steps}
    if (
        StepOutcome.FAILED in outcomes
        or any(step.detail is not None and ORACLE_FAILURE in step.detail for step in steps)
        or not all(check.holds for check in visibility_checks)
    ):
        return ResultClass.FAILED
    if StepOutcome.BLOCKED in outcomes:
        return ResultClass.BLOCKED
    if StepOutcome.UNAVAILABLE in outcomes or unavailable_capabilities:
        return ResultClass.UNAVAILABLE
    if any(material.arrival in _UNDELIVERED for material in materials) or any(
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
    record_schema: Literal['northwind-journey-run/3'] = RECORD_SCHEMA
    run_id: str
    scenario_id: str
    family: Literal['motor', 'home', 'contents']
    pack_id: str
    rubric_refs: list[str]
    configuration: RunConfiguration
    materials: list[InputMaterial]
    steps: list[RunStep] = Field(min_length=1)
    agent_turns: list[AgentTurn]
    consents: list[ConsentRecord]
    visibility_checks: list[VisibilityCheck]
    seam_checks: list[SeamCheck]
    unavailable_capabilities: list[UnavailableCapability] = Field(default_factory=list)
    final_state: FinalState
    effort: ClaimantEffort
    result_class: ResultClass
    result_reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def _class_follows_the_evidence(self) -> Self:
        recorded = {step.name for step in self.steps}
        referenced = [turn.step for turn in self.agent_turns]
        referenced += [consent.step for consent in self.consents]
        for step in referenced:
            if step not in recorded:
                raise ValueError(f'{step!r} is not a recorded step')
        for capability in self.unavailable_capabilities:
            if capability.needed_for in recorded:
                raise ValueError(
                    f'{capability.capability}: needed for {capability.needed_for!r}, which the run '
                    'did attempt, so its outcome is the evidence, not an unavailable capability'
                )
        succeeded = {step.name for step in self.steps if step.outcome is StepOutcome.SUCCEEDED}
        for material in self.materials:
            if (
                material.delivered_at_step is not None
                and material.delivered_at_step not in succeeded
            ):
                raise ValueError(
                    f'{material.path}: delivered at {material.delivered_at_step!r}, '
                    'which is not a step that succeeded'
                )
        derived = classify(
            steps=self.steps,
            materials=self.materials,
            seam_checks=self.seam_checks,
            visibility_checks=self.visibility_checks,
            configuration=self.configuration,
            unavailable_capabilities=self.unavailable_capabilities,
        )
        if self.result_class is not derived:
            raise ValueError(
                f'result_class {self.result_class} contradicts the recorded evidence, '
                f'which classifies as {derived}'
            )
        return self
