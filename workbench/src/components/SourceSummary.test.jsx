import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import SourceSummary from './SourceSummary.jsx'

describe('SourceSummary', () => {
  it('keeps source context visible and reveals traceability details on request', async () => {
    const user = userEvent.setup()
    render(<SourceSummary summary={{
      status: 'available',
      items: [{
        kind: 'field',
        record_ref: 'field:incident.description',
        label: 'Incident Description',
        context: 'Incident Description is recorded for the current action.',
        source_label: 'Claimant statement',
        status: 'confirmed',
        source_refs: ['msg_source'],
        needed_for: ['current_action'],
        confidence: 0.92,
        updated_at: '2026-09-03T01:00:00Z',
      }],
    }} />)

    expect(screen.getByText('Claimant statement · Confirmed')).toBeVisible()
    expect(screen.queryByText('msg_source')).not.toBeVisible()
    await user.click(screen.getByText('Incident Description'))
    expect(screen.getByText('msg_source')).toBeVisible()
    expect(screen.getByText('92%')).toBeVisible()
  })

  it('states empty and unavailable source conditions explicitly', () => {
    const { rerender } = render(<SourceSummary summary={{ status: 'empty', items: [] }} />)
    expect(screen.getByText(/No source context is recorded/)).toBeVisible()

    rerender(<SourceSummary summary={{ status: 'unavailable', items: [], limitation: 'External records could not be read.' }} />)
    expect(screen.getByText('External records could not be read.')).toBeVisible()
    expect(screen.getByText(/Source context is unavailable/)).toBeVisible()
  })
})
