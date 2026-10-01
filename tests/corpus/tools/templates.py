"""Render synthetic documents for the controlled corpus as PDF files.

Each renderer takes a plain dict and writes a PDF. Every page carries the synthetic footer. The
renderers return the list of field values they printed, so the checker can compare documents with
the fact sheet without parsing PDF text.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from tests.corpus.tools.corpus_lists import FOOTER

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle(
    'body', parent=STYLES['Normal'], fontName='Helvetica', fontSize=10, leading=14
)
SMALL = ParagraphStyle(
    'small', parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor('#444444')
)
TITLE = ParagraphStyle(
    'title', parent=BODY, fontName='Helvetica-Bold', fontSize=16, leading=20, spaceAfter=6
)
ISSUER = ParagraphStyle('issuer', parent=BODY, fontName='Helvetica-Bold', fontSize=12, leading=15)


class _FooterCanvas(rl_canvas.Canvas):  # type: ignore[misc]  # reportlab ships no stubs, so Canvas is Any
    """Draws the footer after layout, so every page can say 'Page X of N'.

    A page removed later (the missing_page variant) still shows the original count, so the gap is
    visible on the document itself.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self.saveState()
            self.setFont('Helvetica', 7.5)
            self.setFillColor(colors.HexColor('#666666'))
            self.drawString(18 * mm, 10 * mm, FOOTER)
            self.drawRightString(A4[0] - 18 * mm, 10 * mm, f'Page {self._pageNumber} of {total}')
            self.restoreState()
            super().showPage()
        super().save()


def _table(
    rows: Sequence[Sequence[str | Paragraph]], widths: Sequence[float], header: bool = False
) -> Table:
    table = Table(rows, colWidths=widths)
    style = [
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 9.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#BBBBBB')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 9.5),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EEEEEE')),
        ]
    else:
        style += [('FONT', (0, 0), (0, -1), 'Helvetica-Bold', 9.5)]
    table.setStyle(TableStyle(style))
    return table


def _build(path: str, story: list[Flowable]) -> None:
    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
    )
    doc.build(story, canvasmaker=_FooterCanvas)


def _money(value: float) -> str:
    return f'${value:,.2f}'


def _key_values(pairs: Iterable[tuple[str, object]]) -> Table:
    return _table([[k, Paragraph(str(v), BODY)] for k, v in pairs], [55 * mm, 119 * mm])


def repair_quote(data: dict[str, Any], path: str) -> dict[str, Any]:
    """Two pages: page 1 has the header and itemised work, page 2 the totals and terms."""
    items = data['items']
    subtotal = sum(i['amount'] for i in items)
    gst = round(subtotal * 0.15, 2)
    story = [
        Paragraph(data['issuer'], ISSUER),
        Paragraph(data['issuer_address'], SMALL),
        Spacer(1, 8),
        Paragraph('Repair quote', TITLE),
        _key_values(
            [
                ('Quote number', data['quote_number']),
                ('Quote date', data['quote_date']),
                ('Valid until', data['valid_until']),
                ('Customer', data['customer']),
                ('Subject', data['subject']),
            ]
        ),
        Spacer(1, 10),
        _table(
            [['Work item', 'Qty', 'Amount (excl. GST)']]
            + [
                [Paragraph(i['description'], BODY), str(i.get('qty', 1)), _money(i['amount'])]
                for i in items
            ],
            [120 * mm, 14 * mm, 40 * mm],
            header=True,
        ),
        PageBreak(),
        Paragraph('Totals and terms', TITLE),
        _key_values(
            [
                ('Subtotal', _money(subtotal)),
                ('GST (15%)', _money(gst)),
                ('Total including GST', _money(subtotal + gst)),
            ]
        ),
        Spacer(1, 10),
        Paragraph(
            data.get(
                'terms',
                'This quote is an estimate based on a visual inspection. '
                'Hidden damage found during repair will be quoted separately.',
            ),
            BODY,
        ),
        Spacer(1, 16),
        Paragraph(f'Prepared by: {data["prepared_by"]}', BODY),
    ]
    _build(path, story)
    return {
        'quote_date': data['quote_date'],
        'valid_until': data['valid_until'],
        'subject': data['subject'],
        'total_incl_gst': round(subtotal + gst, 2),
        'customer': data['customer'],
    }


def policy_schedule(data: dict[str, Any], path: str) -> dict[str, Any]:
    rows = (
        [
            ('Policy number', data['policy_number']),
            ('Policyholder', data['policyholder']),
            ('Policy wording', data['wording']),
            ('Cover', data['cover']),
            ('Period of insurance', data['period']),
        ]
        + [(k, v) for k, v in data['insured'].items()]
        + [
            ('Excess', data['excess']),
        ]
        + [(k, v) for k, v in data.get('extra', {}).items()]
    )
    story = [
        Paragraph('Northwind Insurance (fictional insurer)', ISSUER),
        Spacer(1, 8),
        Paragraph('Policy schedule', TITLE),
        _key_values(rows),
        Spacer(1, 10),
        Paragraph(
            'This schedule must be read with the policy wording named above. '
            'The wording and this schedule together describe the cover.',
            SMALL,
        ),
    ]
    _build(path, story)
    return {
        'policy_number': data['policy_number'],
        'policyholder': data['policyholder'],
        **{k: v for k, v in data['insured'].items()},
    }


def receipt(data: dict[str, Any], path: str) -> dict[str, Any]:
    """A receipt. With 'reprinted_on' it is a reprint that shows both the purchase date \
and the print date."""
    items = data['items']
    total = sum(i['amount'] for i in items)
    header = [('Invoice number', data['invoice_number']), ('Date of purchase', data['date'])]
    if data.get('reprinted_on'):
        header.append(('Reprinted on', data['reprinted_on']))
    header.append(('Customer', data['customer']))
    title = (
        'Tax invoice / receipt (reprint)' if data.get('reprinted_on') else 'Tax invoice / receipt'
    )
    story = [
        Paragraph(data['issuer'], ISSUER),
        Paragraph(data['issuer_address'], SMALL),
        Spacer(1, 8),
        Paragraph(title, TITLE),
        _key_values(header),
        Spacer(1, 10),
        _table(
            [['Item', 'Serial number', 'Amount (incl. GST)']]
            + [
                [
                    Paragraph(i['description'], BODY),
                    i.get('serial', 'Not recorded'),
                    _money(i['amount']),
                ]
                for i in items
            ],
            [95 * mm, 40 * mm, 39 * mm],
            header=True,
        ),
        Spacer(1, 8),
        _key_values([('Total paid', _money(total)), ('Payment method', data['payment_method'])]),
    ]
    _build(path, story)
    printed = {
        'date': data['date'],
        'customer': data['customer'],
        'items': [i['description'] for i in items],
        'serials': [i.get('serial') for i in items],
        'total': total,
    }
    if data.get('reprinted_on'):
        printed['reprinted_on'] = data['reprinted_on']
    return printed


def police_reference_record(data: dict[str, Any], path: str) -> dict[str, Any]:
    story = [
        Paragraph('Police report confirmation (claimant copy)', TITLE),
        Paragraph(
            'Synthetic record for testing. '
            'Not issued by New Zealand Police and not in any Police format.',
            SMALL,
        ),
        Spacer(1, 8),
        _key_values(
            [
                ('Event reference', data['event_reference']),
                ('Reported on', data['reported_on']),
                ('Reported by', data['reported_by']),
                ('How reported', data['how_reported']),
                ('Incident summary as reported', data['summary']),
            ]
        ),
    ]
    _build(path, story)
    return {
        'event_reference': data['event_reference'],
        'reported_on': data['reported_on'],
        'reported_by': data['reported_by'],
    }


def attendance_note(data: dict[str, Any], path: str) -> dict[str, Any]:
    story = [
        Paragraph(data['issuer'], ISSUER),
        Paragraph(data['issuer_address'], SMALL),
        Spacer(1, 8),
        Paragraph('Attendance note', TITLE),
        _key_values(
            [
                ('Job number', data['job_number']),
                ('Attended', data['attended']),
                ('Address', data['address']),
                ('Customer', data['customer']),
                ('Found', data['found']),
                ('Work done', data['work_done']),
                ('Follow-up', data['follow_up']),
            ]
        ),
    ]
    _build(path, story)
    return {'attended': data['attended'], 'address': data['address'], 'customer': data['customer']}


def assessment_report(data: dict[str, Any], path: str) -> dict[str, Any]:
    """An assessor's report: what was inspected, findings and an estimate. \
No coverage or liability decision."""
    story = [
        Paragraph(data['issuer'], ISSUER),
        Paragraph(data['issuer_address'], SMALL),
        Spacer(1, 8),
        Paragraph('Assessment report', TITLE),
        _key_values(
            [
                ('Report number', data['report_number']),
                ('Inspection date', data['report_date']),
                ('Customer', data['customer']),
                ('Item inspected', data['subject']),
                ('Findings', data['findings']),
                ('Estimated repair cost (incl. GST)', _money(data['estimate'])),
                ('Recommendation', data.get('recommendation', 'Repair as quoted.')),
                ('Assessor', data['assessor']),
            ]
        ),
        Spacer(1, 10),
        Paragraph(
            'This report records the physical inspection only. '
            'It makes no coverage or liability decision.',
            SMALL,
        ),
    ]
    _build(path, story)
    return {
        'report_date': data['report_date'],
        'subject': data['subject'],
        'customer': data['customer'],
        'estimate': data['estimate'],
    }


def unavailable_notice(data: dict[str, Any], path: str) -> dict[str, Any]:
    story = [
        Paragraph('Material not yet available', TITLE),
        _key_values(
            [
                ('Material', data['material']),
                ('Reason', data['reason']),
                ('Expected', data['expected']),
            ]
        ),
    ]
    _build(path, story)
    return {'material': data['material']}


# Page each printed field sits on, where it is not page 1. A missing_page variant keeps only the
# fields on its remaining pages, so a total on a removed page is not recorded as printed.
FIELD_PAGES = {'repair_quote': {'total_incl_gst': 2}}

RENDERERS = {
    'repair_quote': repair_quote,
    'policy_schedule': policy_schedule,
    'receipt': receipt,
    'police_reference_record': police_reference_record,
    'attendance_note': attendance_note,
    'assessment_report': assessment_report,
    'unavailable_notice': unavailable_notice,
}
