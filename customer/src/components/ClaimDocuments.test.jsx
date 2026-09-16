import { expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ClaimDocuments from './ClaimDocuments.jsx'
import { documentAttentionCount, documentStatus } from '../claimDocumentProjection.js'

const documents = [
  {
    evidence_id: 'evd_later',
    kind: 'police_report',
    status: 'pending',
    file_status: 'not_available',
    needed_for: ['later_action'],
    claimant_note: 'Police said this will be available next week.',
  },
  {
    evidence_id: 'evd_received',
    kind: 'receipt',
    status: 'received',
    file_status: 'ready',
    original_filename: 'purchase-receipt.pdf',
    needed_for: ['later_action'],
  },
  {
    evidence_id: 'evd_processing',
    kind: 'incident_photo',
    status: 'received',
    file_status: 'processing',
    original_filename: 'kitchen-damage.jpg',
    needed_for: ['current_action'],
  },
  {
    evidence_id: 'evd_recommended',
    kind: 'repair_quote',
    status: 'missing',
    file_status: 'not_available',
    needed_for: [],
  },
  {
    evidence_id: 'evd_required',
    kind: 'proof_of_ownership',
    status: 'missing',
    file_status: 'not_available',
    needed_for: ['current_action'],
  },
]

it('sorts contract-backed document states and exposes only supported actions', async () => {
  const user = userEvent.setup()
  const onUpload = vi.fn()
  const onView = vi.fn()
  const { container } = render(
    <ClaimDocuments
      items={documents}
      loadStatus="ready"
      onUpload={onUpload}
      onView={onView}
    />,
  )

  expect(screen.getByText('2 items need your attention')).toBeInTheDocument()
  const rows = screen.getAllByRole('listitem')
  expect(rows.map((row) => within(row).getByText(
    /Required|Recommended|Processing|Received|Can add later/,
  ).textContent)).toEqual([
    '!Required',
    '+Recommended',
    '…Processing',
    '✓Received',
    '↗Can add later',
  ])

  const uploadInput = container.querySelector('input[type="file"]')
  const file = new File(['ownership'], 'ownership.pdf', { type: 'application/pdf' })
  await user.upload(uploadInput, file)
  expect(onUpload).toHaveBeenCalledWith(documents.at(-1), file)

  await user.click(screen.getByRole('button', { name: 'View purchase-receipt.pdf' }))
  expect(onView).toHaveBeenCalledWith(documents[1])
  expect(screen.getByText('Add later')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add later' })).not.toBeInTheDocument()
})

it('shows honest loading, empty, and unavailable states', () => {
  const { rerender } = render(<ClaimDocuments items={[]} loadStatus="loading" />)
  expect(screen.getByRole('status')).toHaveTextContent('Checking document guidance')

  rerender(<ClaimDocuments items={[]} loadStatus="ready" />)
  expect(screen.getByText('0 items need your attention')).toBeInTheDocument()
  expect(screen.getByText('No claim-specific documents are recorded yet.')).toBeInTheDocument()

  rerender(<ClaimDocuments items={[]} loadStatus="error" />)
  expect(screen.getByRole('alert')).toHaveTextContent('Your claim is still saved')
})

it.each([
  ['failed processing needed now', { status: 'received', file_status: 'failed', needed_for: ['current_action'] }, 'required'],
  ['invalid material needed now', { status: 'invalid', file_status: 'ready', needed_for: ['current_action'] }, 'required'],
  ['retryable supporting material', { status: 'received', file_status: 'failed', needed_for: [] }, 'recommended'],
  ['usable received material', { status: 'received', file_status: 'ready', needed_for: [] }, 'received'],
])('maps %s from both authoritative Evidence states', (_label, item, expected) => {
  expect(documentStatus(item)).toBe(expected)
})

it('renders failed and invalid material as attention items with replacement uploads', () => {
  const failed = {
    evidence_id: 'evd_failed',
    kind: 'repair_quote',
    status: 'received',
    file_status: 'failed',
    original_filename: 'failed-quote.pdf',
    needed_for: ['current_action'],
  }
  const invalid = {
    evidence_id: 'evd_invalid',
    kind: 'proof_of_ownership',
    status: 'invalid',
    file_status: 'ready',
    original_filename: 'invalid-receipt.pdf',
    needed_for: ['current_action'],
  }

  render(
    <ClaimDocuments
      items={[failed, invalid]}
      loadStatus="ready"
      onUpload={vi.fn()}
      onView={vi.fn()}
    />,
  )

  expect(documentAttentionCount([failed, invalid])).toBe(2)
  expect(screen.getByText('2 items need your attention')).toBeInTheDocument()
  expect(screen.getAllByText('Required')).toHaveLength(2)
  expect(screen.getByRole('button', { name: 'Upload failed-quote.pdf' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Upload invalid-receipt.pdf' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /View (failed-quote|invalid-receipt)/ })).not.toBeInTheDocument()
})
