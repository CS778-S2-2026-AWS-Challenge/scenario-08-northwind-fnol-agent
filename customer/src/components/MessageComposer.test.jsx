import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
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

it('still offers a remove action once the upload has finished, since it has not been sent yet', async () => {
  const user = userEvent.setup()
  const onRemoved = vi.fn()
  render(<ComposerHarness initialStatus="uploaded" onRemoved={onRemoved} />)

  expect(screen.getByText('kitchen-damage.jpg')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Remove kitchen-damage.jpg' }))

  expect(onRemoved).toHaveBeenCalledWith(expect.objectContaining({ id: 'file-1' }))
  expect(screen.queryByText('kitchen-damage.jpg')).not.toBeInTheDocument()
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

class FakeSpeechRecognition {
  constructor() {
    FakeSpeechRecognition.instances.push(this)
    this.continuous = false
    this.interimResults = false
    this.start = vi.fn()
    this.stop = vi.fn(() => this.onend?.())
  }
}
FakeSpeechRecognition.instances = []

it('keeps recording across several utterances until the claimant stops it, without duplicating text', async () => {
  FakeSpeechRecognition.instances = []
  globalThis.SpeechRecognition = FakeSpeechRecognition
  const user = userEvent.setup()
  render(<ControlHarness />)

  const voice = screen.getByRole('button', { name: 'Use voice input' })
  await user.click(voice)

  expect(FakeSpeechRecognition.instances).toHaveLength(1)
  const recognition = FakeSpeechRecognition.instances[0]
  // The claimant should not have to re-trigger recognition after every pause.
  expect(recognition.continuous).toBe(true)

  // Two separate continuous-mode events, each only carrying its own new
  // result at event.resultIndex -- exactly what a real browser sends.
  await act(async () => {
    recognition.onresult({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'rear-ended on Symonds Street' } }] })
  })
  await act(async () => {
    recognition.onresult({
      resultIndex: 1,
      results: [
        { isFinal: true, 0: { transcript: 'rear-ended on Symonds Street' } },
        { isFinal: true, 0: { transcript: 'bumper is damaged' } },
      ],
    })
  })

  const textarea = screen.getByRole('textbox', { name: 'Claim message' })
  expect(textarea).toHaveValue('rear-ended on Symonds Street bumper is damaged')

  // A second click stops the same instance rather than starting a new one.
  const stopButton = screen.getByRole('button', { name: 'Stop voice input' })
  await user.click(stopButton)
  expect(recognition.stop).toHaveBeenCalledTimes(1)
  expect(FakeSpeechRecognition.instances).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Use voice input' })).toBeInTheDocument()
})
