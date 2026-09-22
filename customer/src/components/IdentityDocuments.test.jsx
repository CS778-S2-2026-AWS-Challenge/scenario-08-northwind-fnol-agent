import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ProfileMutationError } from '../profile/profileMutation.js'
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

function IdentityHarness({ initialDocuments = [], onCreate = vi.fn(), onUpdate = vi.fn() }) {
  const [documents, setDocuments] = useState(initialDocuments)
  return (
    <IdentityDocuments
      resource={{ items: documents, error: '', loading: false }}
      pending={{}}
      onBeginCreate={() => 'identity-attempt-1'}
      onAbandonCreate={vi.fn()}
      onCreate={async (request) => {
        const saved = await onCreate(request)
        setDocuments((current) => [saved, ...current.filter(({ identity_id: id }) => id !== saved.identity_id)])
        return saved
      }}
      onReload={vi.fn()}
      onUpdate={async (...args) => {
        const saved = await onUpdate(...args)
        setDocuments((current) => current.map((document) => document.identity_id === saved.identity_id ? saved : document))
        return saved
      }}
    />
  )
}

describe('IdentityDocuments account projection', () => {
  it('edits a masked record without pre-filling its protected number', async () => {
    const user = userEvent.setup()
    const updated = { ...passport, masked_document_number: '****9012', revision: 2 }
    const onUpdate = vi.fn().mockResolvedValue(updated)
    render(<IdentityHarness initialDocuments={[licence, passport]} onUpdate={onUpdate} />)

    await user.click(screen.getByRole('button', { name: 'Edit Passport ****5678' }))
    const number = screen.getByLabelText('Passport number')
    expect(number).toHaveFocus()
    expect(number).toHaveValue('')
    await user.type(number, 'P12349012')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(passport.identity_id, 1, 'P12349012'))
    expect(await screen.findByText('****9012')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('P12349012')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit Passport ****9012' })).toHaveFocus()
  })

  it('passes one create attempt to the controller and keeps only the masked projection', async () => {
    const user = userEvent.setup()
    const onCreate = vi.fn().mockResolvedValue(passport)
    render(<IdentityHarness onCreate={onCreate} />)

    await user.click(screen.getByRole('button', { name: 'Add identity document' }))
    expect(screen.getByLabelText('Document type')).toHaveFocus()
    await user.selectOptions(screen.getByLabelText('Document type'), 'passport')
    await user.type(screen.getByLabelText('Passport number'), 'P00005678')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith({
      documentType: 'passport',
      documentNumber: 'P00005678',
      attemptId: 'identity-attempt-1',
    }))
    expect(await screen.findByText('****5678')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('P00005678')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Only its masked number is shown')
  })

  it('keeps the draft open after the controller reloads a conflicting record', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockRejectedValue(new ProfileMutationError(
      'This saved record changed. Northwind reloaded the latest list and kept your draft.',
      { code: 'REVISION_CONFLICT', kind: 'conflict' },
    ))
    render(<IdentityHarness initialDocuments={[licence]} onUpdate={onUpdate} />)

    await user.click(screen.getByRole('button', { name: 'Edit Driver licence ****1234' }))
    await user.type(screen.getByLabelText('Driver licence number'), 'DL9999999')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('kept your draft')
    expect(screen.getByLabelText('Driver licence number')).toHaveValue('DL9999999')
  })

  it('keeps an ambiguous update draft open without claiming it was saved', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockRejectedValue(new ProfileMutationError(
      'Northwind reloaded saved identity documents but could not confirm that the identity-document update completed. Your draft is still here; review the latest saved list and retry when ready.',
      { code: 'NETWORK_ERROR', kind: 'unknown' },
    ))
    render(<IdentityHarness initialDocuments={[licence]} onUpdate={onUpdate} />)

    await user.click(screen.getByRole('button', { name: 'Edit Driver licence ****1234' }))
    await user.type(screen.getByLabelText('Driver licence number'), 'DIFFERENT-1234')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('could not confirm')
    expect(screen.getByLabelText('Driver licence number')).toHaveValue('DIFFERENT-1234')
    expect(screen.queryByText(/Driver licence saved/)).not.toBeInTheDocument()
  })

  it('keeps an unsaved number editable when protected storage rejects the write', async () => {
    const user = userEvent.setup()
    const onCreate = vi.fn().mockRejectedValue({ status: 503 })
    render(<IdentityHarness onCreate={onCreate} />)

    await user.click(screen.getByRole('button', { name: 'Add identity document' }))
    await user.type(screen.getByLabelText('Driver licence number'), 'DL1234567')
    await user.click(screen.getByRole('button', { name: 'Save identity document' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('service is unavailable')
    expect(screen.getByLabelText('Driver licence number')).toHaveValue('DL1234567')
    expect(screen.queryByText('****4567')).not.toBeInTheDocument()
  })
})
