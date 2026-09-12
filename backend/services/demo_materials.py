"""Associate the produced demonstration materials with a Claim and Evidence records.

`backend/demo_data/materials/` holds twenty-six catalogued materials, twenty-four of
them produced files. Until now nothing read them: the seeded scenarios carried Evidence
records with asserted sizes and `fixture://` provenance references that resolved to
nothing. This module makes those records describe material that actually exists.

Three things are deliberately kept in one place each, because each is an open decision
rather than a fact this module gets to invent:

- `CONDITION_STATUS` is the whole of the mapping from a catalogue condition to the
  persisted status pair. Every condition has a counterpart now that the business
  condition and the file lifecycle are separate vocabularies; before that, four did not,
  and this module reported them as named gaps rather than coercing them into a
  neighbouring value.
- `SCENARIO_FOR_FAMILY` is the whole of the mapping from a claim family to the
  demonstration claim its materials attach to.
- `MATERIAL_CLASS_KIND` is the whole of the mapping from a catalogue class to the
  Evidence kind, chosen so the existing staff tag projection recognises them.

Nothing here writes the catalogue condition into `provenance`. Provenance carries origin
and the storage reference only; the business condition is what `status` is for.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceReference,
    EvidenceRelation,
    EvidenceRelationState,
    EvidenceSource,
    EvidenceStatus,
    WorkingClaim,
)
from backend.repositories.scenario_loader import ScenarioFixture

MATERIALS_DIRECTORY = Path(__file__).resolve().parents[1] / 'demo_data' / 'materials'
MANIFEST_PATH = MATERIALS_DIRECTORY / 'materials.json'
DEMO_MATERIAL_SCHEME = 'demo-material://'

RECORD_HELD_AS = 'record'
INCIDENT_EVIDENCE_CLASS = 'Incident evidence'

# Which demonstration claim carries each family's materials.
#
# These are `VALIDATION_SCENARIO_IDS` from `demo_seed`, which #583 made a seeded product
# demonstration rather than test-only scenario files. Each is a claim of exactly one
# family, which is what lets a family's materials attach to one claim and to no other.
SCENARIO_FOR_FAMILY: dict[str, str] = {
    'motor': 'AT-14-field-states-motor',
    'home': 'AT-15-field-states-home',
    'contents': 'AT-16-field-states-contents',
}

# The catalogue condition resolved to the persisted pair, and nothing else in this module
# decides it. Every catalogue condition now has a counterpart, which it did not before the
# condition and the file lifecycle were separated.
#
# `disputed` resolves to `received`, not to a status of its own. A contested material is a
# received one; the conflict is carried by the typed reference the manifest already
# records, which is also the only place that can say what the other side is.
CONDITION_STATUS: dict[str, tuple[EvidenceStatus, EvidenceFileStatus]] = {
    'missing': (EvidenceStatus.MISSING, EvidenceFileStatus.NOT_AVAILABLE),
    'pending': (EvidenceStatus.PENDING, EvidenceFileStatus.NOT_AVAILABLE),
    'received': (EvidenceStatus.RECEIVED, EvidenceFileStatus.READY),
    'disputed': (EvidenceStatus.RECEIVED, EvidenceFileStatus.READY),
    'invalid': (EvidenceStatus.INVALID, EvidenceFileStatus.READY),
    'unavailable': (EvidenceStatus.UNAVAILABLE, EvidenceFileStatus.NOT_AVAILABLE),
    'superseded': (EvidenceStatus.SUPERSEDED, EvidenceFileStatus.READY),
    'expired': (EvidenceStatus.EXPIRED, EvidenceFileStatus.READY),
}

UNMAPPED_REASON = 'no EvidenceStatus counterpart for this catalogue condition'

# Chosen so the material is recognised by what already reads evidence kinds:
# `backend/services/tag_projection.py` raises staff tags from `assessment_report`,
# `proof_of_ownership`, and `incident_image`, and treats `police_report` separately.
#
# Incident evidence is the one class that is not one kind. Most instances are
# photographs, but an attendance note is incident evidence too, and calling a PDF an
# incident image would put "Incident Image" in front of staff for a document. So that
# class alone resolves by what the material is held as.
MATERIAL_CLASS_KIND: dict[str, str] = {
    'Identity and ownership evidence': 'proof_of_ownership',
    'Authority or official report': 'police_report',
    'Assessment or estimate': 'assessment_report',
    'Communication and consent record': 'other_document',
}

INCIDENT_EVIDENCE_KIND: dict[str, str] = {
    'photo': 'incident_image',
    'document': 'other_document',
}

# The manifest says who provides a material in the catalogue's words; these are the
# persisted equivalents.
PROVIDED_BY_SOURCE: dict[str, EvidenceSource] = {
    'claimant': EvidenceSource.CLAIMANT,
    'northwind_staff': EvidenceSource.STAFF,
    'external_party': EvidenceSource.EXTERNAL_SYSTEM,
}

# A material that does not exist was provided by nobody, so the manifest records
# `provided_by: none` and names who recorded it instead. The source of such a record is
# whoever wrote it down, which is not the same as whoever the material was expected from:
# attributing it to the assessor would say the assessor supplied something.
NO_PROVIDER = 'none'
RECORDED_BY_SOURCE: dict[str, EvidenceSource] = {
    'northwind': EvidenceSource.STAFF,
    'claimant': EvidenceSource.CLAIMANT,
}

# Enough of each format to confirm the file is what the manifest says it is. The
# generator's own `--check` verifies this far more thoroughly; this is here so that a
# record never claims a media type for bytes nobody looked at on the way in.
MEDIA_TYPE_SIGNATURE: dict[str, bytes] = {
    'image/jpeg': b'\xff\xd8\xff',
    'application/pdf': b'%PDF',
}


class MaterialAssociationError(ValueError):
    """A material cannot be associated, and coercing it would state something false."""


@dataclass(frozen=True, slots=True)
class UnassociatedMaterial:
    """One catalogued material that did not become an Evidence record, and why."""

    path: str
    condition: str
    reason: str


@dataclass(frozen=True, slots=True)
class MaterialAssociationResult:
    """The scenarios with their materials attached, and what could not be attached."""

    scenarios: tuple[ScenarioFixture, ...]
    associated: tuple[str, ...]
    unassociated: tuple[UnassociatedMaterial, ...]


def load_material_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, Any]]:
    """Read the produced-material manifest.

    Args:
        path: The manifest to read.

    Returns:
        The manifest's material entries, in the order it records them.
    """

    payload = json.loads(path.read_text(encoding='utf-8'))
    materials = payload.get('materials')
    return list(materials) if isinstance(materials, list) else []


def _evidence_id_for(material_path: str) -> str:
    """Derive a stable Evidence identifier from the material's own path.

    A generated identifier would differ between two seeds of the same material, so the
    path is used directly: the material is the thing being identified.

    Args:
        material_path: The manifest path, such as `motor/motor-incident-scene-wide.jpg`.

    Returns:
        An `evd_material_` identifier unique to that material.
    """

    stem = material_path.replace('/', '_').replace('.', '_').replace('-', '_')
    return f'evd_material_{stem}'


def _file_facts(material: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    """Read the produced file's own facts rather than asserting them.

    Args:
        material: One manifest entry.

    Returns:
        The original filename, media type, and size in bytes; all `None` for a material
        held as a record, which deliberately has no file.

    Raises:
        MaterialAssociationError: The file is missing, or its leading bytes are not the
            media type the manifest declares.
    """

    if material.get('held_as') == RECORD_HELD_AS:
        return None, None, None

    material_path = str(material['path'])
    target = MATERIALS_DIRECTORY / material_path
    if not target.exists():
        raise MaterialAssociationError(f'{material_path}: the produced file is missing')

    media_type = str(material['media_type'])
    signature = MEDIA_TYPE_SIGNATURE.get(media_type)
    if signature is None:
        raise MaterialAssociationError(f'{material_path}: unrecognised media type {media_type}')
    with target.open('rb') as handle:
        leading = handle.read(len(signature))
    if leading != signature:
        raise MaterialAssociationError(f'{material_path}: the file does not begin as {media_type}')
    return target.name, media_type, target.stat().st_size


def _condition_detail(material: dict[str, Any], condition: str) -> str | None:
    """Return what the material itself says this condition means for it.

    Args:
        material: One manifest entry.
        condition: The condition the material demonstrates.

    Returns:
        The manifest's own sentence, or `None` when it records none.
    """

    attributes = material.get('attributes')
    if not isinstance(attributes, dict):
        return None
    occupiable = attributes.get('conditions_it_can_occupy')
    if not isinstance(occupiable, dict):
        return None
    entry = occupiable.get(condition)
    if not isinstance(entry, dict):
        return None
    meaning = entry.get('means_for_this_material')
    return str(meaning) if meaning is not None else None


def _source_for(material: dict[str, Any]) -> EvidenceSource:
    """Resolve who supplied the material to a persisted source.

    Args:
        material: One manifest entry.

    Returns:
        The matching `EvidenceSource`.

    Raises:
        MaterialAssociationError: The manifest names a provider with no equivalent.
    """

    attributes = material.get('attributes')
    stakeholder: dict[str, Any] = {}
    if isinstance(attributes, dict):
        block = attributes.get('source_and_stakeholder')
        if isinstance(block, dict):
            stakeholder = block
    provided_by = str(stakeholder.get('provided_by', ''))
    if provided_by == NO_PROVIDER:
        recorded_by = str(stakeholder.get('recorded_by', ''))
        source = RECORDED_BY_SOURCE.get(recorded_by)
        if source is None:
            raise MaterialAssociationError(
                f'{material.get("path")}: nothing provided it and {recorded_by!r} did not record it'
            )
        return source
    source = PROVIDED_BY_SOURCE.get(provided_by)
    if source is None:
        raise MaterialAssociationError(
            f'{material.get("path")}: unrecognised provider {provided_by!r}'
        )
    return source


def _kind_for(material: dict[str, Any]) -> str:
    """Resolve the Evidence kind a material is recorded under.

    Args:
        material: One manifest entry.

    Returns:
        The kind, chosen so the existing projections recognise the material.

    Raises:
        MaterialAssociationError: The class has no kind, or incident evidence is held in
            a form with no kind of its own.
    """

    material_class = str(material['material_class'])
    if material_class == INCIDENT_EVIDENCE_CLASS:
        held_as = str(material.get('held_as', ''))
        kind = INCIDENT_EVIDENCE_KIND.get(held_as)
        if kind is None:
            raise MaterialAssociationError(
                f'{material["path"]}: incident evidence held as {held_as!r} has no kind'
            )
        return kind
    kind = MATERIAL_CLASS_KIND.get(material_class)
    if kind is None:
        raise MaterialAssociationError(f'{material["path"]}: class {material_class} has no kind')
    return kind


# The manifest names the other side of a relation by material path, or by a claim field
# written `field:<code>`. Evidence records name it by evidence identifier, so the two are
# the same statement in two address spaces and this is the translation.
MANIFEST_RELATION: dict[str, EvidenceRelation] = {
    'conflicts_with': EvidenceRelation.CONFLICTS_WITH,
    'superseded_by': EvidenceRelation.SUPERSEDED_BY,
    'established_by': EvidenceRelation.UNAVAILABILITY_ESTABLISHED_BY,
}

FIELD_TARGET_PREFIX = 'field:'


def _references_for(
    material: dict[str, Any],
    raised_at: datetime,
    catalogue: Mapping[str, str],
) -> list[EvidenceReference]:
    """Carry the manifest's typed references onto the record.

    The catalogue records these because a condition that is a statement about a second
    thing cannot be carried by a status. The Evidence contract records them for the same
    reason, so this is a translation of address — a material path becomes the evidence
    identifier that material became — rather than a second model of the same facts.

    Nothing is invented here. A relation the manifest does not record does not appear,
    and a resolution the manifest does not state is `unresolved`, which is what the
    demonstration needs to be able to show.

    A target is checked against the catalogue before it becomes a reference. Deriving an
    identifier from a string always succeeds, so a typo, a deleted material, or a target
    in another family would otherwise produce a reference that looks valid and points at
    no record — and an unavailability whose establishing notice does not exist is exactly
    the claim section 7 forbids. The same-family rule follows from the reference model:
    an `evidence_id` is only meaningful on the claim that holds the record.

    Args:
        material: One manifest entry.
        raised_at: When the relation is recorded as raised, taken from the claim rather
            than from a clock, so seeding twice produces the same records.
        catalogue: Every catalogued material path mapped to its claim family.

    Returns:
        The typed references, empty when the material records none.

    Raises:
        MaterialAssociationError: The manifest names a relation with no counterpart, or a
            target that is not a catalogued material of the same family.
    """

    entries = material.get('references')
    if not isinstance(entries, list):
        return []

    references: list[EvidenceReference] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        relation = MANIFEST_RELATION.get(str(entry.get('relation', '')))
        if relation is None:
            raise MaterialAssociationError(
                f'{material["path"]}: unrecognised relation {entry.get("relation")!r}'
            )
        target = str(entry.get('target', ''))
        if not target.startswith(FIELD_TARGET_PREFIX):
            family = str(material['claim_path'])
            if target not in catalogue:
                raise MaterialAssociationError(
                    f'{material["path"]}: {relation.value} names {target}, '
                    f'which is not a catalogued material'
                )
            if catalogue[target] != family:
                raise MaterialAssociationError(
                    f'{material["path"]}: {relation.value} names {target}, which belongs to '
                    f'the {catalogue[target]} family and so is on a different claim'
                )
        # A supersession and an established unavailability happened once and stay true, so
        # they are recorded resolved at the moment they are raised. Only a conflict can
        # stand open, and the manifest records its resolution because the demonstration
        # has to be able to show one nobody has decided.
        resolved = (
            relation is not EvidenceRelation.CONFLICTS_WITH
            or str(entry.get('resolution', '')) == 'resolved'
        )
        references.append(
            EvidenceReference(
                relation=relation,
                evidence_id=(
                    None if target.startswith(FIELD_TARGET_PREFIX) else _evidence_id_for(target)
                ),
                field_code=(
                    target[len(FIELD_TARGET_PREFIX) :]
                    if target.startswith(FIELD_TARGET_PREFIX)
                    else None
                ),
                state=(
                    EvidenceRelationState.RESOLVED if resolved else EvidenceRelationState.UNRESOLVED
                ),
                reason=str(entry.get('reason', '')),
                raised_at=raised_at,
                resolved_at=raised_at if resolved else None,
            )
        )
    return references


def evidence_record_for(
    material: dict[str, Any],
    claim: WorkingClaim,
    catalogue: Mapping[str, str],
) -> EvidenceRecord:
    """Build the Evidence record one material becomes on its demonstration claim.

    Args:
        material: One manifest entry.
        claim: The claim the material attaches to.
        catalogue: Every catalogued material path mapped to its claim family, used to
            check that each relation target resolves.

    Returns:
        The record, with file facts read from the produced file.

    Raises:
        MaterialAssociationError: The condition has no persisted counterpart, the class
            has no Evidence kind, or the produced file contradicts the manifest.
    """

    material_path = str(material['path'])
    condition = str(material['demonstrates_condition'])
    resolved = CONDITION_STATUS.get(condition)
    if resolved is None:
        raise MaterialAssociationError(f'{material_path}: {UNMAPPED_REASON}')
    status, file_status = resolved

    kind = _kind_for(material)

    original_filename, media_type, size_bytes = _file_facts(material)
    provenance: dict[str, Any] = {
        'demo_material_ref': f'{DEMO_MATERIAL_SCHEME}{material_path}',
        'origin': 'simulated',
    }

    return EvidenceRecord(
        evidence_id=_evidence_id_for(material_path),
        claim_id=claim.claim_id,
        kind=kind,
        status=status,
        file_status=file_status,
        original_filename=original_filename,
        media_type=media_type,
        size_bytes=size_bytes,
        source=_source_for(material),
        references=_references_for(material, claim.updated_at, catalogue),
        related_fields=[],
        needed_for=['current_action'],
        provenance=provenance,
        context_summary=_condition_detail(material, condition),
        created_at=claim.updated_at,
        updated_at=claim.updated_at,
    )


def associate_materials(
    scenarios: tuple[ScenarioFixture, ...],
    materials: list[dict[str, Any]] | None = None,
) -> MaterialAssociationResult:
    """Attach every associable material to the demonstration claim of its family.

    The composed scenario is rebuilt through `ScenarioFixture.model_validate` rather than
    copied, so the fixture's own rule that `evidence_summary` and `claim_state.evidence`
    derive from the evidence records checks this composition instead of a second copy of
    that rule living here.

    Args:
        scenarios: The scenarios to attach materials to. Any whose identifier is not a
            demonstration claim for a family is returned unchanged.
        materials: The manifest entries; read from the manifest when omitted.

    Returns:
        The scenarios with materials attached, the material paths that became Evidence,
        and every material that did not, with the reason.
    """

    entries = load_material_manifest() if materials is None else materials
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    unassociated: list[UnassociatedMaterial] = []
    for material in entries:
        family = str(material['claim_path'])
        scenario_id = SCENARIO_FOR_FAMILY.get(family)
        if scenario_id is None:
            unassociated.append(
                UnassociatedMaterial(
                    path=str(material['path']),
                    condition=str(material['demonstrates_condition']),
                    reason=f'no demonstration claim exists for the {family} family',
                )
            )
            continue
        by_scenario.setdefault(scenario_id, []).append(material)

    catalogue = {str(material['path']): str(material['claim_path']) for material in entries}
    supplied = {scenario.scenario_id for scenario in scenarios}

    # A material whose claim is mapped but not supplied would otherwise be in neither
    # list: grouped away from `unassociated`, and never reached by the loop below. Every
    # catalogued material has to come back in exactly one of the two.
    for scenario_id, orphaned in by_scenario.items():
        if scenario_id in supplied:
            continue
        for material in orphaned:
            unassociated.append(
                UnassociatedMaterial(
                    path=str(material['path']),
                    condition=str(material['demonstrates_condition']),
                    reason=f'{scenario_id} carries this family but was not supplied',
                )
            )

    associated: list[str] = []
    composed: list[ScenarioFixture] = []
    for scenario in scenarios:
        candidates = by_scenario.get(scenario.scenario_id)
        if not candidates:
            composed.append(scenario)
            continue
        records = list(scenario.evidence)
        for material in candidates:
            try:
                records.append(evidence_record_for(material, scenario.claim, catalogue))
            except MaterialAssociationError as error:
                unassociated.append(
                    UnassociatedMaterial(
                        path=str(material['path']),
                        condition=str(material['demonstrates_condition']),
                        reason=str(error).split(': ', 1)[-1],
                    )
                )
                continue
            associated.append(str(material['path']))
        composed.append(_with_evidence(scenario, records))

    return MaterialAssociationResult(
        scenarios=tuple(composed),
        associated=tuple(associated),
        unassociated=tuple(unassociated),
    )


def _with_evidence(
    scenario: ScenarioFixture,
    records: list[EvidenceRecord],
) -> ScenarioFixture:
    """Rebuild a scenario around a new evidence set, deriving what the claim must state.

    Args:
        scenario: The scenario to rebuild.
        records: The complete evidence set the rebuilt scenario carries.

    Returns:
        The rebuilt scenario, validated by `ScenarioFixture`'s own derivation rules.
    """

    payload = scenario.model_dump(mode='json')
    payload['evidence'] = [record.model_dump(mode='json') for record in records]
    payload['claim']['evidence_summary'] = evidence_summary_for(records).model_dump(mode='json')
    payload['claim']['claim_state']['evidence'] = evidence_state_for(records).value
    return ScenarioFixture.model_validate(payload)


def material_content(record: EvidenceRecord) -> bytes | None:
    """Return the committed bytes that a produced demonstration material refers to.

    `associate_materials` names each produced file through `provenance['demo_material_ref']`.
    Evidence that is not a produced material, and a material held as a record with no bytes,
    has nothing to read and returns `None`.

    Args:
        record: An Evidence record, possibly one created by `associate_materials`.

    Returns:
        The produced file's bytes, or `None` when the record names no produced file.

    Raises:
        MaterialAssociationError: The reference is not a demonstration-material reference,
            points outside the materials directory, names a missing file, or names a file that
            no longer has the size the record declares.
    """

    reference = record.provenance.get('demo_material_ref')
    if not isinstance(reference, str) or record.media_type is None:
        return None
    if not reference.startswith(DEMO_MATERIAL_SCHEME):
        raise MaterialAssociationError(f'{reference}: not a demonstration-material reference')
    root = MATERIALS_DIRECTORY.resolve()
    target = (root / reference.removeprefix(DEMO_MATERIAL_SCHEME)).resolve()
    if root not in target.parents:
        raise MaterialAssociationError(f'{reference}: outside the materials directory')
    if not target.is_file():
        raise MaterialAssociationError(f'{reference}: the produced file is missing')
    content = target.read_bytes()
    if record.size_bytes is not None and len(content) != record.size_bytes:
        raise MaterialAssociationError(f'{reference}: the file no longer has its recorded size')
    return content
