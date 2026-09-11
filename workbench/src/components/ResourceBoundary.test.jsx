import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ResourceBoundary from './ResourceBoundary.jsx'

describe('ResourceBoundary', () => {
  it('keeps saved records visible and labels them stale when refresh fails', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(
      <ResourceBoundary
        resource={{
          items: [{ id: 'rec_1' }],
          stale: true,
          error: Object.assign(new Error('Evidence source timed out.'), { requestId: 'req_evidence_1' }),
        }}
        onRetry={onRetry}
      >
        <p>Saved evidence record</p>
      </ResourceBoundary>,
    )

    expect(screen.getByText('Saved evidence record')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Showing saved records')
    expect(screen.getByRole('alert')).toHaveTextContent('Request reference: req_evidence_1')
    await user.click(screen.getByRole('button', { name: 'Retry section' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('does not fabricate an empty state when a source is unavailable', () => {
    render(
      <ResourceBoundary resource={{ items: [], status: 'unavailable', limitation: 'Archive lookup unavailable.' }}>
        <p>No records</p>
      </ResourceBoundary>,
    )

    expect(screen.getByText('This section is unavailable')).toBeInTheDocument()
    expect(screen.getByText('Archive lookup unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('No records')).not.toBeInTheDocument()
  })
})
