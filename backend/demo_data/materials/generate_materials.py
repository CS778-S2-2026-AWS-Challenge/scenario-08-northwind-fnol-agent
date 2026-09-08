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


@dataclass(frozen=True, slots=True)
class Asset:
    """One material to produce, described in the catalogue's own vocabulary."""

    path: str
    family: str
    material_class: str
    condition: str
    title: str
    lines: tuple[str, ...]
    kind: str  # 'photo' or 'document'

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.kind]


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
    draw.line([(140, 200), (width - 200, height - 190)], fill=ACCENT, width=6)
    draw.line([(width - 220, 220), (180, height - 200)], fill=ACCENT, width=4)

    draw.rectangle([(0, 0), (width, 34)], fill=ACCENT)
    draw.text((14, 11), SIMULATED, fill=PAPER)
    draw.text((24, 58), asset.title, fill=INK)
    draw.text((24, 84), f'{asset.family} / {asset.material_class} / {asset.condition}', fill=MUTED)
    for index, line in enumerate(asset.lines):
        draw.text((24, height - 96 + index * 20), f'- {line}', fill=INK)
    # The banner is drawn for a human reader; the comment segment carries the same
    # statement where --check can read it back with the standard library alone.
    image.save(target, 'JPEG', quality=82, comment=SIMULATED.encode('ascii'))


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


def manifest_document() -> dict[str, object]:
    """Build the machine-readable record of what was produced.

    This describes the materials themselves: what each one is, which claim path it
    belongs to, which catalogue condition it demonstrates, and that its origin is
    simulated. It deliberately carries no Claim, Evidence, or storage reference; the
    association of a material with a claim record is issue #602.
    """

    return {
        'schema': MANIFEST_SCHEMA,
        'produced_by': 'backend/demo_data/materials/generate_materials.py',
        'specified_by': 'docs/demonstration-material-catalogue.md',
        'origin': 'simulated',
        'origin_statement': SIMULATED,
        'materials': [
            {
                'path': asset.path,
                'claim_path': asset.family,
                'material_class': asset.material_class,
                'condition': asset.condition,
                'media_type': asset.media_type,
                'title': asset.title,
                'described_as': list(asset.lines),
                'simulated': True,
            }
            for asset in ASSETS
        ],
    }


def write_all() -> list[tuple[str, int]]:
    written: list[tuple[str, int]] = []
    for asset in ASSETS:
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
    """Verify every asset exists, is the declared type, and states its simulated origin."""

    reports: list[str] = []
    failures: list[str] = []
    for asset in ASSETS:
        target = HERE / asset.path
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
                if SIMULATED not in comments:
                    failures.append(f'{asset.path}: no simulated-origin comment segment')
                    continue
                detail = f'JPEG {size[0]}x{size[1]}, origin in comment segment'
            else:
                text = pdf_page_text(data)
                if SIMULATED not in text:
                    failures.append(f'{asset.path}: no simulated-origin statement in page text')
                    continue
                detail = 'PDF-1.4 single page, origin in page text'
        except ValueError as error:
            failures.append(f'{asset.path}: {error}')
            continue
        reports.append(f'{target.stat().st_size:>7} B  {asset.media_type:<16} {asset.path}')
        reports[-1] += f'  {detail}'

    if not MANIFEST.exists():
        failures.append(f'{MANIFEST.name}: missing')
    else:
        stored = json.loads(MANIFEST.read_text(encoding='utf-8'))
        if stored != manifest_document():
            failures.append(f'{MANIFEST.name}: does not match the ASSETS table; regenerate')
    return reports, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--check',
        action='store_true',
        help='verify each asset opens, is the declared type, and states its simulated origin',
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
    print(
        f'{len(reports)} assets verified: each opens, is the declared media type, '
        'and states its simulated origin; the manifest matches the asset table'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
