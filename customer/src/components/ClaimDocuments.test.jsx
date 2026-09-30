import { expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ClaimDocuments from './ClaimDocuments.jsx'
import { documentStatus } from '../claimDocumentProjection.js'

const recommendedPhoto = {
  evidence_id: 'evd_photo',
  kind: 'incident_photo',
  status: 'missing',
  file_status: 'not_available',
  needed_for: [],
}

function renderDocuments(items, props = {}) {
  return render(
    <ClaimDocuments
      items={items}
      loadStatus="ready"
      onUpload={vi.fn()}
      {...props}
    />,
  )
}

it('renders a recommended upload as a complete task card with contract-backed constraints', async () => {
  const user = userEvent.setup()
  const { container } = renderDocuments([recommendedPhoto])

  expect(screen.getByRole('heading', { name: 'Documents and evidence' })).toBeInTheDocument()
  expect(screen.getByText('0 of 1 provided')).toBeInTheDocument()
  expect(screen.getByRole('progressbar')).toHaveAttribute('max', '1')
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
  expect(screen.getByRole('heading', { name: 'Recommended for this claim' })).toBeInTheDocument()
  expect(screen.getByText('1 item')).toBeInTheDocument()

  const card = screen.getByRole('listitem')
  expect(within(card).getByRole('heading', { name: 'Photos of the damage' })).toBeInTheDocument()
  expect(within(card).getByText('Recommended')).toBeInTheDocument()
  expect(within(card).getByText(/Clear photos help Northwind/)).toBeInTheDocument()
  expect(within(card).getByText('JPG, PNG or PDF · up to 10 MB each')).toBeInTheDocument()
  expect(within(card).queryByText(/HEIC/)).not.toBeInTheDocument()
  expect(within(card).getByRole('button', {
    name: 'Upload photos for Photos of the damage',
  })).toBeInTheDocument()
  expect(screen.queryByText(/needs your attention/)).not.toBeInTheDocument()

  const input = container.querySelector('input[type="file"]')
  expect(input).toHaveAttribute('accept', 'image/jpeg,image/png,application/pdf')

  await user.click(within(card).getByRole('button', { name: 'See photo tips' }))
  expect(within(card).getByText(/full damaged area/)).toBeVisible()
})

it('separates required and recommended tasks without presenting recommendations as errors', () => {
  const required = {
    evidence_id: 'evd_required',
    kind: 'repair_quote',
    status: 'missing',
    file_status: 'not_available',
    needed_for: ['current_action'],
  }
  renderDocuments([recommendedPhoto, required])

  const requiredGroup = screen.getByRole('region', { name: 'Required for this claim' })
  const recommendedGroup = screen.getByRole('region', { name: 'Recommended for this claim' })
  expect(within(requiredGroup).getByText('Required')).toBeInTheDocument()
  expect(within(recommendedGroup).getByText('Recommended')).toBeInTheDocument()
  expect(within(recommendedGroup).queryByRole('alert')).not.toBeInTheDocument()
})

it('shows an in-card loading state while the selected file is uploading', async () => {
  const user = userEvent.setup()
  let finishUpload
  const onUpload = vi.fn(() => new Promise((resolve) => { finishUpload = resolve }))
  const { container } = renderDocuments([recommendedPhoto], { onUpload })
  const file = new File(['image'], 'damage.jpg', { type: 'image/jpeg' })

  await user.upload(container.querySelector('input[type="file"]'), file)

  expect(onUpload).toHaveBeenCalledWith(recommendedPhoto, file)
  expect(screen.getByText('damage.jpg')).toBeInTheDocument()
  expect(screen.getByText('JPG · Uploading…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Uploading photos…' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: /Replace/ })).not.toBeInTheDocument()

  finishUpload({ succeeded: true })
  await waitFor(() => expect(screen.queryByText('JPG · Uploading…')).not.toBeInTheDocument())
})

it('shows the authoritative successful file and hides replacement and removal operations', () => {
  renderDocuments([{
    ...recommendedPhoto,
    status: 'received',
    file_status: 'ready',
    original_filename: 'damage.jpg',
    media_type: 'image/jpeg',
  }])

  expect(screen.getByText('1 of 1 provided')).toBeInTheDocument()
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '1')
  expect(screen.getByText('damage.jpg')).toBeInTheDocument()
  expect(screen.getByText('JPG · Upload complete')).toBeInTheDocument()
  expect(screen.getByText('Uploaded successfully')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Replace/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Upload photos/ })).not.toBeInTheDocument()
})

it('offers Replace only after an upload failure and keeps the error actionable', async () => {
  const user = userEvent.setup()
  const onUpload = vi.fn().mockResolvedValue({
    succeeded: false,
    message: 'The upload connection was interrupted. Choose Replace and try again.',
  })
  const { container } = renderDocuments([recommendedPhoto], { onUpload })

  await user.upload(
    container.querySelector('input[type="file"]'),
    new File(['image'], 'damage.png', { type: 'image/png' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('The upload connection was interrupted')
  expect(screen.getByText('PNG · Upload failed')).toBeInTheDocument()
  expect(screen.getByRole('button', {
    name: 'Replace photos for Photos of the damage',
  })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
})

it('rejects HEIC before upload and offers a replacement with supported formats', async () => {
  const user = userEvent.setup({ applyAccept: false })
  const onUpload = vi.fn()
  const { container } = renderDocuments([recommendedPhoto], { onUpload })

  await user.upload(
    container.querySelector('input[type="file"]'),
    new File(['image'], 'damage.heic', { type: 'image/heic' }),
  )

  expect(screen.getByRole('alert')).toHaveTextContent('Choose a JPG, PNG or PDF file')
  expect(screen.getByText('File · Unsupported file format')).toBeInTheDocument()
  expect(screen.getByRole('button', {
    name: 'Replace photos for Photos of the damage',
  })).toBeInTheDocument()
  expect(onUpload).not.toHaveBeenCalled()
})

it('derives server-side failure and invalid states without exposing unsupported actions', () => {
  const failed = {
    evidence_id: 'evd_failed',
    kind: 'repair_quote',
    status: 'received',
    file_status: 'failed',
    original_filename: 'failed-quote.pdf',
    media_type: 'application/pdf',
    needed_for: ['current_action'],
  }
  const invalid = {
    evidence_id: 'evd_invalid',
    kind: 'proof_of_ownership',
    status: 'invalid',
    file_status: 'ready',
    original_filename: 'invalid-receipt.pdf',
    media_type: 'application/pdf',
    needed_for: ['current_action'],
  }
  renderDocuments([failed, invalid])

  expect(screen.getAllByRole('alert')).toHaveLength(2)
  expect(screen.getByRole('button', { name: 'Replace file for Repair quote' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Replace file for Proof of ownership' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
})

it('shows honest loading, empty, and unavailable states', () => {
  const { rerender } = render(<ClaimDocuments items={[]} loadStatus="loading" />)
  expect(screen.getByRole('status')).toHaveTextContent('Checking what may help')
  expect(screen.getByText('Checking progress…')).toBeInTheDocument()

  rerender(<ClaimDocuments items={[]} loadStatus="ready" />)
  expect(screen.getByText('0 of 0 provided')).toBeInTheDocument()
  expect(screen.getByText('Nothing to provide right now.')).toBeInTheDocument()

  rerender(<ClaimDocuments items={[]} loadStatus="error" />)
  expect(screen.getByRole('alert')).toHaveTextContent('Your claim is still saved')
})

it('uses a lightweight empty state in the Next steps panel', () => {
  renderDocuments([], { compact: true })

  expect(screen.getByRole('heading', { name: 'Documents and evidence' })).toBeVisible()
  expect(screen.getByText('No documents required yet.')).toBeVisible()
  expect(screen.queryByText('0 of 0 provided')).not.toBeInTheDocument()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})

it.each([
  ['failed processing needed now', { status: 'received', file_status: 'failed', needed_for: ['current_action'] }, 'required'],
  ['invalid material needed now', { status: 'invalid', file_status: 'ready', needed_for: ['current_action'] }, 'required'],
  ['retryable supporting material', { status: 'received', file_status: 'failed', needed_for: [] }, 'recommended'],
  ['usable received material', { status: 'received', file_status: 'ready', needed_for: [] }, 'received'],
  ['processing material', { status: 'received', file_status: 'processing', needed_for: [] }, 'processing'],
])('maps %s from both authoritative Evidence states', (_label, item, expected) => {
  expect(documentStatus(item)).toBe(expected)
})
