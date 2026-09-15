import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  it('opens from the closed native button with the keyboard', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    renderAgent({ open: false, onOpenChange })

    const trigger = screen.getByRole('button', { name: 'Open Staff Agent' })
    trigger.focus()
    await user.keyboard('{Enter}')

    expect(onOpenChange).toHaveBeenCalledWith(true)
  })

  it('keeps a dragged closed button inside the viewport without opening it', () => {
    const onOpenChange = vi.fn()
    const { container } = renderAgent({ open: false, onOpenChange })
    const trigger = screen.getByRole('button', { name: 'Open Staff Agent' })
    const widget = container.querySelector('.staff-agent')
    Object.defineProperties(widget, {
      offsetWidth: { configurable: true, value: 48 },
      offsetHeight: { configurable: true, value: 48 },
    })
    vi.spyOn(widget, 'getBoundingClientRect').mockReturnValue({
      left: 900,
      top: 650,
      right: 948,
      bottom: 698,
      width: 48,
      height: 48,
      x: 900,
      y: 650,
      toJSON: () => ({}),
    })
    trigger.setPointerCapture = vi.fn()
    trigger.hasPointerCapture = vi.fn(() => true)
    trigger.releasePointerCapture = vi.fn()

    fireEvent.pointerDown(trigger, { button: 0, pointerId: 1, clientX: 924, clientY: 674 })
    fireEvent.pointerMove(trigger, { pointerId: 1, clientX: 2000, clientY: 2000 })
    fireEvent.pointerUp(trigger, { pointerId: 1 })
    fireEvent.click(trigger)

    expect(widget).toHaveStyle({
      left: `${window.innerWidth - 48}px`,
      top: `${window.innerHeight - 48}px`,
    })
    expect(onOpenChange).not.toHaveBeenCalled()

    fireEvent.click(trigger)
    expect(onOpenChange).toHaveBeenCalledWith(true)
  })

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

  it('does not persist New until the first non-empty message and then uses the selected model', async () => {
    const user = userEvent.setup()
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({
      items: [{ session_id: 'sas_1', title: 'Evidence review', model_profile_id: 'staff-secondary' }],
    })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [
        { id: 'qwen-local', label: 'qwen3.8-27b' },
        { id: 'staff-secondary', label: 'Staff secondary' },
      ],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'staffAgentMessages').mockResolvedValue({
      items: [{
        message_id: 'sam_existing',
        role: 'assistant',
        content: 'Review the existing evidence.',
        claim_ids: [],
        drafts: [],
        source_refs: [],
      }],
    })
    vi.spyOn(workbenchApi, 'createStaffAgentSession').mockResolvedValue({
      session_id: 'sas_new',
      title: 'New Staff Agent session',
      model_profile_id: 'staff-secondary',
      created_at: '2026-09-14T00:10:00Z',
    })
    vi.spyOn(workbenchApi, 'sendStaffAgentMessage').mockResolvedValue({
      session: { session_id: 'sas_new', title: 'Question about evidence' },
      staff_message: {
        message_id: 'sam_staff',
        role: 'staff',
        content: 'What should I review next?',
        claim_ids: [],
        drafts: [],
        source_refs: [],
      },
      assistant_message: {
        message_id: 'sam_agent',
        role: 'assistant',
        content: 'Review the repair estimate next.',
        claim_ids: [],
        drafts: [],
        source_refs: [],
      },
    })

    render(<StatefulAgentHarness />)
    await screen.findByRole('option', { name: 'Staff secondary' })
    const sessionSelect = screen.getByLabelText('Session')
    const newSessionModelSelect = screen.getByLabelText('New session model')
    expect(sessionSelect).toHaveValue('sas_1')
    expect(newSessionModelSelect).toHaveValue('qwen-local')

    await user.selectOptions(newSessionModelSelect, 'staff-secondary')

    expect(sessionSelect).toHaveValue('sas_1')
    expect(workbenchApi.createStaffAgentSession).not.toHaveBeenCalled()
    const newSessionButton = screen.getByRole('button', { name: 'Start a new Staff Agent session' })
    await user.click(newSessionButton)

    expect(workbenchApi.createStaffAgentSession).not.toHaveBeenCalled()
    expect(sessionSelect).toHaveValue('')
    expect(screen.getByRole('option', { name: 'New conversation (not saved)' })).toBeInTheDocument()
    expect(screen.getByText('New conversation ready')).toBeInTheDocument()
    expect(screen.getByText('This conversation will be saved when you send the first message.')).toBeInTheDocument()
    const composer = screen.getByLabelText('Message Staff Agent')
    expect(composer).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Send to Staff Agent' })).toBeDisabled()

    await user.type(composer, '   ')
    expect(screen.getByRole('button', { name: 'Send to Staff Agent' })).toBeDisabled()
    expect(workbenchApi.createStaffAgentSession).not.toHaveBeenCalled()

    await user.clear(composer)
    await user.type(composer, 'What should I review next?')
    await user.click(screen.getByRole('button', { name: 'Send to Staff Agent' }))

    await waitFor(() => expect(workbenchApi.createStaffAgentSession).toHaveBeenCalledWith(
      'staff-token',
      'New Staff Agent session',
      'staff-secondary',
    ))
    expect(workbenchApi.sendStaffAgentMessage).toHaveBeenCalledWith(
      'staff-token',
      'sas_new',
      'What should I review next?',
      [],
    )
    expect(await screen.findByText('Review the repair estimate next.')).toBeInTheDocument()
  })

  it('reuses the current empty session when New is clicked', async () => {
    const user = userEvent.setup()
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({
      items: [{ session_id: 'sas_empty', title: 'New Staff Agent session', model_profile_id: 'qwen-local' }],
    })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [{ id: 'qwen-local', label: 'qwen3.8-27b' }],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'staffAgentMessages').mockResolvedValue({ items: [] })
    vi.spyOn(workbenchApi, 'createStaffAgentSession')

    renderAgent()
    await waitFor(() => expect(workbenchApi.staffAgentMessages).toHaveBeenCalledWith('staff-token', 'sas_empty'))
    const sessionSelect = screen.getByLabelText('Session')
    expect(sessionSelect).toHaveValue('sas_empty')

    await user.click(screen.getByRole('button', { name: 'Start a new Staff Agent session' }))

    expect(sessionSelect).toHaveValue('sas_empty')
    expect(screen.getByText('This conversation is already empty. Start typing to continue.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send to Staff Agent' })).toBeDisabled()
    expect(workbenchApi.createStaffAgentSession).not.toHaveBeenCalled()
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

  function mockDraftConversation(draft) {
    vi.spyOn(workbenchApi, 'staffAgentSessions').mockResolvedValue({
      items: [{ session_id: 'sas_1', title: 'Action review', model_profile_id: 'qwen-local' }],
    })
    vi.spyOn(workbenchApi, 'staffAgentCapabilities').mockResolvedValue({
      models: [{ id: 'qwen-local', label: 'qwen3.8-27b' }],
      default_model_profile_id: 'qwen-local',
    })
    vi.spyOn(workbenchApi, 'claims').mockResolvedValue({ items: [claim] })
    vi.spyOn(workbenchApi, 'staffAgentMessages').mockResolvedValue({
      items: [{
        session_id: 'sas_1',
        message_id: 'sam_action',
        role: 'assistant',
        content: 'I prepared a bounded staff action.',
        claim_ids: ['clm_1'],
        drafts: [draft],
        source_refs: ['claim:clm_1:revision:4'],
      }],
    })
  }

  function executableDraft(overrides = {}) {
    return {
      draft_id: 'sad_1',
      claim_id: 'clm_1',
      action_code: 'work_item.update',
      target_ref: 'wki_1',
      kind: 'staff_action',
      title: 'Progress work item',
      content: 'Move the assigned work item to in progress.',
      payload: { status: 'in_progress', note: 'Staff confirmed.' },
      ...overrides,
    }
  }

  it('keeps informational drafts copy/edit-only without an execution control', async () => {
    mockDraftConversation({
      kind: 'claimant_message',
      title: 'Claimant reply',
      content: 'Please send the repair estimate.',
      claim_id: 'clm_1',
    })

    renderAgent()

    expect(await screen.findByLabelText('Edit Claimant reply')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Review action' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm and execute' })).not.toBeInTheDocument()
  })

  it('requires two-step confirmation, re-reads the Claim, and renders authoritative success', async () => {
    const user = userEvent.setup()
    const draft = executableDraft()
    mockDraftConversation(draft)
    vi.spyOn(workbenchApi, 'claim').mockResolvedValue({ ...claim, revision: 9 })
    vi.spyOn(workbenchApi, 'executeStaffAgentDraft').mockResolvedValue({
      claim_id: 'clm_1',
      action_code: 'work_item.update',
      outcome: 'executed',
      result: {
        action: { action_id: 'wki_1', status: 'in_progress' },
        revision: 10,
      },
      runtime_execution: {
        outcome: 'executed',
        resulting_revision: 10,
        result: {
          action: { action_id: 'wki_1', status: 'in_progress' },
          revision: 10,
        },
      },
    })

    renderAgent()

    const review = await screen.findByRole('button', { name: 'Review action' })
    expect(screen.queryByRole('button', { name: 'Confirm and execute' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Review Progress work item')).toHaveAttribute('readonly')

    await user.click(review)
    const confirm = screen.getByRole('button', { name: 'Confirm and execute' })
    expect(workbenchApi.claim).not.toHaveBeenCalled()
    expect(workbenchApi.executeStaffAgentDraft).not.toHaveBeenCalled()

    await user.click(confirm)

    await waitFor(() => expect(workbenchApi.claim).toHaveBeenCalledWith('staff-token', 'clm_1'))
    expect(workbenchApi.executeStaffAgentDraft).toHaveBeenCalledWith(
      'staff-token',
      'sas_1',
      'sam_action',
      'sad_1',
      9,
      draft.payload,
    )
    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent('Workbench outcome: Executed')
    expect(result).toHaveTextContent('Work item status: In Progress')
    expect(result).toHaveTextContent('Work item: wki_1')
    expect(result).toHaveTextContent('Claim revision: 10')
  })



  it('re-reads the Claim on an ambiguous retry while preserving the saved draft operation boundary', async () => {
    const user = userEvent.setup()
    const draft = executableDraft()
    mockDraftConversation(draft)
    vi.spyOn(workbenchApi, 'claim')
      .mockResolvedValueOnce({ ...claim, revision: 9 })
      .mockResolvedValueOnce({ ...claim, revision: 10 })
    const executeDraft = vi.spyOn(workbenchApi, 'executeStaffAgentDraft')
      .mockRejectedValueOnce(new ApiError(
        'The Workbench service could not be reached.',
        { code: 'NETWORK_ERROR', retryable: true },
      ))
      .mockResolvedValueOnce({
        claim_id: 'clm_1',
        action_code: 'work_item.update',
        outcome: 'executed',
        result: {
          action: { action_id: 'wki_1', status: 'in_progress' },
          revision: 10,
        },
        runtime_execution: {
          outcome: 'executed',
          resulting_revision: 10,
          result: {
            action: { action_id: 'wki_1', status: 'in_progress' },
            revision: 10,
          },
        },
      })

    renderAgent()
    await user.click(await screen.findByRole('button', { name: 'Review action' }))
    await user.click(screen.getByRole('button', { name: 'Confirm and execute' }))

    const unknown = await screen.findByRole('alert')
    expect(unknown).toHaveTextContent('Execution outcome unknown')
    expect(unknown).toHaveTextContent('The Workbench service could not be reached.')
    expect(unknown).toHaveTextContent('Retry this same saved draft')

    await user.click(screen.getByRole('button', { name: 'Confirm and execute' }))

    await waitFor(() => expect(workbenchApi.claim).toHaveBeenCalledTimes(2))
    expect(executeDraft).toHaveBeenNthCalledWith(
      1,
      'staff-token',
      'sas_1',
      'sam_action',
      'sad_1',
      9,
      draft.payload,
    )
    expect(executeDraft).toHaveBeenNthCalledWith(
      2,
      'staff-token',
      'sas_1',
      'sam_action',
      'sad_1',
      10,
      draft.payload,
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Workbench outcome: Executed')
  })

  it.each([
    ['CONFIRMATION_REQUIRED', 'nothing was executed'],
    ['ACCESS_DENIED', 'not authorised'],
    ['REVISION_CONFLICT', 'Claim changed before execution'],
    ['DEPENDENCY_UNAVAILABLE', 'required service is unavailable'],
    ['IDEMPOTENCY_CONFLICT', 'was not run again'],
    ['UNEXPECTED_FAILURE', 'Unexpected execution failure'],
  ])('keeps %s failures visibly unexecuted', async (code, expected) => {
    const user = userEvent.setup()
    mockDraftConversation(executableDraft())
    vi.spyOn(workbenchApi, 'claim').mockResolvedValue({ ...claim, revision: 9 })
    vi.spyOn(workbenchApi, 'executeStaffAgentDraft').mockRejectedValue(new ApiError(
      code === 'UNEXPECTED_FAILURE' ? 'Unexpected execution failure' : 'Execution rejected',
      { status: 409, code, requestId: 'req-action-1' },
    ))

    renderAgent()
    await user.click(await screen.findByRole('button', { name: 'Review action' }))
    await user.click(screen.getByRole('button', { name: 'Confirm and execute' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Action not executed')
    expect(alert).toHaveTextContent(expected)
    expect(screen.queryByText('Executed by Workbench')).not.toBeInTheDocument()
  })

  it('preserves authoritative success when the post-execution refresh fails', async () => {
    const user = userEvent.setup()
    mockDraftConversation(executableDraft())
    vi.spyOn(workbenchApi, 'claim').mockResolvedValue({ ...claim, revision: 9 })
    vi.spyOn(workbenchApi, 'executeStaffAgentDraft').mockResolvedValue({
      claim_id: 'clm_1',
      action_code: 'work_item.update',
      outcome: 'executed',
      result: {
        action: { action_id: 'wki_1', status: 'in_progress' },
        revision: 10,
      },
      runtime_execution: {
        outcome: 'executed',
        resulting_revision: 10,
        result: {
          action: { action_id: 'wki_1', status: 'in_progress' },
          revision: 10,
        },
      },
    })
    const refreshError = Object.assign(
      new Error('Action executed, but refresh failed for Claim queue, open Claim. Refresh before taking another action.'),
      { requestId: 'req-refresh-1' },
    )

    renderAgent({
      onBusinessActionExecuted: vi.fn().mockRejectedValue(refreshError),
    })
    await user.click(await screen.findByRole('button', { name: 'Review action' }))
    await user.click(screen.getByRole('button', { name: 'Confirm and execute' }))

    expect(await screen.findByText('Workbench outcome: Executed')).toBeInTheDocument()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Action executed; refresh required')
    expect(alert).toHaveTextContent('Claim queue, open Claim')
    expect(alert).toHaveTextContent('Reference: req-refresh-1')
  })

})
