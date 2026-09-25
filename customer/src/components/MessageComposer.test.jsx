import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import MessageComposer from './MessageComposer.jsx'

const recognitionInstances = []

class FakeSpeechRecognition {
  constructor() {
    recognitionInstances.push(this)
    this.startCalls = 0
    this.stopCalls = 0
    this.abortCalls = 0
  }

  start() {
    this.startCalls += 1
    this.onstart?.()
  }

  stop() {
    this.stopCalls += 1
    this.onend?.()
  }

  abort() {
    this.abortCalls += 1
    this.onend?.()
  }
}

beforeEach(() => {
  recognitionInstances.length = 0
  globalThis.SpeechRecognition = FakeSpeechRecognition
  delete globalThis.webkitSpeechRecognition
})

afterEach(() => {
  delete globalThis.SpeechRecognition
  delete globalThis.webkitSpeechRecognition
})

function ComposerHarness({ onRemoved = vi.fn(), initialStatus = 'uploading', busy = false, disabled = false }) {
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
      busy={busy}
      disabled={disabled}
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

it('adds one final voice transcript to the draft and announces completion', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  const message = screen.getByRole('textbox', { name: 'Claim message' })
  await user.type(message, 'Existing details')
  const voice = screen.getByRole('button', { name: 'Use voice input' })
  await user.click(voice)

  const recognition = recognitionInstances[0]
  expect(voice).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('status')).toHaveAttribute('aria-atomic', 'true')
  expect(screen.getByRole('status')).toHaveTextContent('Listening...')

  recognition.onresult({
    resultIndex: 0,
    results: [{ isFinal: true, 0: { transcript: 'The car is still drivable.' } }],
  })
  recognition.onresult({
    resultIndex: 0,
    results: [{ isFinal: true, 0: { transcript: 'The car is still drivable.' } }],
  })
  recognition.onend()

  await waitFor(() => {
    expect(message).toHaveValue('Existing details The car is still drivable.')
    expect(screen.getByRole('status')).toHaveTextContent('Voice input added to your message.')
    expect(voice).toHaveAttribute('aria-pressed', 'false')
  })
})

it('stops listening when the voice control is activated again', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  const voice = screen.getByRole('button', { name: 'Use voice input' })
  await user.click(voice)
  // The claimant, not the browser's silence detection, decides when to stop.
  expect(recognitionInstances[0].continuous).toBe(true)
  await user.click(voice)

  expect(recognitionInstances[0].stopCalls).toBe(1)
  expect(voice).toHaveAttribute('aria-pressed', 'false')
  expect(screen.getByRole('status')).toHaveTextContent('Voice input stopped.')
})

it('does not change the draft when recognition ends without a transcript', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  const message = screen.getByRole('textbox', { name: 'Claim message' })
  await user.type(message, 'Existing details')
  const voice = screen.getByRole('button', { name: 'Use voice input' })
  await user.click(voice)
  recognitionInstances[0].onend()

  await waitFor(() => {
    expect(message).toHaveValue('Existing details')
    expect(voice).toHaveAttribute('aria-pressed', 'false')
  })
  expect(screen.getByRole('status')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('')
})

it('reports an unexpected aborted recognition as retryable', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  await user.click(screen.getByRole('button', { name: 'Use voice input' }))
  recognitionInstances[0].onerror({ error: 'aborted' })

  await waitFor(() => {
    expect(screen.getByRole('status')).toHaveTextContent('Voice input stopped unexpectedly. Try again.')
    expect(screen.getByRole('button', { name: 'Use voice input' })).toHaveAttribute('aria-pressed', 'false')
  })
})

it('normalizes only the whitespace boundary before a transcript', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  const message = screen.getByRole('textbox', { name: 'Claim message' })
  await user.type(message, 'Existing details  ')
  await user.click(screen.getByRole('button', { name: 'Use voice input' }))
  recognitionInstances[0].onresult({
    resultIndex: 0,
    results: [{ isFinal: true, 0: { transcript: 'More detail' } }],
  })

  await waitFor(() => expect(message).toHaveValue('Existing details More detail'))
})

it.each([
  ['not-allowed', 'Microphone permission was denied.'],
  ['no-speech', 'No speech was detected.'],
  ['audio-capture', 'No working microphone was found.'],
  ['network', 'Voice recognition could not reach the browser speech service.'],
])('explains the %s recognition error', async (error, message) => {
  const user = userEvent.setup()
  render(<ComposerHarness />)

  await user.click(screen.getByRole('button', { name: 'Use voice input' }))
  recognitionInstances[0].onerror({ error })

  await waitFor(() => {
    expect(screen.getByRole('status')).toHaveTextContent(message)
    expect(screen.getByRole('button', { name: 'Use voice input' })).toHaveAttribute('aria-pressed', 'false')
  })
})

it('reports unsupported browsers without constructing recognition', async () => {
  delete globalThis.SpeechRecognition
  const user = userEvent.setup()
  render(<ComposerHarness />)

  await user.click(screen.getByRole('button', { name: 'Use voice input' }))

  expect(recognitionInstances).toHaveLength(0)
  expect(screen.getByRole('status')).toHaveTextContent('Voice input is not available in this browser.')
})

it('does not start voice input while the composer is disabled', async () => {
  const user = userEvent.setup()
  render(<ComposerHarness disabled />)

  const voice = screen.getByRole('button', { name: 'Use voice input' })
  expect(voice).toBeDisabled()
  await user.click(voice)

  expect(recognitionInstances).toHaveLength(0)
})

it('aborts active recognition when the composer unmounts', async () => {
  const user = userEvent.setup()
  const { unmount } = render(<ComposerHarness />)

  await user.click(screen.getByRole('button', { name: 'Use voice input' }))
  unmount()

  expect(recognitionInstances[0].abortCalls).toBe(1)
})
