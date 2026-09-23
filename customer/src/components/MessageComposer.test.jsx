import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import MessageComposer from './MessageComposer.jsx'

const originalCreateObjectUrl = Object.getOwnPropertyDescriptor(globalThis.URL, 'createObjectURL')
const originalRevokeObjectUrl = Object.getOwnPropertyDescriptor(globalThis.URL, 'revokeObjectURL')
const createObjectUrl = vi.fn((file) => `blob:composer/${encodeURIComponent(file.name)}`)
const revokeObjectUrl = vi.fn()

beforeEach(() => {
  createObjectUrl.mockClear()
  revokeObjectUrl.mockClear()
  Object.defineProperty(globalThis.URL, 'createObjectURL', {
    configurable: true,
    value: createObjectUrl,
  })
  Object.defineProperty(globalThis.URL, 'revokeObjectURL', {
    configurable: true,
    value: revokeObjectUrl,
  })
})

afterEach(() => {
  if (originalCreateObjectUrl) {
    Object.defineProperty(globalThis.URL, 'createObjectURL', originalCreateObjectUrl)
  } else {
    delete globalThis.URL.createObjectURL
  }
  if (originalRevokeObjectUrl) {
    Object.defineProperty(globalThis.URL, 'revokeObjectURL', originalRevokeObjectUrl)
  } else {
    delete globalThis.URL.revokeObjectURL
  }
})

function ComposerHarness({
  onRemoved = vi.fn(),
  onSubmit = (event) => event.preventDefault(),
  initialStatus = 'uploading',
  previewFile = null,
}) {
  const [draft, setDraft] = useState('')
  const [attachments, setAttachments] = useState([
    {
      id: 'file-1',
      evidenceId: initialStatus === 'uploaded' ? 'evd-file-1' : null,
      name: 'kitchen-damage.jpg',
      previewFile,
      status: initialStatus,
      statusLabel: initialStatus === 'uploaded' ? 'Ready' : 'Uploading…',
    },
  ])

  return (
    <MessageComposer
      draft={draft}
      setDraft={setDraft}
      onSubmit={onSubmit}
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
      models={[{
        id: 'qwen-local',
        label: 'Qwen Local',
        availability: 'available',
        image_input: false,
        document_input: false,
      }]}
      selectedModel={selectedModel}
      setSelectedModel={setSelectedModel}
    />
  )
}

function CapabilityHarness({ file, onSubmit = (event) => event.preventDefault() }) {
  const [draft, setDraft] = useState('')
  const [selectedModel, setSelectedModel] = useState('qwen-local')
  const [attachments, setAttachments] = useState([{
    id: 'file-1',
    evidenceId: 'evd-file-1',
    name: file.name,
    previewFile: file,
    status: 'uploaded',
    statusLabel: 'Ready',
  }])

  return (
    <MessageComposer
      draft={draft}
      setDraft={setDraft}
      onSubmit={onSubmit}
      inputLabel="Claim message"
      busy={false}
      buttonLabel="Send"
      variant="workspace"
      models={[
        {
          id: 'qwen-local',
          label: 'Qwen Local',
          availability: 'available',
          image_input: false,
          document_input: false,
        },
        {
          id: 'gemini',
          label: 'Gemini',
          availability: 'available',
          image_input: true,
          document_input: true,
        },
      ]}
      selectedModel={selectedModel}
      setSelectedModel={setSelectedModel}
      attachments={attachments}
      onRemoveAttachment={(attachment) => {
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

it('shows a selected image as a clickable local preview and releases its object URL', async () => {
  const user = userEvent.setup()
  const previewFile = new File(['image'], 'kitchen-damage.jpg', { type: 'image/jpeg' })
  render(<ComposerHarness previewFile={previewFile} />)

  const preview = await screen.findByRole('link', {
    name: 'Open kitchen-damage.jpg in a new tab',
  })
  expect(preview).toHaveAttribute('href', 'blob:composer/kitchen-damage.jpg')
  expect(preview).toHaveAttribute('target', '_blank')
  expect(preview.querySelector('img')).toHaveAttribute('src', 'blob:composer/kitchen-damage.jpg')

  await user.click(screen.getByRole('button', { name: 'Remove kitchen-damage.jpg' }))
  await waitFor(() => expect(revokeObjectUrl).toHaveBeenCalledWith('blob:composer/kitchen-damage.jpg'))
})

it('removes uploaded Evidence from the current message selection', async () => {
  const user = userEvent.setup()
  const onRemoved = vi.fn()
  render(<ComposerHarness initialStatus="uploaded" onRemoved={onRemoved} />)

  expect(screen.getByText('kitchen-damage.jpg')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Remove kitchen-damage.jpg' }))

  expect(onRemoved).toHaveBeenCalledWith(expect.objectContaining({ evidenceId: 'evd-file-1' }))
  expect(screen.queryByText('kitchen-damage.jpg')).not.toBeInTheDocument()
})

it('allows an uploaded file to be sent without message text', async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn((event) => event.preventDefault())
  render(<ComposerHarness initialStatus="uploaded" onSubmit={onSubmit} />)

  const send = screen.getByRole('button', { name: 'Send' })
  expect(send).toBeEnabled()
  await user.click(send)

  expect(onSubmit).toHaveBeenCalledOnce()
})

it('keeps send disabled while the selected file is uploading', () => {
  render(<ComposerHarness initialStatus="uploading" />)

  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
})

it.each([
  {
    name: 'damage.png',
    type: 'image/png',
    unsupportedLabel: 'Does not support images',
    supportedLabel: 'Supports images',
    warning: 'This model cannot process images.',
  },
  {
    name: 'repair-quote.pdf',
    type: 'application/pdf',
    unsupportedLabel: 'Does not support PDF documents',
    supportedLabel: 'Supports PDF documents',
    warning: 'This model cannot process PDF documents.',
  },
])('blocks an incompatible model for $type and recovers after a compatible model is selected', async ({
  name,
  type,
  unsupportedLabel,
  supportedLabel,
  warning,
}) => {
  const user = userEvent.setup()
  const onSubmit = vi.fn((event) => event.preventDefault())
  render(<CapabilityHarness file={new File(['file'], name, { type })} onSubmit={onSubmit} />)

  const capabilityWarning = screen.getByRole('alert')
  expect(capabilityWarning).toHaveTextContent(warning)
  expect(capabilityWarning).toHaveTextContent('Your file is still attached.')
  expect(capabilityWarning.closest('.composer-input-surface')).not.toBeNull()
  expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

  await user.click(screen.getByRole('button', { name: 'Model' }))
  expect(screen.getByRole('option', {
    name: new RegExp(`Qwen Local.*${unsupportedLabel}`),
  })).toBeDisabled()
  await user.click(screen.getByRole('option', {
    name: new RegExp(`Gemini.*${supportedLabel}`),
  }))

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  const send = screen.getByRole('button', { name: 'Send' })
  expect(send).toBeEnabled()
  await user.click(send)
  expect(onSubmit).toHaveBeenCalledOnce()
})

it('clears the model capability warning when the conflicting attachment is removed', async () => {
  const user = userEvent.setup()
  render(<CapabilityHarness file={new File(['image'], 'damage.jpg', { type: 'image/jpeg' })} />)

  expect(screen.getByRole('alert')).toHaveTextContent('This model cannot process images.')
  await user.click(screen.getByRole('button', { name: 'Remove damage.jpg' }))

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText('damage.jpg')).not.toBeInTheDocument()
})

it('keeps the claimant model selector keyboard operable', async () => {
  const user = userEvent.setup()
  render(<ControlHarness />)

  const model = screen.getByRole('button', { name: 'Model' })
  expect(model).toHaveTextContent('Qwen Local')
  model.focus()
  await user.keyboard('{ArrowDown}')
  await waitFor(() => expect(screen.getByRole('option', { name: /Qwen Local/ })).toHaveFocus())
  await user.keyboard('{Enter}')
  expect(model).toHaveFocus()
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
