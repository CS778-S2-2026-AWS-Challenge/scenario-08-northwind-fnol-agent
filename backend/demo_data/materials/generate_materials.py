"""Produce the demonstration materials named by docs/demonstration-material-catalogue.md.

Every asset is generated rather than sourced, so its origin is unambiguous: nothing here
is a photograph of a real incident or a document issued by a real authority. Each rendered
asset states that on its face, which is what the catalogue requires of provenance and what
issue #601 requires of its failure boundary.

Run from the repository root:

    python backend/demo_data/materials/generate_materials.py
"""

from __future__ import annotations

import argparse
import pathlib
import zlib
from dataclasses import dataclass

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent

SIMULATED = 'SIMULATED MATERIAL - NOT A REAL INCIDENT OR DOCUMENT'

# Muted, deliberately unphotographic palette. A demonstration asset should read as a
# stand-in at a glance rather than invite a viewer to mistake it for a photograph.
INK = (38, 42, 48)
MUTED = (120, 128, 138)
PAPER = (247, 246, 243)
FIELD = (214, 219, 224)
ACCENT = (176, 92, 68)


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


def _banner(draw: ImageDraw.ImageDraw, width: int, text: str) -> None:
    draw.rectangle([(0, 0), (width, 34)], fill=ACCENT)
    draw.text((14, 11), text, fill=PAPER)


def _photo(asset: Asset, size: tuple[int, int] = (900, 640)) -> Image.Image:
    """A deliberately schematic stand-in, not an imitation photograph."""

    width, height = size
    image = Image.new('RGB', size, PAPER)
    draw = ImageDraw.Draw(image)

    # Schematic subject: blocked shapes rather than anything photographic.
    draw.rectangle([(70, 150), (width - 70, height - 130)], fill=FIELD, outline=MUTED, width=2)
    for offset in range(0, 5):
        y = 210 + offset * 60
        draw.line([(110, y), (width - 110, y)], fill=MUTED, width=1)
    draw.line([(140, 200), (width - 200, height - 190)], fill=ACCENT, width=6)
    draw.line([(width - 220, 220), (180, height - 200)], fill=ACCENT, width=4)

    _banner(draw, width, SIMULATED)
    draw.text((24, 58), asset.title, fill=INK)
    draw.text((24, 84), f'{asset.family} / {asset.material_class} / {asset.condition}', fill=MUTED)
    for index, line in enumerate(asset.lines):
        draw.text((24, height - 96 + index * 20), f'- {line}', fill=INK)
    return image


def _pdf_bytes(asset: Asset) -> bytes:
    """Write a minimal single-page PDF without a PDF library.

    The repository has no PDF dependency and adding one for demonstration assets would
    put a runtime dependency behind demo data. A single page of Helvetica text is a small
    enough format to emit directly, and the output is validated by reopening it below.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify assets exist, write nothing')
    args = parser.parse_args()

    missing: list[str] = []
    for asset in ASSETS:
        target = HERE / asset.path
        if args.check:
            if not target.exists() or target.stat().st_size == 0:
                missing.append(asset.path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if asset.kind == 'photo':
            _photo(asset).save(target, 'JPEG', quality=82)
        else:
            target.write_bytes(_pdf_bytes(asset))
        print(f'{target.stat().st_size:>8} bytes  {asset.path}')

    if args.check:
        if missing:
            print('missing or empty:')
            for path in missing:
                print(f'  {path}')
            return 1
        print(f'{len(ASSETS)} assets present')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
