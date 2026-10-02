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

  it('folds facts into chips and opens them in place to confirm', async () => {
    const user = userEvent.setup()
    const onConfirmFacts = vi.fn()
    render(
      <TurnAttachments
        facts={[fact('incident.location', 'Location', 'Dominion Road', true), fact('incident.injury_or_danger', 'Anyone hurt', 'No', false)]}
        onConfirmFacts={onConfirmFacts}
      />,
    )

    const location = screen.getByRole('button', { name: 'Location: Dominion Road (to check)' })
    expect(location).toHaveClass('is-check')
    expect(screen.getByRole('button', { name: 'Anyone hurt: No' })).not.toHaveClass('is-check')
    expect(screen.queryByRole('region', { name: 'Just noted' })).not.toBeInTheDocument()

    await user.click(location)
    const list = screen.getByRole('region', { name: 'Just noted' })
    await user.click(within(list).getByRole('button', { name: 'All correct' }))
    expect(onConfirmFacts).toHaveBeenCalledWith(['incident.location'])
    expect(screen.queryByRole('region', { name: 'Just noted' })).not.toBeInTheDocument()
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
