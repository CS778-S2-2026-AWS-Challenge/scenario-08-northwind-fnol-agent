import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import TurnAttachments from './TurnAttachments.jsx'

const fact = (fieldCode, label, value, toCheck) => ({
  fieldCode,
  label,
  value,
  toCheck,
  field: { value, status: toCheck ? 'proposed' : 'confirmed' },
})

describe('TurnAttachments', () => {
  it('shows nothing for a reply that opened nothing', () => {
    const { container } = render(<TurnAttachments />)
    expect(container).toBeEmptyDOMElement()
  })

  it('starts with a compact disclosure and confirms proposed facts while collapsed', async () => {
    const user = userEvent.setup()
    const onConfirmFacts = vi.fn()
    render(
      <TurnAttachments
        facts={[
          fact('claim.product_family', 'Claim type', 'motor', true),
          fact('incident.location', 'Incident location', 'Queen Street', true),
        ]}
        onConfirmFacts={onConfirmFacts}
      />,
    )

    const card = screen.getByRole('region', { name: 'Captured information' })
    expect(within(card).getByText('Noted 2 details')).toBeVisible()
    expect(within(card).getByText('Noted 2 details').previousElementSibling).toHaveAttribute('aria-hidden', 'true')
    const disclosure = within(card).getByRole('button', { name: 'Review' })
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(disclosure.getAttribute('aria-controls'))).not.toBeVisible()
    expect(within(card).getByText('Claim type')).not.toBeVisible()
    expect(within(card).getByRole('button', { name: 'Looks right' })).toBeVisible()

    await user.click(within(card).getByRole('button', { name: 'Looks right' }))
    expect(onConfirmFacts).toHaveBeenCalledWith(['claim.product_family', 'incident.location'])
  })

  it('expands the current-turn details and preserves inline editing', async () => {
    const user = userEvent.setup()
    const onSaveFact = vi.fn().mockResolvedValue(true)
    render(
      <TurnAttachments
        facts={[fact('claim.product_family', 'Claim type', 'motor', false)]}
        fieldInputs={{
          'claim.product_family': {
            value_type: 'enum',
            allowed_values: ['motor', 'home', 'contents'],
          },
        }}
        onSaveFact={onSaveFact}
      />,
    )

    const card = screen.getByRole('region', { name: 'Captured information' })
    expect(within(card).getByText('Noted 1 detail')).toBeVisible()
    await user.click(within(card).getByRole('button', { name: 'Review' }))
    expect(within(card).getByRole('button', { name: 'Hide' })).toHaveAttribute('aria-expanded', 'true')
    expect(within(card).getByText('Claim type')).toBeVisible()
    expect(within(card).getByText('Motor vehicle accident')).toBeVisible()
    expect(within(card).getByText('Review this detail. You can correct it at any time.')).toBeVisible()

    const edit = within(card).getByRole('button', { name: 'Edit Claim type in captured information' })
    expect(edit.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    await user.click(edit)
    await user.selectOptions(within(card).getByRole('combobox', { name: 'Claim type' }), 'home')
    await user.click(within(card).getByRole('button', { name: 'Save' }))
    expect(onSaveFact).toHaveBeenCalledWith(expect.objectContaining({ fieldCode: 'claim.product_family' }), 'home')
  })

  it('marks what the claimant owes and lets them upload from the chip', () => {
    render(
      <TurnAttachments
        receipts={[
          { item_id: 'evd_1', kind: 'document', owner: 'claimant', state: 'open', subject: 'repair_quote' },
          { item_id: 'nwq_1', kind: 'question', owner: 'northwind', state: 'open', subject: 'Will you pay for a hire car?' },
        ]}
        onUpload={vi.fn()}
      />,
    )
    expect(screen.getByText('To do: Repair quote').closest('.turn-chip')).toHaveClass('is-owed')
    expect(screen.getByRole('button', { name: 'Upload' })).toBeVisible()
    expect(screen.getByText('For the claims team: Will you pay for a hire car?').closest('.turn-chip'))
      .not.toHaveClass('is-owed')
  })

  it('pins services, files, clauses and the next step in the case panel', async () => {
    const user = userEvent.setup()
    const onPin = vi.fn()
    render(
      <TurnAttachments
        services={[{ offer_id: 'off_1', service_name: 'Towing', status: 'consent_required' }]}
        fileReads={[{ evidence_id: 'evd_photo', kind: 'incident_photo' }]}
        clauses={[{ chunk_id: 'chk_1', section_path: 'MTR-BEN-03 Hire car', title: 'Motor policy', text: '…' }]}
        nextStep={{ pin: 'submit', label: 'Check your details' }}
        onPin={onPin}
      />,
    )

    await user.click(screen.getByRole('button', { name: /Towing · Permission needed/ }))
    await user.click(screen.getByRole('button', { name: /File · read as/ }))
    await user.click(screen.getByRole('button', { name: /Policy · MTR-BEN-03 Hire car/ }))
    await user.click(screen.getByRole('button', { name: 'Check your details' }))
    expect(onPin.mock.calls.map(([item]) => item)).toEqual([
      { kind: 'service', id: 'off_1' },
      { kind: 'file', id: 'evd_photo' },
      { kind: 'clause', id: 'chk_1' },
      { kind: 'submit' },
    ])
  })

  it('puts the scope note before the chips as one quiet line', () => {
    render(<TurnAttachments scopeNote="Because someone was hurt, two more details are needed." />)
    expect(screen.getByText('Because someone was hurt, two more details are needed.')).toHaveClass('turn-scope-note')
  })
})
