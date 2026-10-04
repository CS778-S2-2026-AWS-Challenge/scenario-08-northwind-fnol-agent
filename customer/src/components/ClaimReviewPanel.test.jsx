import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ClaimReviewPanel, { ClaimNextStepsPanel, ClaimSummaryProgress } from './ClaimReviewPanel.jsx'

const labels = {
  'claim.product_family': 'Claim type',
  'incident.description': 'What happened',
  'incident.injury_or_danger': 'Injury or immediate danger',
  'incident.occurred_at': 'When it happened',
  'incident.location': 'Incident location',
  'loss.description': 'Damage or loss',
  'property.address': 'Affected property',
  'property.habitable': 'Property safe to live in',
}

function panelProps(overrides = {}) {
  return {
    form: {
      'claim.product_family': { value: 'home', status: 'confirmed', source: 'claimant' },
      'incident.description': { value: 'A pipe burst in the kitchen.', status: 'confirmed', source: 'claimant' },
      'property.address': { value: '1 Queen Street', status: 'proposed', source: 'inference' },
      'property.habitable': { value: true, status: 'confirmed', source: 'claimant' },
    },
    contentsItems: [],
    dynamicForm: {
      requirements: {
        ready: false,
        current_action_total: 8,
        missing_required_now: [
          'incident.injury_or_danger',
          'incident.occurred_at',
          'incident.location',
          'loss.description',
        ],
        pending_later: [],
      },
    },
    proposedFields: [['property.address', { value: '1 Queen Street' }]],
    proposedContentsItems: [],
    editingField: null,
    editValue: '',
    setEditValue: vi.fn(),
    beginEdit: vi.fn(),
    cancelEdit: vi.fn(),
    saveFieldCorrection: vi.fn(),
    confirmField: vi.fn(),
    onViewNextSteps: vi.fn(),
    fieldLabel: (fieldCode) => labels[fieldCode] || fieldCode,
    fieldStatusLabel: (status) => status === 'confirmed' ? 'Confirmed' : 'Needs review',
    fieldSourceLabel: (source) => source === 'inference' ? 'Suggested from your description' : 'Provided by you',
    fieldValueText: (field) => typeof field.value === 'boolean' ? (field.value ? 'Yes' : 'No') : String(field.value ?? ''),
    busy: false,
    status: 'idle',
    ...overrides,
  }
}

function renderPanel(overrides = {}) {
  const props = panelProps(overrides)
  render(<ClaimReviewPanel {...props} />)
  return props
}

describe('ClaimReviewPanel overview', () => {
  it('summarises known information without repeating the missing-question list', () => {
    renderPanel()

    // One sentence under "What we know"; progress lives in the title bar only.
    expect(screen.getByRole('heading', { name: 'What we know' })).toBeVisible()
    expect(screen.getByText('We still need incident, damage, and safety details before the claim can progress.')).toBeVisible()
    expect(screen.queryByText('4 of 8 details noted')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText('When did it happen?')).not.toBeInTheDocument()
    expect(screen.queryByText(/No details captured/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Add / })).not.toBeInTheDocument()
  })

  it('hides sections that have no captured information', () => {
    renderPanel({
      form: {
        'claim.product_family': { value: 'motor', status: 'confirmed', source: 'claimant' },
      },
      proposedFields: [],
    })

    expect(screen.getByRole('button', { name: /Claim overview.*Motor vehicle claim/i })).toBeVisible()
    expect(screen.queryByRole('button', { name: /^Incident details/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Insured item and loss/i })).not.toBeInTheDocument()
  })

  it('uses one compact list surface and reveals traceability on expansion', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    const incident = screen.getByRole('button', { name: /Incident details.*A pipe burst in the kitchen/i })
    expect(incident).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: /Insured item and loss.*Needs review/i })).toBeVisible()

    await user.click(incident)
    const editDetail = screen.getByRole('button', { name: 'Edit What happened' })
    expect(within(editDetail).getByText('Provided by you')).toBeVisible()
    expect(within(editDetail).getByText('Confirmed')).toBeVisible()

    await user.click(editDetail)
    expect(props.beginEdit).toHaveBeenCalledWith('incident.description', 'A pipe burst in the kitchen.')
  })

  it('goes to the still-needed details from the safety alert', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    const safety = screen.getByText('Safety information has not been confirmed.').closest('.overview-alert')
    await user.click(within(safety).getByRole('button', { name: 'Review' }))
    expect(props.onViewNextSteps).toHaveBeenCalledOnce()
  })

  it('shows only meaningful safety and review alerts', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    expect(screen.getByRole('heading', { name: 'Needs review' })).toBeVisible()
    expect(screen.getByText('Safety information has not been confirmed.')).toBeVisible()
    expect(screen.getByText('1 Agent-suggested detail needs your review.')).toBeVisible()

    const aiReview = screen.getByText('1 Agent-suggested detail needs your review.').closest('.overview-alert')
    await user.click(within(aiReview).getByRole('button', { name: 'Review' }))
    // Each suggested detail is confirmed on its own row; there is no confirm-all.
    expect(screen.queryByRole('button', { name: 'Confirm suggested details' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /is right$/ }))
    expect(props.confirmField).toHaveBeenCalledOnce()
  })

  it('renders the existing correction editor without creating independent Claim state', () => {
    const field = { value: 'A pipe burst.', status: 'confirmed', source: 'claimant' }
    const saveFieldCorrection = vi.fn()
    const setEditValue = vi.fn()
    renderPanel({
      form: { 'incident.description': field },
      proposedFields: [],
      dynamicForm: null,
      editingField: 'incident.description',
      editValue: 'A pipe burst in the kitchen.',
      setEditValue,
      saveFieldCorrection,
    })

    const editor = screen.getByLabelText('Correct What happened')
    fireEvent.change(editor, { target: { value: 'Updated' } })
    expect(setEditValue).toHaveBeenCalledWith('Updated')

    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }))
    expect(saveFieldCorrection).toHaveBeenCalledWith('incident.description', field)
  })

  it('gently marks the affected section when conversation data changes', () => {
    const props = panelProps()
    const { rerender } = render(<ClaimReviewPanel {...props} />)
    const updatedForm = {
      ...props.form,
      'incident.location': { value: 'Auckland', status: 'confirmed', source: 'claimant' },
    }

    rerender(<ClaimReviewPanel {...props} form={updatedForm} />)

    expect(screen.getByRole('button', { name: /Incident details.*A pipe burst/i }).closest('section')).toHaveClass('is-updated')
    expect(screen.getByRole('button', { name: /^Safety and ongoing risk/i }).closest('section')).not.toHaveClass('is-updated')
  })

  it('shows a quiet Overview empty state before a conversation starts', () => {
    renderPanel({
      form: {},
      proposedFields: [],
      dynamicForm: null,
      conversationEmpty: true,
    })

    expect(screen.getByText('Tell us what happened and the Agent will build this overview as you chat.')).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'What we know' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Needs review' })).not.toBeInTheDocument()
  })
})

describe('ClaimNextStepsPanel', () => {
  it('groups actionable questions without repeated Missing labels or decorative bullets', () => {
    const props = panelProps({
      dynamicForm: {
        requirements: {
          missing_required_now: [
            'incident.injury_or_danger',
            'incident.description',
            'incident.occurred_at',
            'incident.location',
          ],
          pending_later: ['incident.location', 'loss.description'],
        },
      },
    })
    render(<ClaimNextStepsPanel {...props} />)

    expect(screen.queryByRole('heading', { name: 'Next steps' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Still needed: safety' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Still needed' })).toBeVisible()
    expect(screen.getByText('Was anyone injured or in immediate danger?')).toBeVisible()
    expect(screen.getByText('Where did it happen?')).toBeVisible()
    expect(screen.getByText('What was damaged or lost?')).toBeVisible()
    expect(screen.queryByText('Missing')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Add / })).toHaveLength(5)
  })

  it('opens the shared field editor from an Add action', async () => {
    const user = userEvent.setup()
    const props = panelProps()
    render(<ClaimNextStepsPanel {...props} />)

    await user.click(screen.getByRole('button', { name: 'Add When did it happen?' }))
    expect(props.beginEdit).toHaveBeenCalledWith('incident.occurred_at', undefined)
  })

  it('says when nothing is still needed, without repeating what is known', () => {
    const props = panelProps({
      form: {
        'claim.product_family': { value: 'motor', status: 'confirmed', source: 'claimant' },
      },
      dynamicForm: {
        requirements: {
          ready: true,
          missing_required_now: [],
          pending_later: [],
        },
      },
    })
    render(<ClaimNextStepsPanel {...props} />)

    expect(screen.getByText('All required details are complete.')).toBeVisible()
    expect(screen.queryByText('Completed')).not.toBeInTheDocument()
    expect(screen.queryByText('Claim type')).not.toBeInTheDocument()
  })
})

describe('ClaimSummaryProgress', () => {
  it('renders the server-owned captured count as an accessible progress indicator', () => {
    render(
      <ClaimSummaryProgress
        dynamicForm={{ requirements: { ready: false, current_action_total: 11, missing_required_now: ['a', 'b', 'c', 'd', 'e', 'f'] } }}
      />,
    )

    expect(screen.getByText('5 of 11 noted')).toBeVisible()
    expect(screen.getByText('Saved automatically')).toBeVisible()
    expect(screen.getByRole('progressbar', { name: 'Claim details captured' })).toHaveAttribute('aria-valuenow', '5')
  })
})
