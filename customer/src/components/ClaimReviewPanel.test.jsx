import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ClaimReviewPanel from './ClaimReviewPanel.jsx'

const labels = {
  'claim.product_family': 'Claim type',
  'incident.description': 'What happened',
  'incident.occurred_at': 'When it happened',
  'property.address': 'Affected property',
}

function renderPanel(overrides = {}) {
  const props = {
    form: {
      'claim.product_family': { value: 'home', status: 'confirmed', source: 'claimant' },
      'incident.description': { value: 'A pipe burst.', status: 'confirmed', source: 'claimant' },
      'property.address': { value: '1 Queen Street', status: 'proposed', source: 'claimant' },
    },
    contentsItems: [],
    dynamicForm: {
      requirements: {
        ready: false,
        missing_required_now: ['incident.occurred_at'],
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
    confirmProposedFields: vi.fn(),
    fieldLabel: (fieldCode) => labels[fieldCode] || fieldCode,
    fieldStatusLabel: (status) => status === 'confirmed' ? 'Confirmed' : 'Check this',
    fieldSourceLabel: () => 'Provided by you',
    fieldValueText: (field) => String(field.value ?? ''),
    busy: false,
    status: 'idle',
    stepActive: true,
    ...overrides,
  }

  render(<ClaimReviewPanel {...props} />)
  return props
}

describe('ClaimReviewPanel', () => {
  it('shows Step 2, grouped Claim state, and backend-owned missing requirements', () => {
    renderPanel()

    expect(screen.getByText('Step 2 of 4 · Review information')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Claim overview' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Incident details' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Insured item and loss' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Still needed' })).toBeInTheDocument()
    expect(screen.getByText('When it happened')).toBeInTheDocument()
    expect(screen.getByText('A pipe burst.')).toBeInTheDocument()
  })

  it('keeps correction and confirmation actions delegated to App-owned API commands', () => {
    const props = renderPanel()

    const editButtons = screen.getAllByRole('button', { name: 'Edit' })
    fireEvent.click(editButtons[0])
    expect(props.beginEdit).toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm details' }))
    expect(props.confirmProposedFields).toHaveBeenCalledTimes(1)
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

  it('shows contents items as review data without inventing an edit contract', () => {
    renderPanel({
      form: {},
      proposedFields: [],
      dynamicForm: null,
      contentsItems: [
        {
          item_id: 'item-1',
          description: 'Laptop',
          category: 'Electronics',
          status: 'confirmed',
          source: 'claimant',
        },
      ],
    })

    expect(screen.getByRole('heading', { name: 'Insured item and loss' })).toBeInTheDocument()
    expect(screen.getByText('Laptop')).toBeInTheDocument()
    expect(screen.getByText('Electronics')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })
})
