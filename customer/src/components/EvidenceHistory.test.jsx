import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  applyEvidenceHistoryAction: vi.fn(),
  getClaimEvidence: vi.fn(),
  listEvidenceHistory: vi.fn(),
}))

vi.mock('../api.js', () => api)

import EvidenceHistory from './EvidenceHistory.jsx'

const historyItem = {
  evidence_id: 'evd_history_1',
  source_claim_id: 'clm_previous',
  kind: 'incident_photo',
  status: 'received',
  file_status: 'ready',
  original_filename: 'rear-damage.jpg',
  media_type: 'image/jpeg',
  size_bytes: 2048,
  source: 'claimant',
  provenance_summary: ['claimant_upload'],
  can_reuse: true,
  can_remove: false,
  linked_claim_ids: [],
  created_at: '2026-09-12T01:00:00Z',
  updated_at: '2026-09-12T01:01:00Z',
}

describe('claimant Evidence history', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows loading, then the source Claim, lifecycle, provenance, and governed eligibility', async () => {
    let resolveHistory
    api.listEvidenceHistory.mockReturnValue(new Promise((resolve) => { resolveHistory = resolve }))
    render(<EvidenceHistory currentClaimId="clm_current" />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading your evidence history')
    resolveHistory({ items: [historyItem], page: { next_cursor: null } })

    expect(await screen.findByText('rear-damage.jpg')).toBeInTheDocument()
    expect(screen.getByText('clm_previous')).toBeInTheDocument()
    expect(screen.getByText('Uploaded by you')).toBeInTheDocument()
    expect(screen.getByText('12 Sept 2026, 1:01 pm')).toBeInTheDocument()
    expect(screen.getByText('Eligible')).toBeInTheDocument()
    expect(screen.getByText('Not available for this item')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /reuse|remove rear-damage/i })).not.toBeInTheDocument()
  })

  it('distinguishes a true empty account history', async () => {
    api.listEvidenceHistory.mockResolvedValue({ items: [], page: { next_cursor: null } })
    render(<EvidenceHistory currentClaimId="clm_current" />)

    expect(await screen.findByRole('heading', { name: 'No uploaded evidence yet' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh' })).not.toBeInTheDocument()
  })

  it('keeps prior records visible and marks them stale when refresh fails', async () => {
    const user = userEvent.setup()
    api.listEvidenceHistory
      .mockResolvedValueOnce({ items: [historyItem], page: { next_cursor: null } })
      .mockRejectedValueOnce(Object.assign(new Error('Connection interrupted.'), {
        code: 'NETWORK_ERROR',
      }))
    render(<EvidenceHistory currentClaimId="clm_current" />)
    await screen.findByText('rear-damage.jpg')

    await user.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(await screen.findByText('Showing earlier results')).toBeInTheDocument()
    expect(screen.getByText('rear-damage.jpg')).toBeInTheDocument()
  })

  it.each([
    [403, 'FORBIDDEN', 'Evidence history is not available for this account'],
    [503, 'DEPENDENCY_UNAVAILABLE', 'Evidence history is temporarily unavailable'],
    [500, 'INTERNAL_ERROR', 'Evidence history could not be loaded'],
  ])('renders the bounded %s failure state with a safe next step', async (status, code, heading) => {
    api.listEvidenceHistory.mockRejectedValue(Object.assign(new Error('The request was refused.'), {
      status,
      code,
    }))
    render(<EvidenceHistory currentClaimId="clm_current" />)

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
    expect(screen.getByText(/The request was refused/)).toBeInTheDocument()
    if (status !== 403) expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('loads the next opaque page without duplicating an existing Evidence record', async () => {
    const user = userEvent.setup()
    api.listEvidenceHistory
      .mockResolvedValueOnce({ items: [historyItem], page: { next_cursor: 'cursor-2' } })
      .mockResolvedValueOnce({
        items: [historyItem, { ...historyItem, evidence_id: 'evd_history_2', original_filename: 'receipt.pdf' }],
        page: { next_cursor: null },
      })
    render(<EvidenceHistory currentClaimId="clm_current" />)
    await screen.findByText('rear-damage.jpg')

    await user.click(screen.getByRole('button', { name: 'Load more' }))

    expect(await screen.findByText('receipt.pdf')).toBeInTheDocument()
    expect(screen.getAllByText('rear-damage.jpg')).toHaveLength(1)
    expect(api.listEvidenceHistory).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'cursor-2' }))
  })

  it('uses the selected Claim projection and gives Evidence without a filename a readable title', async () => {
    api.getClaimEvidence.mockResolvedValue({
      claim_id: 'clm_selected',
      revision: 4,
      items: [{
        ...historyItem,
        evidence_id: 'evd_police_report',
        original_filename: null,
        kind: 'police_report',
      }],
      customer_next_step: { summary: 'Continue your Claim.' },
    })

    render(<EvidenceHistory claimId="clm_selected" />)

    expect(await screen.findByText('Police Report')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Evidence for this Claim' })).toBeInTheDocument()
    expect(api.getClaimEvidence).toHaveBeenCalledWith('clm_selected', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(api.listEvidenceHistory).not.toHaveBeenCalled()
    expect(screen.queryByText('Reuse')).not.toBeInTheDocument()
    expect(screen.queryByText('Removal')).not.toBeInTheDocument()
  })

  it('reuses an eligible historical item, refreshes the list, and announces the result', async () => {
    const user = userEvent.setup()
    api.listEvidenceHistory
      .mockResolvedValueOnce({ items: [historyItem], page: { next_cursor: null } })
      .mockResolvedValueOnce({ items: [{ ...historyItem, linked_claim_ids: ['clm_current'] }], page: { next_cursor: null } })
    api.applyEvidenceHistoryAction.mockResolvedValue({ status: 'succeeded' })

    render(<EvidenceHistory currentClaimId="clm_current" currentClaimRevision={4} />)
    await screen.findByText('rear-damage.jpg')
    await user.click(screen.getByRole('button', { name: 'Reuse for this Claim' }))

    expect(api.applyEvidenceHistoryAction).toHaveBeenCalledWith(expect.objectContaining({
      claimId: 'clm_current',
      evidenceId: 'evd_history_1',
      action: 'reuse',
      sourceClaimId: 'clm_previous',
      revision: 4,
    }))
    expect(await screen.findByRole('alert')).toHaveTextContent('now attached to this Claim')
    expect(api.listEvidenceHistory).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Remove from this Claim' })).toBeInTheDocument()
  })

  it('announces a server-denied removal and keeps the refreshed history visible', async () => {
    const user = userEvent.setup()
    const removable = {
      ...historyItem,
      can_reuse: false,
      can_remove: true,
      source_claim_id: 'clm_current',
    }
    api.listEvidenceHistory
      .mockResolvedValueOnce({ items: [removable], page: { next_cursor: null } })
      .mockResolvedValueOnce({ items: [removable], page: { next_cursor: null } })
    api.applyEvidenceHistoryAction.mockRejectedValue(Object.assign(new Error('Retention prevents removal.'), {
      status: 409,
      code: 'EVIDENCE_RETENTION_BLOCKED',
    }))

    render(<EvidenceHistory currentClaimId="clm_current" currentClaimRevision={4} />)
    await screen.findByText('rear-damage.jpg')
    await user.click(screen.getByRole('button', { name: 'Remove from history' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Retention prevents removal')
    expect(screen.getByText('rear-damage.jpg')).toBeInTheDocument()
    expect(api.applyEvidenceHistoryAction).toHaveBeenCalledWith(expect.objectContaining({ action: 'remove' }))
  })
})
