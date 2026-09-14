import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

function ControlHarness() {
  const [draft, setDraft] = useState('')
  const [claimType, setClaimType] = useState('')
  const [selectedModel, setSelectedModel] = useState('qwen-local')

  return (
    <MessageComposer
      draft={draft}
      setDraft={setDraft}
      onSubmit={(event) => event.preventDefault()}
      inputLabel="Claim message"
      busy={false}
      buttonLabel="Send"
      variant="workspace"
      claimType={claimType}
      setClaimType={setClaimType}
      models={[{ id: 'qwen-local', label: 'Qwen Local', availability: 'available' }]}
      selectedModel={selectedModel}
      setSelectedModel={setSelectedModel}
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

it('keeps the claimant selectors keyboard operable with clear control sizing hooks', async () => {
  const user = userEvent.setup()
  render(<ControlHarness />)

  const claimType = screen.getByRole('button', { name: 'Claim type (optional)' })
  expect(claimType).toHaveTextContent('Let Agent identify')

  claimType.focus()
  await user.keyboard('{ArrowDown}')
  const automaticOption = screen.getByRole('option', { name: 'Let Agent identify' })
  await waitFor(() => expect(automaticOption).toHaveFocus())
  await user.keyboard('{ArrowDown}')
  await user.keyboard('{Enter}')

  expect(claimType).toHaveTextContent('Motor')
  expect(claimType).toHaveFocus()
  expect(screen.queryByRole('listbox', { name: 'Claim type (optional)' })).not.toBeInTheDocument()

  expect(screen.getByRole('button', { name: 'Model' })).toHaveTextContent('Qwen Local')
})

it('uses recognizable icons and accessible names for attachment and voice controls', () => {
  render(<ControlHarness />)

  const attach = screen.getByRole('button', { name: 'Attach a file' })
  const voice = screen.getByRole('button', { name: 'Use voice input' })

  expect(attach.querySelector('.tool-icon')).toBeInTheDocument()
  expect(voice.querySelector('.tool-icon')).toBeInTheDocument()
  expect(attach).toHaveAttribute('title', 'Attach a file')
  expect(voice).toHaveAttribute('title', 'Use voice input')
})
