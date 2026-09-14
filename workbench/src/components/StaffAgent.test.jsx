import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, workbenchApi } from '../api.js'
import StaffAgent from './StaffAgent.jsx'

afterEach(() => vi.restoreAllMocks())

const claim = {
  claim_id: 'clm_1',
  display_reference: 'NW-1042',
  incident: { summary: 'Rear-end collision on Queen Street.' },
}

function renderAgent(overrides = {}) {
  return render(
    <StaffAgent
      open
      onOpenChange={vi.fn()}
      requestedSessionId={null}
      token="staff-token"
      onSessionChange={vi.fn()}
      onConversationChanged={vi.fn()}
      {...overrides}
    />,
  )
}

function StatefulAgentHarness() {
  const [requestedSessionId, setRequestedSessionId] = useState(null)
  return (
    <StaffAgent
      open
      onOpenChange={vi.fn()}
      requestedSessionId={requestedSessionId}
      token="staff-token"
      onSessionChange={(sessionId) => setRequestedSessionId(sessionId)}
      onConversationChanged={vi.fn()}
    />
  )
}

describe('StaffAgent', () => {
  it('restores a requested persistent session and its messages', async () => {
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({
      items: [{ session_id: 'sas_1', title: 'Evidence review', model_profile_id: 'qwen-local' }],
    })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [{ id: 'qwen-local', label: 'qwen3.8-27b' }],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'staffAgentMessages').mockResolvedValue({
      items: [{
        message_id: 'sam_1',
        role: 'assistant',
        content: 'Check the police report status.',
        claim_ids: ['clm_1'],
        drafts: [],
        source_refs: ['claim:clm_1:revision:4'],
      }],
    })

    renderAgent({ requestedSessionId: 'sas_1' })

    expect(await screen.findByText('Check the police report status.')).toBeInTheDocument()
    expect(workbenchApi.staffAgentMessages).toHaveBeenCalledWith('staff-token', 'sas_1')
    expect(screen.getByText('1 Claim attached')).toBeInTheDocument()
  })

  it('sends only the Claims explicitly selected for the next question', async () => {
    const user = userEvent.setup()
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({ items: [] })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [{ id: 'qwen-local', label: 'qwen3.8-27b' }],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'createStaffAgentSession').mockResolvedValue({
      session_id: 'sas_new',
      title: 'New Staff Agent session',
      model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'sendStaffAgentMessage').mockResolvedValue({
      session: { session_id: 'sas_new', title: 'Question about evidence' },
      staff_message: {
        message_id: 'sam_staff',
        role: 'staff',
        content: 'What evidence is still missing?',
        claim_ids: ['clm_1'],
        drafts: [],
        source_refs: [],
      },
      assistant_message: {
        message_id: 'sam_agent',
        role: 'assistant',
        content: 'The police report is still pending.',
        claim_ids: ['clm_1'],
        drafts: [],
        source_refs: ['claim:clm_1:revision:4'],
      },
    })

    renderAgent()
    await waitFor(() => expect(workbenchApi.claims).toHaveBeenCalled())
    const scopeToggle = screen.getByRole('button', { name: /claim scope/i })
    expect(scopeToggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(scopeToggle)
    expect(scopeToggle).toHaveAttribute('aria-expanded', 'true')
    const claimCheckbox = screen.getByRole('checkbox', { name: /NW-1042/i })
    await user.click(claimCheckbox)
    expect(claimCheckbox).toBeChecked()
    expect(scopeToggle).toHaveTextContent('1 Claim attached · NW-1042')
    expect(screen.getByText('1 of 5')).toBeInTheDocument()
    expect(screen.getByText('1 Claim attached. Changes apply immediately.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Done' }))
    expect(scopeToggle).toHaveAttribute('aria-expanded', 'false')
    await user.type(screen.getByLabelText('Message Staff Agent'), 'What evidence is still missing?')
    await user.click(screen.getByRole('button', { name: 'Send to Staff Agent' }))

    expect(workbenchApi.sendStaffAgentMessage).toHaveBeenCalledWith(
      'staff-token',
      'sas_new',
      'What evidence is still missing?',
      ['clm_1'],
    )
    expect(await screen.findByText('The police report is still pending.')).toBeInTheDocument()
  })

  it('uses the selected model when the explicit New session action is used', async () => {
    const user = userEvent.setup()
    let resolveCreateSession
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({
      items: [{ session_id: 'sas_1', title: 'Evidence review', model_profile_id: 'qwen-local' }],
    })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [
        { id: 'qwen-local', label: 'qwen3.8-27b' },
        { id: 'staff-secondary', label: 'Staff secondary' },
      ],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'staffAgentMessages').mockResolvedValue({ items: [] })
    vi.spyOn(workbenchApi, 'createStaffAgentSession').mockImplementation(() => new Promise((resolve) => {
      resolveCreateSession = resolve
    }))

    render(<StatefulAgentHarness />)
    await screen.findByRole('option', { name: 'Staff secondary' })
    await user.selectOptions(screen.getByLabelText('Model'), 'staff-secondary')
    const newSessionButton = screen.getByRole('button', { name: 'Start a new Staff Agent session' })
    await user.click(newSessionButton)

    expect(newSessionButton).toBeDisabled()
    expect(newSessionButton).toHaveTextContent('Starting...')
    resolveCreateSession({
      session_id: 'sas_new',
      title: 'New Staff Agent session',
      model_profile_id: 'staff-secondary',
      created_at: '2026-09-14T00:10:00Z',
    })

    await waitFor(() => expect(workbenchApi.createStaffAgentSession).toHaveBeenCalledWith(
      'staff-token',
      'New Staff Agent session',
      'staff-secondary',
    ))
    expect(workbenchApi.staffAgentMessages).toHaveBeenCalledWith('staff-token', 'sas_new')
    expect(await screen.findByText('New session ready')).toBeInTheDocument()
    expect(screen.getByText('Ask a general question or attach Claim context to begin.')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /^Created .*2026/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Message Staff Agent')).toHaveFocus()
  })

  it('preserves the draft and identifies a model service failure accurately', async () => {
    const user = userEvent.setup()
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({
      items: [{ session_id: 'sas_1', title: 'Evidence review', model_profile_id: 'qwen-local' }],
    })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [{ id: 'qwen-local', label: 'qwen3.8-27b' }],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'staffAgentMessages').mockResolvedValue({ items: [] })
    vi.spyOn(workbenchApi, 'sendStaffAgentMessage').mockRejectedValue(new ApiError(
      'The model service could not complete the request. The claim is unchanged.',
      { status: 502, code: 'DEPENDENCY_FAILED', requestId: 'req-model-42' },
    ))

    renderAgent()
    await waitFor(() => expect(workbenchApi.staffAgentMessages).toHaveBeenCalledWith('staff-token', 'sas_1'))
    const composer = screen.getByLabelText('Message Staff Agent')
    await user.type(composer, '1111')
    await user.click(screen.getByRole('button', { name: 'Send to Staff Agent' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The model could not complete this request')
    expect(alert).toHaveTextContent('Claim Scope was not the cause.')
    expect(alert).toHaveTextContent('ask the runtime administrator to check the selected model')
    expect(alert).not.toHaveTextContent('choose another model')
    expect(alert).toHaveTextContent('Reference: req-model-42')
    expect(composer).toHaveValue('1111')
    expect(screen.getByRole('button', { name: 'Send to Staff Agent' })).toBeEnabled()
  })
})
