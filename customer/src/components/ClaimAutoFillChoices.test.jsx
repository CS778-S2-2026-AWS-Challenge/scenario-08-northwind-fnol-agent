import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ClaimAutoFillChoices from './ClaimAutoFillChoices.jsx'

const choices = [
  { key: 'a', label: 'Personal details', visible: false },
  { key: 'b', label: 'Policy number', visible: false },
  { key: 'c', label: 'Saved assets', visible: false },
  { key: 'd', label: 'Payment details', visible: false },
  { key: 'e', label: 'Identity information', visible: false },
]

describe('ClaimAutoFillChoices presentation', () => {
  it('shows five independent account-choice controls and reports a changed choice', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const onSave = vi.fn()
    render(<ClaimAutoFillChoices choices={choices} onChange={onChange} onSave={onSave} />)

    expect(screen.getAllByRole('combobox')).toHaveLength(5)
    for (const choice of choices) {
      expect(screen.getByRole('combobox', { name: choice.label })).toHaveValue('hide')
    }
    expect(screen.getByRole('button', { name: 'Save Claim auto-fill choices' })).toBeDisabled()
    expect(screen.getByText(/payment details and identity information only prompt/i)).toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: 'Payment details' }), 'show')
    expect(onChange).toHaveBeenCalledWith('d', true)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onSave).not.toHaveBeenCalled()
  })

  it('offers save for a changed draft and exposes saving and error states', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn()
    const view = render(
      <ClaimAutoFillChoices choices={choices} dirty onChange={vi.fn()} onSave={onSave} />,
    )

    await user.click(screen.getByRole('button', { name: 'Save Claim auto-fill choices' }))
    expect(onSave).toHaveBeenCalledTimes(1)

    view.rerender(
      <ClaimAutoFillChoices choices={choices} dirty saving onChange={vi.fn()} onSave={onSave} />,
    )
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: 'Personal details' })).toBeDisabled()

    view.rerender(
      <ClaimAutoFillChoices choices={choices} dirty error="Your choices were not saved." onChange={vi.fn()} onSave={onSave} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Your choices were not saved.')
    expect(screen.getByRole('button', { name: 'Save Claim auto-fill choices' })).toBeEnabled()
  })
})
