import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { formatDate, formatDateTime, formatTime } from '../format.js'
import Activity from './Activity.jsx'

function renderActivity({
  events = [],
  updates = [],
  actions = [],
  eventNextCursor = null,
  updateNextCursor = null,
  actionNextCursor = null,
  sourceItems = [],
} = {}) {
  return render(
    <Activity
      detail={{ allowed_actions: [], source_summary: { items: sourceItems } }}
      resources={{
        handoffs: { items: [] },
        workItems: { items: actions, page: { next_cursor: actionNextCursor }, status: 'available' },
        events: { items: events, page: { next_cursor: eventNextCursor }, status: 'available' },
        customerUpdates: { items: updates, page: { next_cursor: updateNextCursor }, status: 'available' },
      }}
      onResolve={vi.fn()}
      onUpdateAction={vi.fn()}
      onRetry={vi.fn()}
    />,
  )
}

describe('Activity', () => {
  it('groups the authoritative event order by date and keeps readable context with exact technical references', async () => {
    const user = userEvent.setup()
    const events = [
      {
        event_id: 'evt_message',
        event_type: 'message.appended',
        summary: 'Staff message recorded.',
        actor_id: 'stf_demo',
        source_refs: ['msg_source', 'ses_source'],
        resulting_revision: 7,
        created_at: '2026-09-15T02:15:00Z',
      },
      {
        event_id: 'evt_work_item',
        event_type: 'work_item.completed',
        summary: 'Policy wording review completed.',
        created_at: '2026-09-15T01:45:00Z',
      },
      {
        event_id: 'evt_created',
        event_type: 'claim.created',
        summary: 'Claim context created.',
        source_refs: ['clm_demo'],
        resulting_revision: 1,
        created_at: '2026-09-13T23:30:00Z',
      },
    ]
    renderActivity({ events })

    const activity = screen.getByRole('region', { name: 'Claim activity' })
    expect(within(activity).getByText('3 events')).toBeVisible()
    expect(within(activity).getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)).toEqual([
      formatDate(events[0].created_at),
      formatDate(events[2].created_at),
    ])
    expect(within(activity).getAllByRole('article').map((article) => within(article).getByRole('heading', { level: 4 }).textContent)).toEqual([
      'Staff message recorded.',
      'Policy wording review completed.',
      'Claim context created.',
    ])
    expect(within(activity).getByText('Message.Appended')).toBeVisible()
    expect(within(activity).getByText('Work Item.Completed')).toBeVisible()
    expect(within(activity).getByText('Claim.Created')).toBeVisible()
    expect(within(activity).getByText(formatTime(events[0].created_at))).toHaveAttribute('datetime', events[0].created_at)
    const firstEvent = within(activity).getAllByRole('article')[0]
    expect(within(firstEvent).getByText('Recorded by')).toBeVisible()
    expect(within(firstEvent).getByText('Claims professional')).toBeVisible()
    expect(within(firstEvent).getByText('Related records')).toBeVisible()
    expect(within(firstEvent).getByText('Message · Conversation')).toBeVisible()
    expect(within(firstEvent).getByText(String(events[0].resulting_revision))).toBeVisible()
    expect(within(activity).getAllByRole('article')[2]).not.toHaveTextContent('Actor')

    const technicalSummary = within(firstEvent).getByText(/^Technical details/, { selector: 'summary' })
    const technicalDetails = technicalSummary.closest('details')
    expect(technicalDetails).not.toHaveAttribute('open')
    expect(within(technicalDetails).getByText(events[0].event_id)).not.toBeVisible()
    expect(within(technicalDetails).getByText(events[0].actor_id)).not.toBeVisible()
    expect(within(technicalDetails).getByText(events[0].source_refs[0])).not.toBeVisible()
    expect(within(technicalDetails).getByText(events[0].source_refs[1])).not.toBeVisible()

    await user.click(technicalSummary)

    expect(technicalDetails).toHaveAttribute('open')
    expect(within(technicalDetails).getByText(events[0].event_id)).toBeVisible()
    expect(within(technicalDetails).getByText(events[0].actor_id)).toBeVisible()
    expect(within(technicalDetails).getByText(events[0].source_refs[0])).toBeVisible()
    expect(within(technicalDetails).getByText(events[0].source_refs[1])).toBeVisible()

    const claimCreated = within(activity).getAllByRole('article')[2]
    expect(within(claimCreated).getByText('Claim record', { selector: 'dd' })).toBeVisible()
    expect(within(claimCreated).getByText('Claim version')).toBeVisible()
  })

  it('prefers authoritative source labels and uses a neutral fallback for unknown references', () => {
    const event = {
      event_id: 'act_review',
      event_type: 'work_item.completed',
      summary: 'Policy wording review completed.',
      source_refs: ['act_review', 'opaque-provider-reference'],
      created_at: '2026-09-15T02:15:00Z',
    }
    renderActivity({
      events: [event],
      sourceItems: [{ record_ref: 'act_review', label: 'Policy wording review' }],
    })

    const activity = screen.getByRole('region', { name: 'Claim activity' })
    const item = within(activity).getByRole('article')
    expect(within(item).getByText('Policy wording review · Supporting record')).toBeVisible()
    expect(within(item).queryByText('Opaque Provider Reference')).not.toBeInTheDocument()
    expect(within(item).getByText('opaque-provider-reference')).not.toBeVisible()
  })

  it('uses compact, distinct empty states for audited work and claimant-visible updates', () => {
    renderActivity()

    const actions = screen.getByRole('region', { name: 'Staff actions' })
    expect(within(actions).getByText('0 records')).toBeVisible()
    expect(within(actions).getByText('No staff actions yet')).toBeVisible()
    expect(within(actions).getByText(/Audited work items will appear here/)).toBeVisible()
    expect(within(actions).queryByRole('textbox')).not.toBeInTheDocument()

    const updates = screen.getByRole('region', { name: 'Customer updates' })
    expect(within(screen.getByRole('region', { name: 'Claim activity' })).getByText('0 events')).toBeVisible()
    expect(within(updates).getByText('0 updates')).toBeVisible()
    expect(within(updates).getByText('No customer updates yet')).toBeVisible()
    expect(within(updates).getByText(/Claimant-visible updates will appear here/)).toBeVisible()
  })

  it('keeps existing customer update content and its semantic timestamp visible', () => {
    const update = {
      update_id: 'upd_1',
      summary: 'We are waiting for the police report.',
      responsible_party: 'claims_professional',
      created_at: '2026-09-15T03:30:00Z',
    }
    renderActivity({ updates: [update] })

    const updates = screen.getByRole('region', { name: 'Customer updates' })
    expect(within(updates).getByText('1 update')).toBeVisible()
    expect(within(updates).getByText(update.summary)).toBeVisible()
    expect(within(updates).getByText('Claims Professional')).toBeVisible()
    expect(within(updates).getByText(formatDateTime(update.created_at))).toHaveAttribute('datetime', update.created_at)
  })

  it('marks section counts as partial when another resource page is available', () => {
    renderActivity({
      events: [{
        event_id: 'evt_1',
        event_type: 'claim.created',
        summary: 'Claim context created.',
        created_at: '2026-09-15T02:15:00Z',
      }],
      updates: [{
        update_id: 'upd_1',
        summary: 'Your claim is being reviewed.',
        responsible_party: 'claims_professional',
        created_at: '2026-09-15T02:15:00Z',
      }],
      actions: [{
        action_id: 'act_1',
        action_type: 'policy_review',
        status: 'completed',
        assigned_to: 'stf_demo',
        requested_outcome: 'Review the policy wording.',
        source_refs: [],
        created_at: '2026-09-15T02:15:00Z',
      }],
      eventNextCursor: 'event-page-2',
      updateNextCursor: 'update-page-2',
      actionNextCursor: 'action-page-2',
    })

    expect(within(screen.getByRole('region', { name: 'Claim activity' })).getByText('1+ events')).toBeVisible()
    expect(within(screen.getByRole('region', { name: 'Customer updates' })).getByText('1+ updates')).toBeVisible()
    expect(within(screen.getByRole('region', { name: 'Staff actions' })).getByText('1+ records')).toBeVisible()
  })
})
