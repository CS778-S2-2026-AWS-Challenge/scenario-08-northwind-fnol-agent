"""Produce and verify the demonstration materials named by the material catalogue.

Every asset is generated rather than sourced, so its origin is unambiguous: nothing here
is a photograph of a real incident or a document issued by a real authority. Each rendered
asset states that on its face, and carries the same statement in a machine-readable place
so that the claim can be checked rather than trusted: a JPEG comment segment for the
images, the page text for the documents.

Run from the repository root:

    python backend/demo_data/materials/generate_materials.py          # write every asset
    python backend/demo_data/materials/generate_materials.py --check  # verify, write nothing

`--check` reads the produced files with the standard library alone. Pillow is needed to
write the images and is a development dependency only; nothing in the application or the
test suite imports this module.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import pathlib
import zlib
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = HERE / 'materials.json'

SIMULATED = 'SIMULATED MATERIAL - NOT A REAL INCIDENT OR DOCUMENT'
MANIFEST_SCHEMA = 'northwind.demo-materials/1'

PHOTO_SIZE = (900, 640)

# Muted, deliberately unphotographic palette. A demonstration asset should read as a
# stand-in at a glance rather than invite a viewer to mistake it for a photograph.
INK = (38, 42, 48)
MUTED = (120, 128, 138)
PAPER = (247, 246, 243)
FIELD = (214, 219, 224)
ACCENT = (176, 92, 68)

MEDIA_TYPES = {'photo': 'image/jpeg', 'document': 'application/pdf'}

# Conditions where the material itself is what is wrong, so a viewer has to be able to see
# it. `disputed` is deliberately not here: a contested photograph is perfectly readable,
# and what it conflicts with is another record or a stated fact, not anything in the frame.
VISIBLY_UNUSABLE = frozenset({'invalid'})

# A material that is catalogued but holds no bytes of its own. `unavailable` is the
# condition that needs one: what is unavailable is the material that never arrived, and
# the document recording why it will not arrive is a different material that did.
RECORD_KIND = 'record'

ESTABLISHED_BY = 'established_by'
SUPERSEDED_BY = 'superseded_by'
CONFLICTS_WITH = 'conflicts_with'

# Which conditions cannot be stated on their own. Section 7 requires unavailability to be
# established rather than inferred; supersession is meaningless without the issue that
# replaced this one; and a conflict that does not name its other side cannot be shown to
# either surface, because neither can say what is contested.
REFERENCE_REQUIRED_BY_CONDITION = {
    'unavailable': ESTABLISHED_BY,
    'superseded': SUPERSEDED_BY,
    'disputed': CONFLICTS_WITH,
}

# A conflict target may be a stated claim fact rather than another material, which is the
# `motor` case section 5.2 requires: incident evidence against something the claimant said.
FIELD_TARGET_PREFIX = 'field:'


def _unresolved(question: str, blocked_on: str) -> dict[str, str]:
    """Record a catalogue section 9 decision rather than inventing an answer.

    Section 3 says an unanswered attribute is an open decision recorded in section 9,
    not a blank to be filled in during production. So the manifest answers what is
    settled and names the dependency for what is not, which is the difference between an
    honest gap and a fabricated value.
    """

    return {'unresolved': question, 'blocked_on': blocked_on}


CONSENT_COPY_PENDING = 'What consent copy and disclosure scope this class requires'
ELEVATED_RETENTION_PENDING = 'The retention rule for classes marked Elevated in section 2'

# What a material class answers for every member of it. A class rule genuinely answers
# for its materials, so these are not repeated per asset; the manifest merges them in.
CLASS_PROFILE: dict[str, dict[str, object]] = {
    'Incident evidence': {
        'source_and_stakeholder': {
            'provided_by': 'claimant',
            'detail': 'Captured by the claimant at or after the loss and supplied with the report.',
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': True,
            'claimant_sees': 'Their own material, its condition, and what it now unblocks.',
            'staff_sees': 'The material, its provenance, and whether it has been checked.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
        'retention': {'sensitivity': 'standard', 'rule': 'Follows the claim it belongs to.'},
    },
    'Identity and ownership evidence': {
        'source_and_stakeholder': {
            'provided_by': 'claimant',
            'detail': 'Supplied by the claimant from a retailer, insurer, or valuer record.',
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': True,
            'claimant_sees': 'That it arrived and what it establishes, never internal review '
            'signals.',
            'staff_sees': 'The material, its provenance, and the authorisation permitting any '
            'disclosure.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
        'retention': {
            'sensitivity': 'elevated',
            'rule': _unresolved(ELEVATED_RETENTION_PENDING, 'privacy review'),
        },
    },
    'Authority or official report': {
        'source_and_stakeholder': {
            'provided_by': 'external_party',
            'detail': 'Issued by a body outside Northwind and outside the claimant, and arriving '
            'on the issuer timetable.',
            'stakeholder': _unresolved(
                'Which stakeholder issues this report, and what access exists', 'P3'
            ),
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': True,
            'claimant_sees': 'That it is awaited or has arrived, and who is being waited on.',
            'staff_sees': 'The report, its issuer, and the authorisation that permitted the '
            'request.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
        'retention': {'sensitivity': 'standard', 'rule': 'Follows the claim it belongs to.'},
    },
    'Assessment or estimate': {
        'source_and_stakeholder': {
            'provided_by': 'external_party',
            'detail': 'The output of a third-party service request authorised by Northwind and '
            'by the claimant.',
            'stakeholder': _unresolved(
                'Which stakeholder issues this assessment, and what access exists', 'P3'
            ),
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': True,
            'claimant_sees': 'That an assessment was requested, its condition, and the next step.',
            'staff_sees': 'The assessment, its provenance, whether it has been checked, and the '
            'authorisation that permitted the disclosure.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
        'retention': {
            'sensitivity': 'elevated',
            'rule': _unresolved(ELEVATED_RETENTION_PENDING, 'privacy review'),
        },
    },
    'Communication and consent record': {
        'source_and_stakeholder': {
            'provided_by': 'northwind_staff',
            'detail': 'Recorded by Northwind when an authorisation is given, so the authorisation '
            'is auditable rather than assumed.',
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': False,
            'claimant_sees': 'What was shared, with whom, and for what purpose.',
            'staff_sees': 'The same, plus the authorisation basis for the disclosure.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
        'retention': {
            'sensitivity': 'elevated',
            'rule': _unresolved(ELEVATED_RETENTION_PENDING, 'privacy review'),
        },
    },
}

# A no-byte record describes an expected material that never arrived. It therefore cannot
# inherit a class profile that says an artefact was issued, provided, or can be opened. The
# external party remains the expected source, while Northwind records the established absence
# after the separately received answer named by `established_by`.
RECORD_REPRESENTATION_PROFILE: dict[str, dict[str, object]] = {
    'Authority or official report': {
        'source_and_stakeholder': {
            'provided_by': 'none',
            'expected_from': 'external_party',
            'recorded_by': 'northwind',
            'detail': 'No investigation outcome report was provided. Northwind holds this '
            'no-byte record only after the separately received authority answer cited by '
            'established_by establishes that the expected report is not held.',
            'stakeholder': _unresolved(
                'Which stakeholder would issue this report, and what access exists', 'P3'
            ),
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': True,
            'claimant_can_open_artefact': False,
            'staff_can_open_artefact': False,
            'claimant_sees': 'That the requested report cannot be obtained, the established '
            'reason, and the next step. No report artefact is available to open.',
            'staff_sees': 'The unavailable record, the separately received authority answer '
            'cited by established_by, the reason, and the request authorisation. No report '
            'artefact is available to open.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
    },
    'Assessment or estimate': {
        'source_and_stakeholder': {
            'provided_by': 'none',
            'expected_from': 'external_party',
            'recorded_by': 'northwind',
            'detail': 'No assessment was provided. Northwind holds this no-byte record only '
            'after the separately received assessor answer cited by established_by establishes '
            'that the expected assessment cannot be obtained.',
            'stakeholder': _unresolved(
                'Which stakeholder would issue this assessment, and what access exists', 'P3'
            ),
        },
        'consent_and_visibility': {
            'disclosure_requires_consent': True,
            'claimant_can_open_artefact': False,
            'staff_can_open_artefact': False,
            'claimant_sees': 'That the requested assessment cannot be obtained, the established '
            'reason, and the next step. No assessment artefact is available to open.',
            'staff_sees': 'The unavailable record, the separately received assessor answer '
            'cited by established_by, the reason, and the request authorisation. No assessment '
            'artefact is available to open.',
            'copy_and_scope': _unresolved(CONSENT_COPY_PENDING, 'P5'),
        },
    },
}

# What each catalogue condition requires a surface to show, from section 7. Behaviour
# when a material is not usable is a property of the condition, not of one asset.
CONDITION_BEHAVIOUR: dict[str, dict[str, str]] = {
    'missing': {
        'claimant': 'What is needed, why, and what happens if it cannot be provided.',
        'staff': 'That it is outstanding and who it is waiting on. Missing must not block work '
        'that does not depend on it.',
    },
    'pending': {
        'claimant': 'Who is being waited on, and that the claim is preserved meanwhile.',
        'staff': 'The request, its condition, and the responsible party. Waiting without an owner '
        'is not a displayable state.',
    },
    'unavailable': {
        'claimant': 'That it cannot currently be obtained, and why.',
        'staff': 'The established reason. Unavailability is never inferred where none was '
        'established.',
    },
    'received': {
        'claimant': 'That it arrived, and what it now unblocks.',
        'staff': 'The material, its provenance, and whether it has been checked.',
    },
    'invalid': {
        'claimant': 'What is wrong in terms they can act on, without overwriting the fact it was '
        'meant to support.',
        'staff': 'The reason it is unusable and the action available to them.',
    },
    'superseded': {
        'claimant': 'That a later instance replaces it. Replacement is not deletion.',
        'staff': 'Both instances, with the replacement identified and the earlier one retained.',
    },
    'expired': {
        'claimant': 'What expired, and what would restore it.',
        'staff': 'The expiry and the action that would obtain a current instance.',
    },
    'disputed': {
        'claimant': 'That a check is in progress, never which side is doubted.',
        'staff': 'Both sides, their sources, and the decision that would resolve it.',
    },
}


@dataclass(frozen=True, slots=True)
class MaterialReference:
    """A typed pointer from one material to another, and why it is there.

    Conditions that describe a relationship cannot be carried by a status word alone.
    `unavailable`, `superseded`, and `disputed` each say something about a *second*
    thing, and a reader who is only told the condition cannot find that second thing.
    So the relation is named, the target is named, and the reason is stated.

    `resolution` applies to a conflict alone. An unavailability that has been established
    and a supersession that has happened are both settled; a conflict is not settled until
    someone decides it, and the demonstration has to be able to show one that nobody has.
    """

    relation: str
    target: str
    reason: str
    resolution: str | None = None

    def as_manifest_entry(self) -> dict[str, str]:
        """Return the reference in its generated-manifest shape.

        Returns:
            The relation, target, reason, and optional resolution fields.
        """

        entry = {'relation': self.relation, 'target': self.target, 'reason': self.reason}
        if self.resolution is not None:
            entry['resolution'] = self.resolution
        return entry


@dataclass(frozen=True, slots=True)
class Asset:
    """One material to produce, described in the catalogue's own vocabulary."""

    path: str
    family: str
    material_class: str
    condition: str
    title: str
    lines: tuple[str, ...]
    kind: str  # 'photo', 'document', or 'record'
    references: tuple[MaterialReference, ...] = ()

    @property
    def media_type(self) -> str | None:
        """Return the produced file's media type.

        Returns:
            The media type, or `None` for a material that holds no bytes.
        """

        return MEDIA_TYPES.get(self.kind)

    @property
    def has_artefact(self) -> bool:
        """Return whether this material is represented by produced bytes.

        Returns:
            `True` for a photo or document and `False` for a no-byte record.
        """

        return self.kind != RECORD_KIND


REGISTERED_FIELD_PENDING = 'Which registered field this material class links to'
CONDITION_MAPPING_PENDING = (
    'How this condition maps onto persisted evidence status and file-status values'
)


# What each produced asset answers for itself: the decision it supports, when it becomes
# relevant, which conditions it can occupy, what makes an instance usable, and what it
# attaches to. Everything else its class answers, in CLASS_PROFILE.
ASSET_DETAIL: dict[str, dict[str, object]] = {
    'motor/motor-incident-rear-bumper.jpg': {
        'purpose': 'Lets the Agent propose the damage description instead of interrogating the '
        'claimant for it.',
        'trigger': 'As soon as the claimant reports vehicle damage, before any assessment is '
        'requested.',
        'conditions': {
            'missing': 'No photograph of the damaged area has been offered.',
            'received': 'A legible photograph of the damaged area is attached.',
            'invalid': 'The damage is not identifiable in the frame.',
            'disputed': 'What it shows is inconsistent with the stated impact.',
        },
        'media_usable': 'The damaged area fills enough of the frame to identify what is damaged, '
        'in focus and adequately lit.',
        'media_insufficient': 'Motion blur, darkness, or a crop that excludes the damage.',
        'linkage': 'Supports the claim fact "vehicle damage description" and any later vehicle '
        'damage assessment request.',
    },
    'motor/motor-incident-scene-wide.jpg': {
        'purpose': 'Supports the staff judgement about position and extent, which a close crop '
        'cannot establish.',
        'trigger': 'With the first damage photographs, while the scene account is being taken.',
        'conditions': {
            'missing': 'No wide view of the scene has been offered.',
            'received': 'A wide view showing both vehicles and the road context is attached.',
            'invalid': 'The vehicles or the road context are not identifiable.',
        },
        'media_usable': 'Both vehicles and the road markings or kerb are visible in one frame.',
        'media_insufficient': 'A crop that shows only one vehicle, or no road context at all.',
        'linkage': 'Supports the claim facts "incident location" and "incident description".',
    },
    'motor/motor-incident-unreadable.jpg': {
        'purpose': 'Demonstrates the invalid condition: material arrived and still does not '
        'support the decision it was offered for.',
        'trigger': 'On upload, when the check finds the content unusable.',
        'conditions': {
            'invalid': 'It arrived, and the damage it was offered to show cannot be identified.',
        },
        'media_usable': 'Not applicable; this instance exists to be unusable.',
        'media_insufficient': 'Motion blur across the whole frame, so no damage is identifiable.',
        'linkage': 'Was offered against the claim fact "vehicle damage description" and does not '
        'settle it.',
    },
    'motor/motor-incident-conflicting-panel.jpg': {
        'purpose': 'Demonstrates the disputed condition: a staff decision is required because two '
        'accounts disagree.',
        'trigger': 'When material arrives that contradicts a fact the claimant has stated.',
        'conditions': {
            'received': 'An instance exists and is attached.',
            'disputed': 'It shows front nearside damage while the claimant stated rear impact '
            'only; neither side is resolved.',
        },
        'media_usable': 'The damaged panel is identifiable well enough to compare against the '
        'stated account.',
        'media_insufficient': 'Damage that cannot be located on the vehicle.',
        'linkage': 'Conflicts with the claim fact "vehicle damage description" and requires a '
        'staff decision to resolve.',
    },
    'motor/motor-police-event-report.pdf': {
        'purpose': 'Carries weight about what happened that the claimant cannot supply alone.',
        'trigger': 'After the incident is reported, on the issuing authority timetable rather '
        'than the claim timetable.',
        'conditions': {
            'missing': 'The journey needs it and nothing has been offered.',
            'pending': 'It has been sought and the wait is on the issuing authority.',
            'unavailable': 'It has been sought and cannot currently be obtained.',
            'received': 'The issued report is attached.',
        },
        'media_usable': 'The event reference, the recorded parties, and the position account are '
        'legible.',
        'media_insufficient': 'A copy where the reference or the account cannot be read.',
        'linkage': 'Supports the claim facts "incident description" and "incident location", and '
        'attaches to the authority request that sought it.',
    },
    'motor/motor-assessment-unavailable-notice.pdf': {
        'purpose': 'Records the assessor answer itself, so staff act on a stated reason rather '
        'than on an assumption that the wait continues. This document arrived; what it says '
        'cannot be produced is a different material.',
        'trigger': 'When an authorised assessment request comes back unfulfilled rather than late.',
        'conditions': {
            'pending': 'The request is out and the wait is on the assessor.',
            'received': 'The assessor answer has arrived and states its reason.',
            'invalid': 'A refusal arrived, but without a reason it establishes nothing.',
        },
        'media_usable': 'The assessor reference and the stated reason the assessment cannot be '
        'produced are both legible.',
        'media_insufficient': 'A refusal with no reason, which cannot be distinguished from a '
        'request that was never answered.',
        'linkage': 'Attaches to the third-party vehicle assessment request it answers, and is '
        'what establishes that assessment as unavailable.',
    },
    'motor/motor-assessment-not-obtainable': {
        'purpose': 'Carries the unavailability itself, so the claim records that an assessment was '
        'sought and will not arrive rather than leaving a silent gap that reads as a wait '
        'nobody is servicing.',
        'trigger': 'When the assessor answer establishing non-availability has been received.',
        'conditions': {
            'pending': 'Before the answer arrives, the wait is on the assessor.',
            'unavailable': 'The answer has arrived and establishes that no assessment can be '
            'produced. The reason is on the notice this record cites, never on this record '
            'alone.',
        },
        'media_usable': 'No artefact of its own. What has to be legible is the notice it cites, '
        'which carries the assessor reference and the reason.',
        'media_insufficient': 'An unavailability asserted with no notice behind it, which '
        'section 7 forbids: it cannot be distinguished from a request nobody answered.',
        'linkage': 'Stands in the place the third-party vehicle assessment would have occupied, '
        'and leaves the claim fact it would have supported unsettled.',
    },
    'contents/contents-authority-unavailable-notice.pdf': {
        'purpose': 'Records the authority answer itself, so the claim can proceed on what is known '
        'rather than waiting indefinitely. This document arrived; the outcome report it says '
        'is not held is a different material.',
        'trigger': 'When an authority request comes back unfulfilled rather than late.',
        'conditions': {
            'pending': 'The request is out and the wait is on the issuing authority.',
            'received': 'The authority answer has arrived and states its reason.',
            'invalid': 'A refusal arrived, but without a reason it establishes nothing.',
        },
        'media_usable': 'The event reference and the stated reason no report can be issued are '
        'both legible.',
        'media_insufficient': 'A refusal with no reason, which cannot be distinguished from a '
        'request that was never answered.',
        'linkage': 'Attaches to the investigation outcome request it answers, and is what '
        'establishes that outcome report as unavailable.',
    },
    'contents/contents-authority-outcome-not-held': {
        'purpose': 'Carries the unavailability itself, so the claim records that an outcome report '
        'was sought and is not held rather than leaving a silent gap that reads as a wait '
        'nobody is servicing.',
        'trigger': 'When the authority answer establishing non-availability has been received.',
        'conditions': {
            'pending': 'Before the answer arrives, the wait is on the issuing authority.',
            'unavailable': 'The answer has arrived and establishes that no outcome report is held. '
            'The reason is on the notice this record cites, never on this record alone.',
        },
        'media_usable': 'No artefact of its own. What has to be legible is the notice it cites, '
        'which carries the event reference and the reason.',
        'media_insufficient': 'An unavailability asserted with no notice behind it, which '
        'section 7 forbids: it cannot be distinguished from a request nobody answered.',
        'linkage': 'Stands in the place the investigation outcome report would have occupied, and '
        'leaves the claim fact it would have supported unsettled.',
    },
    'motor/motor-assessment-v1.pdf': {
        'purpose': 'The input to any cost conversation, and the output of a third-party service '
        'request. It is not a decision.',
        'trigger': 'After an assessor request is authorised and the assessor reports.',
        'conditions': {
            'pending': 'The request is authorised and the wait is on the assessor.',
            'received': 'The assessment is attached.',
            'superseded': 'A later assessment replaces it; this one remains in the record.',
        },
        'media_usable': 'The assessor reference, the repairability judgement, and the parts '
        'position are legible.',
        'media_insufficient': 'A copy without a reference, or without a stated judgement.',
        'linkage': 'Attaches to the vehicle damage assessment request that produced it.',
    },
    'motor/motor-assessment-v2.pdf': {
        'purpose': 'The current professional judgement of damage, cost, and repairability.',
        'trigger': 'When the assessor reissues after the first assessment is revised.',
        'conditions': {
            'received': 'The revised assessment is attached and is the current one.',
            'unavailable': 'A revision was sought and cannot currently be obtained.',
        },
        'media_usable': 'The assessor reference, the revised parts list, and the relationship to '
        'the earlier issue are legible.',
        'media_insufficient': 'A revision that does not identify what it supersedes.',
        'linkage': 'Attaches to the same assessment request as the first issue and supersedes it.',
    },
    'motor/motor-consent-record.pdf': {
        'purpose': 'Makes the disclosure to the assessor auditable rather than assumed.',
        'trigger': 'Before any claim detail is disclosed to the assessor.',
        'conditions': {
            'missing': 'No authorisation has been recorded, so no disclosure may occur.',
            'received': 'The authorisation is recorded and names what was shared and why.',
        },
        'media_usable': 'The shared fields, the purpose, and the authorising claimant are all '
        'named.',
        'media_insufficient': 'An authorisation that does not name what was shared or for what '
        'purpose.',
        'linkage': 'Attaches to the vehicle damage assessment request it authorises.',
    },
    'home/home-incident-ceiling.jpg': {
        'purpose': 'Lets the Agent propose the affected areas rather than asking the claimant to '
        'enumerate them.',
        'trigger': 'As soon as property damage is reported.',
        'conditions': {
            'missing': 'No photograph of the affected area has been offered.',
            'received': 'A photograph of the affected area is attached.',
            'invalid': 'The affected area is not identifiable.',
        },
        'media_usable': 'The staining or ingress is visible against identifiable room features.',
        'media_insufficient': 'A frame too close to locate the damage in the property.',
        'linkage': 'Supports the claim fact "affected areas".',
    },
    'home/home-incident-wall-second-room.jpg': {
        'purpose': 'Establishes that the loss extends beyond one area, which changes the scope of '
        'the assessment.',
        'trigger': 'With the first property photographs, when more than one area is affected.',
        'conditions': {
            'missing': 'Only one area has been evidenced.',
            'received': 'A second affected area is evidenced.',
            'invalid': 'The second area cannot be distinguished from the first.',
        },
        'media_usable': 'The second room is identifiable as distinct from the first.',
        'media_insufficient': 'A frame that could be the same room.',
        'linkage': 'Supports the claim fact "affected areas".',
    },
    'home/home-attendance-note-illegible.pdf': {
        'purpose': 'Demonstrates that a third-party record can arrive and still carry nothing '
        'usable.',
        'trigger': 'When an attending party supplies their record.',
        'conditions': {
            'invalid': 'It arrived and its text is not legible in the supplied copy.',
        },
        'media_usable': 'Not applicable; this instance exists to be unusable.',
        'media_insufficient': 'Text that cannot be read in the supplied copy.',
        'linkage': 'Was offered against the claim fact "incident description" and does not settle '
        'it.',
    },
    'home/home-repair-assessment.pdf': {
        'purpose': 'The professional judgement of the repair scope, and the input to the cost '
        'conversation.',
        'trigger': 'After a repair assessment is authorised and the assessor reports.',
        'conditions': {
            'missing': 'No assessment has been sought.',
            'pending': 'The request is authorised and the wait is on the assessor.',
            'received': 'The assessment is attached.',
        },
        'media_usable': 'The assessor reference, the traced cause, and the affected areas are '
        'legible.',
        'media_insufficient': 'An assessment without a reference or without a stated scope.',
        'linkage': 'Attaches to the repair assessment request that produced it, and to the claim '
        'fact "affected areas".',
    },
    'home/home-consent-record.pdf': {
        'purpose': 'Makes the disclosure to the repair assessor auditable rather than assumed.',
        'trigger': 'Before any claim detail is disclosed to the assessor.',
        'conditions': {
            'missing': 'No authorisation has been recorded, so no disclosure may occur.',
            'received': 'The authorisation is recorded and names what was shared and why.',
        },
        'media_usable': 'The shared fields, the purpose, and the authorising claimant are named.',
        'media_insufficient': 'An authorisation that does not name what was shared or why.',
        'linkage': 'Attaches to the repair assessment request it authorises.',
    },
    'contents/contents-item-damaged.jpg': {
        'purpose': 'Identifies the item claimed for and the damage to it.',
        'trigger': 'As soon as an item is claimed for.',
        'conditions': {
            'missing': 'No photograph of the item has been offered.',
            'received': 'A photograph of the item as found is attached.',
            'invalid': 'The item or its damage is not identifiable.',
        },
        'media_usable': 'The item is identifiable and the damage is visible.',
        'media_insufficient': 'A frame in which the item cannot be identified.',
        'linkage': 'Identifies the claimed item. Which registered field carries it is unresolved.',
    },
    'contents/contents-item-in-situ.jpg': {
        'purpose': 'Establishes that the item existed and where it was, which damage evidence '
        'alone does not.',
        'trigger': 'Alongside the damage photograph, as supporting context.',
        'conditions': {
            'missing': 'No prior-condition context has been offered.',
            'received': 'The item is shown undamaged and in place.',
            'invalid': 'The item cannot be matched to the damaged one.',
        },
        'media_usable': 'The same item is recognisable and its location is visible.',
        'media_insufficient': 'A frame in which the item cannot be matched.',
        'linkage': 'Supports ownership of the claimed item alongside the purchase evidence.',
    },
    'contents/contents-police-theft-report.pdf': {
        'purpose': 'Carries weight about the reported theft that the claimant cannot supply alone.',
        'trigger': 'After a theft is reported, on the issuing authority timetable.',
        'conditions': {
            'missing': 'The journey needs it and nothing has been offered.',
            'pending': 'It has been sought and the wait is on the issuing authority.',
            'unavailable': 'It has been sought and cannot currently be obtained.',
            'received': 'The issued report is attached.',
        },
        'media_usable': 'The event reference and the recorded item are legible.',
        'media_insufficient': 'A copy where the reference or the item cannot be read.',
        'linkage': 'Supports the claim fact "loss description" and attaches to the authority '
        'request that sought it.',
    },
    'contents/contents-purchase-receipt.pdf': {
        'purpose': 'Establishes that the claimed item belonged to the claimant, before value or '
        'entitlement can be discussed at all.',
        'trigger': 'When ownership of a specific item must be established, which contents cannot '
        'assume from the policy.',
        'conditions': {
            'missing': 'No ownership evidence has been offered.',
            'received': 'A receipt identifying the item and its purchase is attached.',
            'invalid': 'The retailer, amount, or item line cannot be read.',
            'disputed': 'It disagrees with another ownership record.',
        },
        'media_usable': 'The retailer, the item line, and the purchase date are all legible.',
        'media_insufficient': 'Any of those three unreadable or absent.',
        'linkage': 'Establishes ownership of the claimed item and supports its value.',
    },
    'contents/contents-receipt-illegible.pdf': {
        'purpose': 'Demonstrates ownership evidence that arrived and cannot do its job.',
        'trigger': 'On upload, when the check finds the content unusable.',
        'conditions': {
            'invalid': 'It arrived and the retailer, amount, and item line cannot be read.',
        },
        'media_usable': 'Not applicable; this instance exists to be unusable.',
        'media_insufficient': 'Retailer and amount unreadable, item line partly obscured.',
        'linkage': 'Was offered to establish ownership of a second item and does not do so.',
    },
    'contents/contents-valuation-expired.pdf': {
        'purpose': 'Demonstrates the expired condition: it was valid and time has invalidated it.',
        'trigger': 'When a valuation is required and the held one falls outside the accepted '
        'window.',
        'conditions': {
            'received': 'A valuation is attached.',
            'expired': 'Its valuation date falls outside the accepted window; a current valuation '
            'would restore it.',
        },
        'media_usable': 'The valuation date, the valued item, and the valuer are legible.',
        'media_insufficient': 'A valuation without a date, which cannot be aged at all.',
        'linkage': 'Supports the value of the claimed item, and expires against the accepted '
        'valuation window.',
    },
    'contents/contents-ownership-conflicting.pdf': {
        'purpose': 'Demonstrates the disputed condition between two materials rather than between '
        'a material and a stated fact.',
        'trigger': 'When a second ownership record disagrees with the first.',
        'conditions': {
            'received': 'A second ownership record is attached.',
            'disputed': 'It names a different purchase date to the receipt; both remain in the '
            'record and neither side is resolved.',
        },
        'media_usable': 'The item and the purchase date are legible enough to compare.',
        'media_insufficient': 'A record whose date cannot be read, which cannot conflict.',
        'linkage': 'Conflicts with the purchase receipt over the same claimed item and requires a '
        'staff decision.',
    },
    'contents/contents-replacement-assessment.pdf': {
        'purpose': 'The professional judgement that the item is replaced rather than repaired, and '
        'the input to the cost conversation.',
        'trigger': 'After a replacement assessment is authorised and the assessor reports.',
        'conditions': {
            'missing': 'No assessment has been sought.',
            'pending': 'The request is authorised and the wait is on the assessor.',
            'received': 'The assessment is attached.',
        },
        'media_usable': 'The assessor reference and the replacement judgement are legible.',
        'media_insufficient': 'An assessment without a reference or without a stated judgement.',
        'linkage': 'Attaches to the replacement assessment request that produced it.',
    },
    'contents/contents-consent-record.pdf': {
        'purpose': 'Makes the disclosure to the valuer auditable rather than assumed.',
        'trigger': 'Before any claim or purchase detail is disclosed to the valuer.',
        'conditions': {
            'missing': 'No authorisation has been recorded, so no disclosure may occur.',
            'received': 'The authorisation is recorded and names what was shared and why.',
        },
        'media_usable': 'The shared fields, the purpose, and the authorising claimant are named.',
        'media_insufficient': 'An authorisation that does not name what was shared or why.',
        'linkage': 'Attaches to the replacement assessment request it authorises.',
    },
}


ASSETS: tuple[Asset, ...] = (
    # --- motor -------------------------------------------------------------
    Asset(
        'motor/motor-incident-rear-bumper.jpg',
        'motor',
        'Incident evidence',
        'received',
        'Rear bumper damage',
        (
            'Vehicle rear quarter',
            'Impact damage to bumper and tail light',
            'Supports vehicle.damage_description',
        ),
        'photo',
    ),
    Asset(
        'motor/motor-incident-scene-wide.jpg',
        'motor',
        'Incident evidence',
        'received',
        'Incident scene, wide',
        (
            'Both vehicles in final position',
            'Road markings and kerb visible',
            'Supports position and extent',
        ),
        'photo',
    ),
    Asset(
        'motor/motor-incident-unreadable.jpg',
        'motor',
        'Incident evidence',
        'invalid',
        'Unusable photograph',
        (
            'Motion blur across the whole frame',
            'Damage not identifiable',
            'Arrived, but does not support the stated fact',
        ),
        'photo',
    ),
    Asset(
        'motor/motor-incident-conflicting-panel.jpg',
        'motor',
        'Incident evidence',
        'disputed',
        'Damage inconsistent with statement',
        (
            'Shows front nearside damage',
            'Claimant stated rear impact only',
            'Neither side resolved; staff decision required',
        ),
        'photo',
        (
            MaterialReference(
                CONFLICTS_WITH,
                FIELD_TARGET_PREFIX + 'vehicle.damage_description',
                'The photograph shows a damaged area the confirmed damage description does not '
                'name.',
                'unresolved',
            ),
        ),
    ),
    Asset(
        'motor/motor-police-event-report.pdf',
        'motor',
        'Authority or official report',
        'received',
        'Police event report',
        (
            'Event reference: SIMULATED',
            'Attending unit recorded both vehicles and the road position',
            'Issued outside Northwind and outside the claimant, on the issuer timetable',
        ),
        'document',
    ),
    Asset(
        'motor/motor-assessment-unavailable-notice.pdf',
        'motor',
        'Assessment or estimate',
        'received',
        'Third-party vehicle assessment cannot be provided',
        (
            'Assessor reference: SIMULATED',
            'The other party vehicle was not accessible at the recorded location',
            'A received answer to the assessment request, not the assessment itself',
        ),
        'document',
    ),
    Asset(
        'motor/motor-assessment-not-obtainable',
        'motor',
        'Assessment or estimate',
        'unavailable',
        'Third-party vehicle assessment, not obtainable',
        (
            'No assessment of the other party vehicle exists',
            'The assessor answered that one cannot be produced',
            'Sought and cannot currently be obtained; the reason is on the notice, not inferred',
        ),
        RECORD_KIND,
        (
            MaterialReference(
                ESTABLISHED_BY,
                'motor/motor-assessment-unavailable-notice.pdf',
                'The assessor answer recording why the third-party vehicle could not be assessed.',
            ),
        ),
    ),
    Asset(
        'motor/motor-assessment-v1.pdf',
        'motor',
        'Assessment or estimate',
        'superseded',
        'Vehicle damage assessment, first issue',
        (
            'Assessor reference: SIMULATED',
            'Repairable, parts pending',
            'Replaced by a later assessment; retained in the record',
        ),
        'document',
        (
            MaterialReference(
                SUPERSEDED_BY,
                'motor/motor-assessment-v2.pdf',
                'The revised assessment issued against the same assessor reference.',
            ),
        ),
    ),
    Asset(
        'motor/motor-assessment-v2.pdf',
        'motor',
        'Assessment or estimate',
        'received',
        'Vehicle damage assessment, revised',
        (
            'Assessor reference: SIMULATED',
            'Repairable, revised parts list',
            'Supersedes the first issue',
        ),
        'document',
    ),
    Asset(
        'motor/motor-consent-record.pdf',
        'motor',
        'Communication and consent record',
        'received',
        'Assessor disclosure authorisation',
        (
            'Shared: claim reference, location, damage description',
            'Purpose: request a vehicle damage assessment',
            'Authorised by the claimant linked to this claim',
        ),
        'document',
    ),
    # --- home --------------------------------------------------------------
    Asset(
        'home/home-incident-ceiling.jpg',
        'home',
        'Incident evidence',
        'received',
        'Water damage to ceiling',
        (
            'Staining across ceiling and cornice',
            'Active ingress at time of capture',
            'Supports property.affected_areas',
        ),
        'photo',
    ),
    Asset(
        'home/home-incident-wall-second-room.jpg',
        'home',
        'Incident evidence',
        'received',
        'Water damage, second room',
        (
            'Adjacent room, same event',
            'Shows extent beyond one area',
            'Supports property.affected_areas',
        ),
        'photo',
    ),
    Asset(
        'home/home-attendance-note-illegible.pdf',
        'home',
        'Incident evidence',
        'invalid',
        'Attendance note, unreadable',
        (
            'Third-party attendance record',
            'Text not legible in the supplied copy',
            'Arrived, but carries no usable detail',
        ),
        'document',
    ),
    Asset(
        'home/home-repair-assessment.pdf',
        'home',
        'Assessment or estimate',
        'received',
        'Repair assessment',
        (
            'Assessor reference: SIMULATED',
            'Ingress traced to the roof valley; two rooms affected',
            'Repairable; scope is the input to the cost conversation, not a decision',
        ),
        'document',
    ),
    Asset(
        'home/home-consent-record.pdf',
        'home',
        'Communication and consent record',
        'received',
        'Repair assessment disclosure authorisation',
        (
            'Shared: claim reference, address, affected areas',
            'Purpose: arrange a repair assessment',
            'Authorised by the claimant linked to this claim',
        ),
        'document',
    ),
    # --- contents ----------------------------------------------------------
    Asset(
        'contents/contents-item-damaged.jpg',
        'contents',
        'Incident evidence',
        'received',
        'Damaged item',
        (
            'Item as found after the event',
            'Visible impact damage to casing',
            'Identifies the item claimed for',
        ),
        'photo',
    ),
    Asset(
        'contents/contents-item-in-situ.jpg',
        'contents',
        'Incident evidence',
        'received',
        'Item before the event',
        (
            'Same item, undamaged, in place',
            'Supporting context rather than damage evidence',
            'Establishes the item existed and where',
        ),
        'photo',
    ),
    Asset(
        'contents/contents-police-theft-report.pdf',
        'contents',
        'Authority or official report',
        'received',
        'Police theft report',
        (
            'Event reference: SIMULATED',
            'Records the reported theft of the item claimed for',
            'Issued outside Northwind and outside the claimant, on the issuer timetable',
        ),
        'document',
    ),
    Asset(
        'contents/contents-authority-unavailable-notice.pdf',
        'contents',
        'Authority or official report',
        'received',
        'Investigation outcome cannot be issued',
        (
            'Event reference: SIMULATED',
            'The theft was recorded; no investigation outcome is held against this reference',
            'A received answer to the request, not the outcome report itself',
        ),
        'document',
    ),
    Asset(
        'contents/contents-authority-outcome-not-held',
        'contents',
        'Authority or official report',
        'unavailable',
        'Investigation outcome report, not held',
        (
            'No investigation outcome exists against the event reference',
            'The authority answered that none is held',
            'Sought and cannot currently be obtained; the reason is on the notice, not inferred',
        ),
        RECORD_KIND,
        (
            MaterialReference(
                ESTABLISHED_BY,
                'contents/contents-authority-unavailable-notice.pdf',
                'The authority answer recording that no outcome is held against this reference.',
            ),
        ),
    ),
    Asset(
        'contents/contents-purchase-receipt.pdf',
        'contents',
        'Identity and ownership evidence',
        'received',
        'Purchase receipt',
        ('Retailer: SIMULATED', 'Item and purchase date shown', 'Supports ownership and value'),
        'document',
    ),
    Asset(
        'contents/contents-receipt-illegible.pdf',
        'contents',
        'Identity and ownership evidence',
        'invalid',
        'Receipt, second item, illegible',
        (
            'Retailer and amount not readable',
            'Item line partially obscured',
            'Arrived, but does not carry the needed detail',
        ),
        'document',
    ),
    Asset(
        'contents/contents-valuation-expired.pdf',
        'contents',
        'Identity and ownership evidence',
        'expired',
        'Valuation certificate, expired',
        (
            'Valuation date outside the accepted window',
            'Was valid; no longer is',
            'A current valuation would restore it',
        ),
        'document',
    ),
    Asset(
        'contents/contents-ownership-conflicting.pdf',
        'contents',
        'Identity and ownership evidence',
        'disputed',
        'Second ownership record, conflicting',
        (
            'Names a different purchase date to the receipt',
            'Both documents remain in the record',
            'Neither side resolved; staff decision required',
        ),
        'document',
        (
            MaterialReference(
                CONFLICTS_WITH,
                'contents/contents-purchase-receipt.pdf',
                'The two ownership records give different purchase dates for the same item.',
                'unresolved',
            ),
        ),
    ),
    Asset(
        'contents/contents-replacement-assessment.pdf',
        'contents',
        'Assessment or estimate',
        'received',
        'Replacement assessment',
        (
            'Assessor reference: SIMULATED',
            'Replacement rather than repair',
            'Input to the cost conversation, not a decision',
        ),
        'document',
    ),
    Asset(
        'contents/contents-consent-record.pdf',
        'contents',
        'Communication and consent record',
        'received',
        'Valuation disclosure authorisation',
        (
            'Shared: claim reference, item description, purchase evidence',
            'Purpose: obtain a replacement assessment',
            'Authorised by the claimant linked to this claim',
        ),
        'document',
    ),
)


# --- writing, which is the only path that needs Pillow -----------------------


def _write_photo(asset: Asset, target: pathlib.Path) -> None:
    """Render one deliberately schematic stand-in, not an imitation photograph.

    Pillow is loaded through ``importlib`` rather than a static import. This module
    lives under ``backend/``, which ``mypy`` type-checks and which CI installs from
    ``backend/requirements.txt`` and ``backend/requirements-dev.txt``. Pillow belongs
    in neither: nothing in the application or the test suite reads it, and only
    regenerating these assets needs it. A static import would put a package the
    project does not declare into a type-checked tree, so the write path resolves it
    at call time and ``--check`` never reaches this function at all.
    """

    image_module = importlib.import_module('PIL.Image')
    draw_module = importlib.import_module('PIL.ImageDraw')
    Image = image_module
    ImageDraw = draw_module

    width, height = PHOTO_SIZE
    image = Image.new('RGB', PHOTO_SIZE, PAPER)
    draw = ImageDraw.Draw(image)

    # Schematic subject: blocked shapes rather than anything photographic.
    draw.rectangle([(70, 150), (width - 70, height - 130)], fill=FIELD, outline=MUTED, width=2)
    for offset in range(0, 5):
        y = 210 + offset * 60
        draw.line([(110, y), (width - 110, y)], fill=MUTED, width=1)

    # Only an unusable material is drawn unusable. The first version of this renderer put
    # these strokes on every photograph, meaning to say "this is a stand-in, not a
    # photograph" — but they read as "this one is spoiled", so the `invalid` instance and
    # the `received` ones were indistinguishable by eye. Section 5.2 reaches `invalid` by
    # artefact, which requires the artefact to demonstrate it, and a viewer could not tell
    # which of the four motor photographs was the unusable one. What says "stand-in" is
    # the banner, which every asset carries.
    if asset.condition in VISIBLY_UNUSABLE:
        draw.line([(140, 200), (width - 200, height - 190)], fill=ACCENT, width=6)
        draw.line([(width - 220, 220), (180, height - 200)], fill=ACCENT, width=4)
        for offset in range(0, 6):
            y = 175 + offset * 55
            draw.rectangle([(72, y), (width - 72, y + 16)], fill=PAPER)

    draw.rectangle([(0, 0), (width, 34)], fill=ACCENT)
    draw.text((14, 11), SIMULATED, fill=PAPER)
    draw.text((24, 58), asset.title, fill=INK)
    draw.text((24, 84), f'{asset.family} / {asset.material_class} / {asset.condition}', fill=MUTED)
    for index, line in enumerate(asset.lines):
        draw.text((24, height - 96 + index * 20), f'- {line}', fill=INK)
    # The banner is drawn for a human reader; the comment segment carries the same
    # statement plus the condition, where --check can read both back with the standard
    # library alone and hold the file to what the table says it demonstrates.
    image.save(
        target,
        'JPEG',
        quality=82,
        comment=f'{SIMULATED} | condition: {asset.condition}'.encode('ascii'),
    )


def _pdf_bytes(asset: Asset) -> bytes:
    """Write a minimal single-page PDF without a PDF library.

    Adding a PDF dependency for demonstration assets would put a runtime dependency
    behind demo data. A single page of Helvetica text is a small enough format to emit
    directly, and `--check` reopens the result rather than trusting this function.
    """

    lines = [
        (SIMULATED, 14),
        ('', 6),
        (asset.title, 18),
        (f'{asset.family} / {asset.material_class} / {asset.condition}', 11),
        ('', 8),
    ]
    lines.extend((f'- {line}', 12) for line in asset.lines)
    lines.extend(
        [
            ('', 10),
            ('Generated for the Northwind FNOL Validation Prototype.', 10),
            ('No real claimant, incident, retailer, or authority is represented.', 10),
        ]
    )

    content = ['BT', '/F1 12 Tf', '1 0 0 1 60 760 Tm', '16 TL']
    for text, size in lines:
        escaped = text.replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')
        content.append(f'/F1 {size} Tf')
        content.append(f'({escaped}) Tj' if escaped else '() Tj')
        content.append('T*')
    content.append('ET')
    stream = '\n'.join(content).encode('latin-1')
    compressed = zlib.compress(stream)

    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
        b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
        b'<< /Length '
        + str(len(compressed)).encode()
        + b' /Filter /FlateDecode >>\nstream\n'
        + compressed
        + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]

    out = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode()
    out += b'0000000000 65535 f \n'
    for offset in offsets[1:]:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += (
        f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    )
    return bytes(out)


# Section 5.2 of the catalogue, as a table rather than as prose, so a missing cell is a
# check failure rather than something a reader has to notice. `R` there means the
# condition must be *reachable* in that path's demonstration, not merely describable.
#
# A required cell is reached by absence, artefact, or record. Missing and Pending are
# reached by absence: nothing has been offered, or the wait is on someone, and there is
# no artefact because nothing came back. Present conditions are reached by the artefact
# that demonstrates them. Unavailable uses the third form described below.
REACHED_BY_ABSENCE = frozenset({'missing', 'pending'})

# The third form. Section 7 requires `unavailable` to be *established* and forbids it
# degrading into a claim of unavailability where none was. What establishes it is a
# received answer, which is its own material; the unavailable thing is what that answer
# refuses, and it has no bytes of its own. So the cell is reached by a record that cites
# the answer, never by the answer alone and never by a record citing nothing.
REACHED_BY_RECORD = frozenset({'unavailable'})

REQUIRED_COVERAGE: tuple[tuple[str, str, str], ...] = (
    # condition, claim path, material class ('*' means any class on that path)
    ('missing', 'motor', '*'),
    ('missing', 'home', '*'),
    ('missing', 'contents', '*'),
    ('pending', 'motor', 'Authority or official report'),
    ('pending', 'home', 'Assessment or estimate'),
    ('pending', 'contents', 'Authority or official report'),
    ('unavailable', 'motor', 'Assessment or estimate'),
    ('unavailable', 'contents', 'Authority or official report'),
    ('received', 'motor', 'Incident evidence'),
    ('received', 'home', 'Incident evidence'),
    ('received', 'contents', 'Incident evidence'),
    ('received', 'contents', 'Identity and ownership evidence'),
    ('invalid', 'motor', 'Incident evidence'),
    ('invalid', 'home', '*'),
    ('invalid', 'contents', 'Identity and ownership evidence'),
    ('superseded', 'motor', 'Assessment or estimate'),
    ('expired', 'contents', 'Identity and ownership evidence'),
    ('disputed', 'motor', 'Incident evidence'),
    ('disputed', 'contents', 'Identity and ownership evidence'),
)


def coverage_failures(materials: list[dict[str, object]]) -> list[str]:
    """Report every section 5.2 cell the produced set does not reach.

    Args:
        materials: The manifest's material entries.

    Returns:
        One message per unreached cell, empty when the matrix is satisfied.
    """

    demonstrated: set[tuple[str, str, str]] = set()
    occupiable: set[tuple[str, str, str]] = set()
    witnessed: set[tuple[str, str, str]] = set()
    for material in materials:
        path = str(material['claim_path'])
        material_class = str(material['material_class'])
        condition = str(material['demonstrates_condition'])
        cell = (condition, path, material_class)
        demonstrated.add(cell)
        if _relation_target(material, ESTABLISHED_BY) is not None:
            witnessed.add(cell)
        attributes = material.get('attributes')
        conditions = (
            attributes.get('conditions_it_can_occupy', {}) if isinstance(attributes, dict) else {}
        )
        for name in conditions:
            occupiable.add((str(name), path, material_class))

    failures: list[str] = []
    for condition, path, material_class in REQUIRED_COVERAGE:
        if condition in REACHED_BY_ABSENCE:
            reached, how = occupiable, 'recorded as occupiable'
        elif condition in REACHED_BY_RECORD:
            reached, how = witnessed, 'recorded against the answer that established'
        else:
            reached, how = demonstrated, 'demonstrated'
        if material_class == '*':
            satisfied = any(cell[0] == condition and cell[1] == path for cell in reached)
            where = 'any class'
        else:
            satisfied = (condition, path, material_class) in reached
            where = material_class
        if not satisfied:
            failures.append(
                f'catalogue section 5.2: {path} does not reach {condition} on {where}; '
                f'no material {how} it'
            )
    return failures


def _relation_target(material: dict[str, object], relation: str) -> str | None:
    """Return the target of one relation on a manifest entry, or `None` if absent."""

    references = material.get('references')
    if not isinstance(references, list):
        return None
    for reference in references:
        if isinstance(reference, dict) and reference.get('relation') == relation:
            target = reference.get('target')
            return str(target) if target is not None else None
    return None


def reference_failures(materials: list[dict[str, object]]) -> list[str]:
    """Report every material whose condition names a second thing it does not name.

    `unavailable`, `superseded`, and `disputed` are all statements about a relationship.
    A manifest that records one without saying what the other side is describes a
    situation neither surface can show: staff cannot see what is contested, and the
    claimant cannot be told what replaced what. This is section 7's honesty requirement
    checked rather than assumed.

    Args:
        materials: The manifest's material entries.

    Returns:
        One message per missing or unresolvable reference, empty when all are sound.
    """

    known = {str(material['path']) for material in materials}
    held_as = {str(material['path']): str(material.get('held_as', '')) for material in materials}
    failures: list[str] = []
    for material in materials:
        path = str(material['path'])
        condition = str(material['demonstrates_condition'])
        references = material.get('references')
        references = references if isinstance(references, list) else []
        required = REFERENCE_REQUIRED_BY_CONDITION.get(condition)
        if required is not None and _relation_target(material, required) is None:
            failures.append(
                f'{path}: demonstrates {condition} but names no {required} reference; '
                f'the condition names a second thing the manifest does not'
            )
        for reference in references:
            if not isinstance(reference, dict):
                continue
            target = str(reference.get('target', ''))
            relation = str(reference.get('relation', ''))
            if target.startswith(FIELD_TARGET_PREFIX):
                if relation != CONFLICTS_WITH:
                    failures.append(
                        f'{path}: {relation} names a claim field; only {CONFLICTS_WITH} may'
                    )
                continue
            if target not in known:
                failures.append(f'{path}: {relation} names {target}, which is not a material')
            elif target == path:
                failures.append(f'{path}: {relation} names itself')
            elif relation == ESTABLISHED_BY and held_as.get(target) == RECORD_KIND:
                failures.append(
                    f'{path}: {relation} names {target}, which holds no bytes either; an '
                    f'unavailability has to be established by something that arrived'
                )
    return failures


def provenance_failures(materials: list[dict[str, object]]) -> list[str]:
    """Report record and artefact provenance claims that contradict their representation.

    Args:
        materials: The manifest's material entries.

    Returns:
        One message per false or missing simulation-provenance claim.
    """

    failures: list[str] = []
    for material in materials:
        path = str(material['path'])
        held_as = str(material.get('held_as', ''))
        attributes = material.get('attributes')
        provenance = (
            attributes.get('provenance_and_verification', {})
            if isinstance(attributes, dict)
            else {}
        )
        provenance = provenance if isinstance(provenance, dict) else {}
        if held_as == RECORD_KIND:
            if 'stated_on_the_material' in provenance:
                failures.append(
                    f'{path}: record has no bytes on which a simulated-origin statement can appear'
                )
            if provenance.get('recorded_in_the_manifest') != SIMULATED:
                failures.append(
                    f'{path}: record does not carry its simulated origin in the manifest'
                )
        elif provenance.get('stated_on_the_material') != SIMULATED:
            failures.append(f'{path}: produced material does not declare its simulated origin')
    return failures


def _representation_failures(materials: list[dict[str, object]]) -> list[str]:
    """Report no-byte records that claim artefact-only source or visibility semantics.

    Args:
        materials: The manifest's material entries.

    Returns:
        One message per false or missing record-representation field.
    """

    failures: list[str] = []
    for material in materials:
        if material.get('held_as') != RECORD_KIND:
            continue
        path = str(material['path'])
        attributes = material.get('attributes')
        attributes = attributes if isinstance(attributes, dict) else {}
        source = attributes.get('source_and_stakeholder')
        source = source if isinstance(source, dict) else {}
        visibility = attributes.get('consent_and_visibility')
        visibility = visibility if isinstance(visibility, dict) else {}

        if source.get('provided_by') != 'none':
            failures.append(f'{path}: no-byte record must not claim an artefact was provided')
        if source.get('expected_from') != 'external_party':
            failures.append(f'{path}: no-byte record must name the expected external source')
        if source.get('recorded_by') != 'northwind':
            failures.append(f'{path}: no-byte record must name Northwind as its recorder')
        if visibility.get('claimant_can_open_artefact') is not False:
            failures.append(f'{path}: claimant must not be offered a nonexistent artefact')
        if visibility.get('staff_can_open_artefact') is not False:
            failures.append(f'{path}: staff must not be offered a nonexistent artefact')
        if visibility.get('disclosure_requires_consent') is not True:
            failures.append(
                f'{path}: no-byte record must retain the authorisation boundary for disclosure'
            )
    return failures


REQUIRED_ATTRIBUTES = (
    'purpose',
    'applicable_paths_and_trigger',
    'source_and_stakeholder',
    'conditions_it_can_occupy',
    'media_and_quality_requirements',
    'provenance_and_verification',
    'consent_and_visibility',
    'linkage',
    'behaviour_when_not_usable',
    'retention',
)


def material_attributes(asset: Asset) -> dict[str, object]:
    """Answer every attribute section 3 of the catalogue requires of this material.

    Section 3 says every catalogued material must answer all of them, and that an
    unanswered one is an open decision recorded in section 9 rather than a blank filled
    in during production. So each entry here is either an answer or a named dependency,
    never an invented value.

    Some answers belong to the material class rather than to one asset — who provides it,
    what disclosure requires, how long it is kept — and are merged from `CLASS_PROFILE`.
    Behaviour when a material is not usable is a property of the condition, from
    section 7, and is merged from `CONDITION_BEHAVIOUR` for exactly the conditions this
    material can occupy.

    Args:
        asset: The produced material to describe.

    Returns:
        One mapping answering each of the ten required attributes.

    Raises:
        KeyError: The asset or its class has no recorded detail, which `--check` reports
            rather than letting the manifest ship incomplete.
    """

    detail = ASSET_DETAIL[asset.path]
    profile = CLASS_PROFILE[asset.material_class]
    representation_profile = (
        profile if asset.has_artefact else RECORD_REPRESENTATION_PROFILE[asset.material_class]
    )
    conditions = detail['conditions']
    assert isinstance(conditions, dict)
    if asset.has_artefact:
        provenance_and_verification = {
            'origin': 'generated for the Validation Prototype; no real incident, authority, '
            'retailer, or assessor is represented',
            'stated_on_the_material': SIMULATED,
            'checking_received': 'none beyond structural checks. That the file exists, is the '
            'declared type, and carries its origin statement is not verification of its content.',
        }
    else:
        provenance_and_verification = {
            'origin': 'generated no-byte record for the Validation Prototype; no real incident, '
            'authority, retailer, or assessor is represented',
            'recorded_in_the_manifest': SIMULATED,
            'checking_received': 'structural checks confirm that no file exists at this record '
            'path and that its established_by reference resolves to the received answer. This '
            'does not verify provider content or make the record a real external result.',
        }

    return {
        'purpose': detail['purpose'],
        'applicable_paths_and_trigger': {
            'paths': [asset.family],
            'trigger': detail['trigger'],
        },
        'source_and_stakeholder': representation_profile['source_and_stakeholder'],
        'conditions_it_can_occupy': {
            name: {
                'means_for_this_material': meaning,
                'persisted_mapping': _unresolved(
                    CONDITION_MAPPING_PENDING, 'backend contract work'
                ),
            }
            for name, meaning in conditions.items()
        },
        'media_and_quality_requirements': {
            'usable': detail['media_usable'],
            'insufficient': detail['media_insufficient'],
        },
        'provenance_and_verification': provenance_and_verification,
        'consent_and_visibility': representation_profile['consent_and_visibility'],
        'linkage': {
            'attaches_to': detail['linkage'],
            'registered_field': _unresolved(REGISTERED_FIELD_PENDING, 'P2'),
        },
        'behaviour_when_not_usable': {
            name: CONDITION_BEHAVIOUR[name] for name in conditions if name in CONDITION_BEHAVIOUR
        },
        'retention': profile['retention'],
    }


def manifest_document() -> dict[str, object]:
    """Build the machine-readable record of what was produced.

    This describes the materials themselves: what each one is, which claim path it
    belongs to, which catalogue condition it currently demonstrates, every attribute
    section 3 requires of it, what other material its condition depends on, and that its
    origin is simulated. It deliberately carries no Claim, Evidence, or storage reference;
    the association of a material with a claim record is issue #602.

    `media_type` is `null` and `held_as` is `record` for a material with no bytes of its
    own. Those entries are not gaps in production: an unavailable material is precisely
    the one that does not exist, and the manifest has to be able to say so without
    inventing a file to say it with.

    Returns:
        The manifest as it should be written to `materials.json`.
    """

    return {
        'schema': MANIFEST_SCHEMA,
        'produced_by': 'backend/demo_data/materials/generate_materials.py',
        'specified_by': 'docs/demonstration-material-catalogue.md',
        'required_attributes': list(REQUIRED_ATTRIBUTES),
        'origin': 'simulated',
        'origin_statement': SIMULATED,
        'materials': [
            {
                'path': asset.path,
                'claim_path': asset.family,
                'material_class': asset.material_class,
                'demonstrates_condition': asset.condition,
                'held_as': asset.kind if asset.has_artefact else RECORD_KIND,
                'media_type': asset.media_type,
                'title': asset.title,
                'described_as': list(asset.lines),
                'references': [reference.as_manifest_entry() for reference in asset.references],
                'simulated': True,
                'attributes': material_attributes(asset),
            }
            for asset in ASSETS
        ],
    }


def write_all() -> list[tuple[str, int]]:
    written: list[tuple[str, int]] = []
    for asset in ASSETS:
        if not asset.has_artefact:
            continue
        target = HERE / asset.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if asset.kind == 'photo':
            _write_photo(asset, target)
        else:
            target.write_bytes(_pdf_bytes(asset))
        written.append((asset.path, target.stat().st_size))
    MANIFEST.write_text(
        json.dumps(manifest_document(), indent=2, ensure_ascii=True) + '\n',
        encoding='utf-8',
        newline='\n',
    )
    written.append((MANIFEST.name, MANIFEST.stat().st_size))
    return written


# --- verification, which uses the standard library alone ---------------------


def jpeg_facts(data: bytes) -> tuple[tuple[int, int], list[str]]:
    """Return the JPEG's pixel size and its comment segments, parsing the markers."""

    if not data.startswith(b'\xff\xd8\xff') or not data.rstrip(b'\x00').endswith(b'\xff\xd9'):
        raise ValueError('not a JPEG envelope')
    size = (0, 0)
    comments: list[str] = []
    index = 2
    while index < len(data) - 1:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if marker == 0xDA:  # start of scan; entropy-coded data follows
            break
        length = int.from_bytes(data[index + 2 : index + 4], 'big')
        segment = data[index + 4 : index + 2 + length]
        if marker == 0xFE:
            comments.append(segment.split(b'\x00', 1)[0].decode('latin-1'))
        elif 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            size = (
                int.from_bytes(segment[3:5], 'big'),
                int.from_bytes(segment[1:3], 'big'),
            )
        index += 2 + length
    return size, comments


def pdf_page_text(data: bytes) -> str:
    """Return the decompressed page-content text of a single-page PDF."""

    if not data.startswith(b'%PDF-1.4') or not data.rstrip().endswith(b'%%EOF'):
        raise ValueError('not a PDF envelope')
    parts: list[str] = []
    marker = b'stream\n'
    start = data.find(marker)
    while start != -1:
        end = data.find(b'\nendstream', start)
        if end == -1:
            break
        with contextlib.suppress(zlib.error):
            parts.append(zlib.decompress(data[start + len(marker) : end]).decode('latin-1'))
        start = data.find(marker, end)
    return '\n'.join(parts)


def check_all() -> tuple[list[str], list[str]]:
    """Verify every asset exists, is the declared type, and states its simulated origin.

    A material held as a record has nothing to open, so the check is the opposite one: a
    file must *not* be there. An unavailable material that quietly acquired bytes would be
    the defect this whole shape exists to prevent, back again in the other direction.

    Returns:
        Human-readable reports for valid materials and all validation failures.
    """

    reports: list[str] = []
    failures: list[str] = []
    for asset in ASSETS:
        target = HERE / asset.path
        if not asset.has_artefact:
            if target.exists():
                failures.append(f'{asset.path}: held as a record but a file exists at its path')
                continue
            established_by = next(
                (
                    reference.target
                    for reference in asset.references
                    if reference.relation == ESTABLISHED_BY
                ),
                None,
            )
            reports.append(f'{"record":>7}    {"(no bytes)":<16} {asset.path}')
            reports[-1] += f'  established by {established_by}'
            continue
        if not target.exists() or target.stat().st_size == 0:
            failures.append(f'{asset.path}: missing or empty')
            continue
        data = target.read_bytes()
        try:
            if asset.kind == 'photo':
                size, comments = jpeg_facts(data)
                if size != PHOTO_SIZE:
                    failures.append(f'{asset.path}: {size[0]}x{size[1]}, expected 900x640')
                    continue
                if not any(SIMULATED in comment for comment in comments):
                    failures.append(f'{asset.path}: no simulated-origin comment segment')
                    continue
                stated = f'condition: {asset.condition}'
                if not any(stated in comment for comment in comments):
                    failures.append(
                        f'{asset.path}: the file does not state the condition the table '
                        f'gives it ({asset.condition})'
                    )
                    continue
                detail = f'JPEG {size[0]}x{size[1]}, origin and condition in comment segment'
            else:
                text = pdf_page_text(data)
                if SIMULATED not in text:
                    failures.append(f'{asset.path}: no simulated-origin statement in page text')
                    continue
                detail = 'PDF-1.4 single page, origin in page text'
        except ValueError as error:
            failures.append(f'{asset.path}: {error}')
            continue
        reports.append(f'{target.stat().st_size:>7} B  {asset.media_type or "":<16} {asset.path}')
        reports[-1] += f'  {detail}'

    # Every asset must answer section 3 in the tables, not only in the written manifest,
    # so a missing entry is reported here rather than raising while the manifest is built.
    for asset in ASSETS:
        if asset.path not in ASSET_DETAIL:
            failures.append(f'{asset.path}: has no entry in ASSET_DETAIL')
        if asset.material_class not in CLASS_PROFILE:
            failures.append(f'{asset.path}: class {asset.material_class} has no CLASS_PROFILE')
        if not asset.has_artefact and asset.material_class not in RECORD_REPRESENTATION_PROFILE:
            failures.append(
                f'{asset.path}: class {asset.material_class} has no record representation profile'
            )
    for path in ASSET_DETAIL:
        if path not in {asset.path for asset in ASSETS}:
            failures.append(f'{path}: ASSET_DETAIL describes a material that is not produced')

    if not MANIFEST.exists():
        failures.append(f'{MANIFEST.name}: missing')
        return reports, failures

    stored = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if not failures and stored != manifest_document():
        failures.append(f'{MANIFEST.name}: does not match the ASSETS table; regenerate')

    for material in stored.get('materials', []):
        attributes = material.get('attributes') or {}
        for name in REQUIRED_ATTRIBUTES:
            answer = attributes.get(name)
            if answer is None or answer == {} or answer == '':
                failures.append(
                    f'{material.get("path")}: does not answer the required attribute {name}'
                )
        occupied = attributes.get('conditions_it_can_occupy') or {}
        demonstrated = material.get('demonstrates_condition')
        if demonstrated and demonstrated not in occupied:
            failures.append(
                f'{material.get("path")}: demonstrates {demonstrated}, which is not among the '
                'conditions it records itself as able to occupy'
            )
        unknown = sorted(set(occupied) - set(CONDITION_BEHAVIOUR))
        if unknown:
            failures.append(
                f'{material.get("path")}: names conditions the catalogue does not define: '
                f'{", ".join(unknown)}'
            )

    failures.extend(coverage_failures(stored.get('materials', [])))
    failures.extend(reference_failures(stored.get('materials', [])))
    failures.extend(provenance_failures(stored.get('materials', [])))
    failures.extend(_representation_failures(stored.get('materials', [])))
    return reports, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help='verify each produced asset opens, is the declared type, states its simulated '
        'origin, answers every attribute the catalogue requires, names whatever second '
        'material its condition depends on, and reaches every condition the catalogue '
        'requires of its path',
    )
    args = parser.parse_args()

    if not args.check:
        for path, size in write_all():
            print(f'{size:>8} bytes  {path}')
        return 0

    reports, failures = check_all()
    for line in reports:
        print(line)
    print()
    if failures:
        print(f'{len(failures)} problem(s):')
        for line in failures:
            print(f'  {line}')
        return 1
    artefacts = sum(1 for asset in ASSETS if asset.has_artefact)
    records = len(ASSETS) - artefacts
    print(
        f'{len(reports)} materials verified: {artefacts} produced assets each open, are the '
        f'declared media type and state their simulated origin on their own face, and {records} '
        'are held as records with no bytes, an arrived answer behind each, and their simulated '
        'origin recorded in the manifest instead of claimed on a surface they do not have; every '
        f'material answers all {len(REQUIRED_ATTRIBUTES)} required attributes and names whatever '
        'second material its condition depends on; the manifest matches the asset table; all '
        f'{len(REQUIRED_COVERAGE)} conditions section 5.2 requires are reached'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
