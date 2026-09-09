import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { workbenchApi } from '../api.js'
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
    await user.click(screen.getByRole('button', { name: /claim scope/i }))
    await user.click(screen.getByRole('checkbox', { name: /NW-1042/i }))
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
})
