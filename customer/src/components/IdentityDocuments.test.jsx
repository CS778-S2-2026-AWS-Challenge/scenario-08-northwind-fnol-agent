import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  createAccountIdentityDocument: vi.fn(),
  listAccountIdentityDocuments: vi.fn(),
  requestId: vi.fn(() => 'identity-document-test-key'),
  updateAccountIdentityDocument: vi.fn(),
}))
vi.mock('../api.js', () => api)

import IdentityDocuments from './IdentityDocuments.jsx'

const licence = {
  identity_id: 'idn_11111111111111111111',
  document_type: 'driver_licence',
  masked_document_number: '****1234',
  revision: 2,
  active: true,
}
const passport = {
  identity_id: 'idn_22222222222222222222',
  document_type: 'passport',
  masked_document_number: '****5678',
  revision: 1,
  active: true,
}

describe('IdentityDocuments account projection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listAccountIdentityDocuments.mockResolvedValue({ items: [], page: { next_cursor: null } })
  })

  it('pages through every masked record and edits one without pre-filling its full number', async () => {
    const user = userEvent.setup()
    api.listAccountIdentityDocuments
      .mockResolvedValueOnce({ items: [licence], page: { next_cursor: 'next-page' } })
      .mockResolvedValueOnce({ items: [passport], page: { next_cursor: null } })
    api.updateAccountIdentityDocument.mockResolvedValue({ ...passport, masked_document_number: '****9012', revision: 2 })
    render(<IdentityDocuments />)

    const list = await screen.findByRole('list', { name: 'Saved identity documents' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('****1234')).toBeInTheDocument()
    expect(screen.getByText('****5678')).toBeInTheDocument()
    expect(api.listAccountIdentityDocuments).toHaveBeenNthCalledWith(2, expect.objectContaining({ cursor: 'next-page' }))

    await user.click(screen.getByRole('button', { name: 'Edit Passport ****5678' }))
    const number = screen.getByLabelText('Passport number')
    expect(number).toHaveFocus()
    expect(number).toHaveValue('')
    await user.type(number, 'P12349012')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    await waitFor(() => expect(api.updateAccountIdentityDocument).toHaveBeenCalledWith({
      identityId: passport.identity_id,
      revision: 1,
      documentNumber: 'P12349012',
    }))
    expect(await screen.findByText('****9012')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('P12349012')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Passport number')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Passport ****9012' })).toBeInTheDocument()
  })

  it('adds a passport with a stable idempotency key, closes the editor, and keeps only the masked projection', async () => {
    const user = userEvent.setup()
    api.createAccountIdentityDocument.mockResolvedValue(passport)
    render(<IdentityDocuments />)

    await user.click(await screen.findByRole('button', { name: 'Add identity document' }))
    expect(screen.getByLabelText('Document type')).toHaveFocus()
    await user.selectOptions(screen.getByLabelText('Document type'), 'passport')
    await user.type(screen.getByLabelText('Passport number'), 'P00005678')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    await waitFor(() => expect(api.createAccountIdentityDocument).toHaveBeenCalledWith({
      documentType: 'passport',
      documentNumber: 'P00005678',
      idempotencyKey: 'identity-document-test-key',
    }))
    expect(await screen.findByText('****5678')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('P00005678')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add identity document' })).toHaveFocus()
    expect(screen.getByRole('status')).toHaveTextContent('Only its masked number is shown')
  })

  it('reloads after a revision conflict before another edit', async () => {
    const user = userEvent.setup()
    api.listAccountIdentityDocuments
      .mockResolvedValueOnce({ items: [licence], page: { next_cursor: null } })
      .mockResolvedValueOnce({ items: [{ ...licence, revision: 3, masked_document_number: '****4321' }], page: { next_cursor: null } })
    api.updateAccountIdentityDocument.mockRejectedValueOnce({ status: 409 })
    render(<IdentityDocuments />)

    await user.click(await screen.findByRole('button', { name: 'Edit Driver licence ****1234' }))
    await user.type(screen.getByLabelText('Driver licence number'), 'DL9999999')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('reopen the document')
    await user.click(await screen.findByRole('button', { name: 'Edit Driver licence ****4321' }))
    expect(screen.getByLabelText('Driver licence number')).toHaveValue('')
    expect(api.listAccountIdentityDocuments).toHaveBeenCalledTimes(2)
  })

  it('offers a retry if the saved list cannot be loaded', async () => {
    const user = userEvent.setup()
    api.listAccountIdentityDocuments
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce({ items: [passport], page: { next_cursor: null } })
    render(<IdentityDocuments />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Check your connection and try again')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('****5678')).toBeInTheDocument()
  })

  it('keeps an unsaved number editable when protected storage rejects the write', async () => {
    const user = userEvent.setup()
    api.createAccountIdentityDocument.mockRejectedValue({ status: 503 })
    render(<IdentityDocuments />)

    await user.click(await screen.findByRole('button', { name: 'Add identity document' }))
    await user.type(screen.getByLabelText('Driver licence number'), 'DL1234567')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('protected account storage is unavailable')
    expect(screen.getByLabelText('Driver licence number')).toHaveValue('DL1234567')
    expect(screen.queryByText('****4567')).not.toBeInTheDocument()
    expect(screen.queryByText(/Only its masked number is shown/)).not.toBeInTheDocument()
  })

  it('keeps the same create key after an uncertain network result and lets the user refresh the list', async () => {
    const user = userEvent.setup()
    api.createAccountIdentityDocument
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce(passport)
    api.listAccountIdentityDocuments
      .mockResolvedValueOnce({ items: [], page: { next_cursor: null } })
      .mockResolvedValueOnce({ items: [passport], page: { next_cursor: null } })
    render(<IdentityDocuments />)

    await user.click(await screen.findByRole('button', { name: 'Add identity document' }))
    await user.selectOptions(screen.getByLabelText('Document type'), 'passport')
    await user.type(screen.getByLabelText('Passport number'), 'P00005678')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('could not confirm whether this document was saved')
    expect(screen.getByLabelText('Passport number')).toHaveValue('P00005678')
    await user.click(screen.getByRole('button', { name: 'Refresh saved list' }))
    expect(await screen.findByText('****5678')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))
    await waitFor(() => expect(api.createAccountIdentityDocument).toHaveBeenCalledTimes(2))
    expect(api.createAccountIdentityDocument.mock.calls[1][0].idempotencyKey).toBe(api.createAccountIdentityDocument.mock.calls[0][0].idempotencyKey)
    expect(screen.getAllByText('****5678')).toHaveLength(1)
  })
})
