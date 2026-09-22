import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { formatDate, formatDateTime, formatTime } from '../format.js'
import Activity from './Activity.jsx'

function renderActivity({ events = [], updates = [], actions = [] } = {}) {
  return render(
    <Activity
      detail={{ allowed_actions: [] }}
      resources={{
        handoffs: { items: [] },
        workItems: { items: actions, status: 'available' },
        events: { items: events, status: 'available' },
        customerUpdates: { items: updates, status: 'available' },
      }}
      onResolve={vi.fn()}
      onUpdateAction={vi.fn()}
      onRetry={vi.fn()}
    />,
  )
}

describe('Activity', () => {
  it('groups the authoritative event order by date and keeps codes and timestamps as metadata', () => {
    const events = [
      {
        event_id: 'evt_message',
        event_type: 'message.appended',
        summary: 'Staff message recorded.',
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
        created_at: '2026-09-13T23:30:00Z',
      },
    ]
    renderActivity({ events })

    const activity = screen.getByRole('region', { name: 'Claim activity' })
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
  })

  it('uses compact, distinct empty states for audited work and claimant-visible updates', () => {
    renderActivity()

    const actions = screen.getByRole('region', { name: 'Staff actions' })
    expect(within(actions).getByText('0 records')).toBeVisible()
    expect(within(actions).getByText('No staff actions yet')).toBeVisible()
    expect(within(actions).getByText(/Audited work items will appear here/)).toBeVisible()
    expect(within(actions).queryByRole('textbox')).not.toBeInTheDocument()

    const updates = screen.getByRole('region', { name: 'Customer updates' })
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
    expect(within(updates).getByText(update.summary)).toBeVisible()
    expect(within(updates).getByText('Claims Professional')).toBeVisible()
    expect(within(updates).getByText(formatDateTime(update.created_at))).toHaveAttribute('datetime', update.created_at)
  })
})
