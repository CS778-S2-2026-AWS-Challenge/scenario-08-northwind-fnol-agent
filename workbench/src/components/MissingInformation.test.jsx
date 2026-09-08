import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import MissingInformation from './MissingInformation.jsx'

describe('MissingInformation', () => {
  it('shows the prioritised first six and expands all details from the keyboard', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 8 }, (_, index) => ({
      kind: 'field',
      code: `missing.${index + 1}`,
      label: `Missing item ${index + 1}`,
      status: index === 7 ? 'unavailable' : 'missing',
      attention: index === 0 ? 'required_now' : 'needed_next',
      responsible_party: index === 7 ? 'external_party' : 'claimant',
      source_refs: [`msg_${index + 1}`],
      blocked_action: index === 7 ? 'claim.create' : null,
    }))
    render(<MissingInformation items={items} />)

    expect(screen.getAllByText('Missing item 6')[0]).toBeVisible()
    expect(screen.queryByText('Missing item 7')).not.toBeVisible()
    const disclosure = screen.getByText('Show all gaps')
    disclosure.focus()
    await user.keyboard('{Enter}')

    expect(screen.getAllByText('Missing item 8').at(-1)).toBeVisible()
    await user.click(screen.getAllByText('Traceability').at(-1))
    expect(screen.getByText('msg_8')).toBeVisible()
    expect(screen.getByText(/claim create/i)).toBeVisible()
    expect(screen.getAllByText(/external party/i).at(-1)).toBeVisible()
    expect(screen.getAllByText(/unavailable.*needed next.*external party/i).at(-1)).toBeVisible()
  })
})
