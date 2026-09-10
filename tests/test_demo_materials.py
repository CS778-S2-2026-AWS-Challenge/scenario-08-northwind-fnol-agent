"""The produced demonstration materials, associated with Claims and Evidence records.

These check what the association *states*, not only that it runs. A seeding step that
silently drops materials, or that asserts a size nobody measured, or that puts a business
condition somewhere a projection cannot be held to, would pass a smoke test and still be
wrong in the way that matters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.domain.evidence import (
    evidence_state_for,
    evidence_summary_for,
    is_registered_evidence_shape,
)
from backend.domain.models import (
    EvidenceRecord,
    EvidenceRelation,
    EvidenceRelationState,
    EvidenceSource,
    EvidenceStatus,
)
from backend.repositories.scenario_loader import ScenarioFixture, load_scenario
from backend.services.demo_materials import (
    CONDITION_STATUS,
    MATERIALS_DIRECTORY,
    SCENARIO_FOR_FAMILY,
    MaterialAssociationError,
    associate_materials,
    evidence_record_for,
    load_material_manifest,
)
from backend.services.support import now_utc

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'backend' / 'demo_data' / 'scenarios'

NOW = now_utc()


@pytest.fixture(scope='module')
def materials() -> list[dict[str, Any]]:
    return load_material_manifest()


@pytest.fixture(scope='module')
def scenarios() -> tuple[ScenarioFixture, ...]:
    return tuple(
        load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        for scenario_id in SCENARIO_FOR_FAMILY.values()
    )


def test_every_material_is_either_associated_or_named(
    materials: list[dict[str, Any]],
    scenarios: tuple[ScenarioFixture, ...],
) -> None:
    """No material may be silently dropped on the way to a Claim."""

    result = associate_materials(scenarios)
    accounted = {*result.associated, *(item.path for item in result.unassociated)}
    assert accounted == {str(material['path']) for material in materials}


def test_every_catalogue_condition_now_has_a_persisted_counterpart(
    materials: list[dict[str, Any]],
) -> None:
    """The contract migration closed the vocabulary gap this loader used to report.

    Before it, `unavailable`, `superseded`, and `expired` had no `EvidenceStatus` to
    resolve to, and the loader named them as gaps rather than coercing them into a
    neighbouring value. There is nothing left to coerce.
    """

    demonstrated = {str(material['demonstrates_condition']) for material in materials}

    assert demonstrated <= set(CONDITION_STATUS)


def test_every_catalogued_material_reaches_a_claim(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """Nothing is left over once every family has a claim.

    Two things had to land for this to be true: the contract migration, which gave every
    catalogue condition a persisted counterpart, and #583, which made `AT-14`, `AT-15`,
    and `AT-16` seeded product demonstration claims rather than test-only scenario files.
    Before either, this loader reported the leftovers by name rather than coercing them,
    and the fact that there are none now is worth asserting rather than assuming.
    """

    result = associate_materials(scenarios)

    assert result.unassociated == ()
    assert len(result.associated) == len(materials)


def test_file_facts_are_read_from_the_produced_file(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """Size and filename must come from the bytes, not from an asserted number."""

    by_path = {str(material['path']): material for material in materials}
    material = by_path['motor/motor-incident-rear-bumper.jpg']
    record = evidence_record_for(material, scenarios[0].claim)
    target = MATERIALS_DIRECTORY / 'motor/motor-incident-rear-bumper.jpg'

    assert record.size_bytes == target.stat().st_size
    assert record.original_filename == target.name
    assert record.media_type == 'image/jpeg'


def test_a_material_held_as_a_record_carries_no_file_facts(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """An unavailable material has no bytes, so it must claim none."""

    by_path = {str(material['path']): material for material in materials}
    material = dict(by_path['motor/motor-assessment-not-obtainable'])
    # The condition itself has no status yet, so the record is built through a condition
    # that does; what is under test here is the file half, not the status half.
    material['demonstrates_condition'] = 'pending'

    record = evidence_record_for(material, scenarios[0].claim)
    assert record.original_filename is None
    assert record.media_type is None
    assert record.size_bytes is None
    # Nobody supplied a material that does not exist. Attributing it to the assessor it
    # was expected from would say the assessor supplied something.
    assert record.source is EvidenceSource.STAFF


def test_a_file_that_contradicts_its_declared_media_type_is_refused(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """The record may not claim a media type for bytes nobody looked at."""

    by_path = {str(material['path']): material for material in materials}
    material = dict(by_path['motor/motor-police-event-report.pdf'])
    material['media_type'] = 'image/jpeg'

    with pytest.raises(MaterialAssociationError, match='does not begin as'):
        evidence_record_for(material, scenarios[0].claim)


def test_provenance_carries_no_catalogue_condition(scenarios: tuple[ScenarioFixture, ...]) -> None:
    """Discussion #692 constraint 1: the business condition is what `status` is for."""

    result = associate_materials(scenarios)
    for scenario in result.scenarios:
        for record in scenario.evidence:
            if not record.evidence_id.startswith('evd_material_'):
                continue
            serialised = json.dumps(record.provenance)
            for condition in CONDITION_STATUS:
                assert f'"{condition}"' not in serialised
            assert 'demo_material_ref' in record.provenance


def test_incident_evidence_held_as_a_document_is_not_an_incident_image(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """An attendance note is incident evidence, but it is not a photograph.

    Checked on the record rather than through the association, because the material that
    exercises it belongs to `home`, which has no demonstration claim until #583 lands.
    """

    by_path = {str(material['path']): material for material in materials}
    note = evidence_record_for(
        by_path['home/home-attendance-note-illegible.pdf'], scenarios[0].claim
    )
    photo = evidence_record_for(by_path['home/home-incident-ceiling.jpg'], scenarios[0].claim)

    assert note.kind == 'other_document'
    assert photo.kind == 'incident_image'


def test_only_the_named_family_reaches_the_demonstration_claim(
    scenarios: tuple[ScenarioFixture, ...],
) -> None:
    """A claim receives its own family's materials and nobody else's."""

    result = associate_materials(scenarios)
    seeded = {
        scenario.scenario_id: {
            record.evidence_id for record in scenario.evidence if 'material' in record.evidence_id
        }
        for scenario in result.scenarios
    }
    for family, scenario_id in SCENARIO_FOR_FAMILY.items():
        attached = seeded[scenario_id]
        assert attached, family
        # A material carries its family in its own identifier, so a record on the wrong
        # claim is visible without consulting the manifest again.
        assert all(f'_{family}_' in evidence_id for evidence_id in attached), family

    # And no claim received another family's material.
    assert sum(len(records) for records in seeded.values()) == len(result.associated)


def test_the_manifest_relations_become_typed_references(
    scenarios: tuple[ScenarioFixture, ...],
) -> None:
    """The catalogue's references reach the record as the contract's own references.

    The manifest names the other side by material path and the record names it by
    evidence identifier, so this is a translation of address, not a second model. A
    conflict against a claim fact keeps naming the field.
    """

    result = associate_materials(scenarios)
    records = {
        record.evidence_id: record for scenario in result.scenarios for record in scenario.evidence
    }
    pairs = [(record, reference) for record in records.values() for reference in record.references]

    def one(relation: EvidenceRelation, **match: str | None) -> tuple[Any, Any]:
        """The single pair with this relation and these reference fields.

        Selected rather than collected, because several materials carry a conflict and a
        mapping keyed by relation alone would silently keep whichever came last.
        """

        found = [
            pair
            for pair in pairs
            if pair[1].relation is relation
            and all(getattr(pair[1], name) == value for name, value in match.items())
        ]
        assert len(found) == 1, (relation, match, len(found))
        return found[0]

    superseded_record, superseded_ref = one(EvidenceRelation.SUPERSEDED_BY)
    assert superseded_record.status is EvidenceStatus.SUPERSEDED
    assert superseded_ref.evidence_id in records
    # A supersession happened; it is not an open question.
    assert superseded_ref.state is EvidenceRelationState.RESOLVED
    # The replacement is the material that is current, not another superseded issue.
    assert records[superseded_ref.evidence_id].status is EvidenceStatus.RECEIVED

    # Section 7: unavailability is established by an answer that arrived and can be opened.
    established = [
        pair for pair in pairs if pair[1].relation is EvidenceRelation.UNAVAILABILITY_ESTABLISHED_BY
    ]
    assert len(established) == 2
    for record, reference in established:
        assert record.status is EvidenceStatus.UNAVAILABLE
        assert record.size_bytes is None
        notice = records[reference.evidence_id or '']
        assert notice.status is EvidenceStatus.RECEIVED
        assert notice.size_bytes
        assert reference.state is EvidenceRelationState.RESOLVED

    # A conflict against a stated claim fact, which is the `motor` case section 5.2 needs.
    against_fact = one(
        EvidenceRelation.CONFLICTS_WITH,
        field_code='vehicle.damage_description',
    )
    assert against_fact[0].status is EvidenceStatus.RECEIVED
    assert against_fact[1].state is EvidenceRelationState.UNRESOLVED

    # And one between two materials, which is the `contents` case.
    against_material = one(
        EvidenceRelation.CONFLICTS_WITH,
        field_code=None,
    )
    assert against_material[0].status is EvidenceStatus.RECEIVED
    assert against_material[1].evidence_id in records
    assert against_material[1].state is EvidenceRelationState.UNRESOLVED


def test_the_claim_state_derives_from_the_associated_evidence(
    scenarios: tuple[ScenarioFixture, ...],
) -> None:
    """The composed scenario must satisfy the fixture's own derivation rule.

    `ScenarioFixture` already refuses a claim whose `evidence_summary` or
    `claim_state.evidence` does not follow from its records, so this asserts the
    composition went through that rule rather than around it.
    """

    result = associate_materials(scenarios)
    for scenario in result.scenarios:
        assert scenario.claim.evidence_summary == evidence_summary_for(scenario.evidence)
        assert scenario.claim.claim_state.evidence is evidence_state_for(scenario.evidence)


def test_every_associated_record_uses_a_registered_shape(
    scenarios: tuple[ScenarioFixture, ...],
) -> None:
    """A seeded record must occupy a status and file status the shared model allows."""

    result = associate_materials(scenarios)
    for scenario in result.scenarios:
        for record in scenario.evidence:
            assert is_registered_evidence_shape(record), record.evidence_id


def test_every_mapped_pair_is_one_the_domain_registers() -> None:
    """A condition may not resolve to a pair the evidence model calls a contradiction."""

    for condition, (status, file_status) in CONDITION_STATUS.items():
        record = EvidenceRecord(
            evidence_id=f'evd_{condition}',
            claim_id='clm_1',
            kind='receipt',
            status=status,
            file_status=file_status,
            source=EvidenceSource.CLAIMANT,
            created_at=NOW,
            updated_at=NOW,
        )
        assert is_registered_evidence_shape(record), condition


def test_disputed_resolves_to_received_rather_than_to_a_status_of_its_own() -> None:
    """A contested material is a received one; the conflict is the reference beside it."""

    assert CONDITION_STATUS['disputed'] == CONDITION_STATUS['received']
    assert 'disputed' not in {member.value for member in EvidenceStatus}


def test_a_family_with_no_demonstration_claim_is_reported_not_dropped(
    scenarios: tuple[ScenarioFixture, ...],
) -> None:
    """If a family loses its claim, the materials must be named rather than vanish."""

    materials = [
        {**material, 'claim_path': 'aviation'}
        for material in load_material_manifest()
        if material['claim_path'] == 'motor'
    ]
    result = associate_materials(scenarios, materials)
    assert not result.associated
    assert len(result.unassociated) == len(materials)
    assert all('aviation family' in item.reason for item in result.unassociated)


def test_a_missing_produced_file_is_refused_rather_than_asserted(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """A record must not describe a file that is not there."""

    by_path = {str(material['path']): material for material in materials}
    material = {**by_path['motor/motor-incident-scene-wide.jpg'], 'path': 'motor/absent.jpg'}

    with pytest.raises(MaterialAssociationError, match='the produced file is missing'):
        evidence_record_for(material, scenarios[0].claim)


def test_an_unrecognised_media_type_is_refused(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """A type nothing knows how to confirm cannot be confirmed by asserting it."""

    by_path = {str(material['path']): material for material in materials}
    material = {**by_path['motor/motor-incident-scene-wide.jpg'], 'media_type': 'image/heic'}

    with pytest.raises(MaterialAssociationError, match='unrecognised media type'):
        evidence_record_for(material, scenarios[0].claim)


def test_an_unrecognised_class_is_refused_rather_than_given_a_default_kind(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """Falling back to a default kind would file the material under the wrong thing."""

    by_path = {str(material['path']): material for material in materials}
    material = {
        **by_path['motor/motor-police-event-report.pdf'],
        'material_class': 'Telemetry',
    }

    with pytest.raises(MaterialAssociationError, match='has no kind'):
        evidence_record_for(material, scenarios[0].claim)


def test_incident_evidence_held_in_an_unknown_form_is_refused(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """Incident evidence resolves by form, so an unknown form has no kind."""

    by_path = {str(material['path']): material for material in materials}
    material = {**by_path['motor/motor-incident-scene-wide.jpg'], 'held_as': 'audio'}

    with pytest.raises(MaterialAssociationError, match='has no kind'):
        evidence_record_for(material, scenarios[0].claim)


def test_an_unrecognised_provider_is_refused(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """Source is who supplied it; a provider with no equivalent cannot be guessed."""

    by_path = {str(material['path']): material for material in materials}
    original = by_path['motor/motor-incident-scene-wide.jpg']
    attributes = {
        **original['attributes'],
        'source_and_stakeholder': {'provided_by': 'a passer-by'},
    }
    material = {**original, 'attributes': attributes}

    with pytest.raises(MaterialAssociationError, match='unrecognised provider'):
        evidence_record_for(material, scenarios[0].claim)


def test_a_record_nobody_recorded_is_refused(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """A no-byte record exists because someone wrote it down; if nobody did, it does not."""

    by_path = {str(material['path']): material for material in materials}
    original = by_path['motor/motor-assessment-not-obtainable']
    attributes = {
        **original['attributes'],
        'source_and_stakeholder': {'provided_by': 'none', 'recorded_by': 'nobody'},
    }
    material = {**original, 'attributes': attributes, 'demonstrates_condition': 'pending'}

    with pytest.raises(MaterialAssociationError, match='did not record it'):
        evidence_record_for(material, scenarios[0].claim)


def test_a_material_with_no_recorded_attributes_still_produces_a_record(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]],
) -> None:
    """A missing condition sentence leaves the summary empty rather than inventing one."""

    by_path = {str(material['path']): material for material in materials}
    original = by_path['motor/motor-incident-scene-wide.jpg']
    attributes = {
        'source_and_stakeholder': {'provided_by': 'claimant'},
        'conditions_it_can_occupy': {'received': {}},
    }
    material = {**original, 'attributes': attributes}

    record = evidence_record_for(material, scenarios[0].claim)
    assert record.context_summary is None
