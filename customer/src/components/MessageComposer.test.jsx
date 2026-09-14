import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import MessageComposer from './MessageComposer.jsx'

function ComposerHarness({ onRemoved = vi.fn(), initialStatus = 'uploading' }) {
  const [draft, setDraft] = useState('')
  const [attachments, setAttachments] = useState([
    { id: 'file-1', name: 'kitchen-damage.jpg', status: initialStatus, statusLabel: initialStatus === 'uploaded' ? 'Ready' : 'Uploading…' },
  ])

  return (
    <MessageComposer
      draft={draft}
      setDraft={setDraft}
      onSubmit={(event) => event.preventDefault()}
      inputLabel="Claim message"
      busy={false}
      buttonLabel="Send"
      variant="workspace"
      attachments={attachments}
      onRemoveAttachment={(attachment) => {
        onRemoved(attachment)
        setAttachments((current) => current.filter((item) => item.id !== attachment.id))
      }}
    />
  )
}

it('removes a selected draft attachment with Backspace without changing message text', async () => {
  const user = userEvent.setup()
  const onRemoved = vi.fn()
  render(<ComposerHarness onRemoved={onRemoved} />)

  const message = screen.getByRole('textbox', { name: 'Claim message' })
  await user.type(message, 'Kitchen damage')
  await user.keyboard('{Backspace}')
  expect(message).toHaveValue('Kitchen damag')
  expect(screen.getByText('kitchen-damage.jpg')).toBeInTheDocument()

  const attachment = screen.getByRole('button', { name: 'Select kitchen-damage.jpg' })
  attachment.focus()
  await user.keyboard('{Backspace}')

  expect(onRemoved).toHaveBeenCalledWith(expect.objectContaining({ id: 'file-1' }))
  expect(screen.queryByText('kitchen-damage.jpg')).not.toBeInTheDocument()
  expect(message).toHaveValue('Kitchen damag')
})

it('provides an accessible remove control and returns focus to the message', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  await user.click(screen.getByRole('button', { name: 'Remove kitchen-damage.jpg' }))

  expect(screen.queryByText('kitchen-damage.jpg')).not.toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Claim message' })).toHaveFocus()
})

it('does not present a local remove action for server-persisted Evidence', () => {
  render(<ComposerHarness initialStatus="uploaded" />)

  expect(screen.getByText('kitchen-damage.jpg')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Remove kitchen-damage.jpg' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Select kitchen-damage.jpg' })).not.toBeInTheDocument()
})
