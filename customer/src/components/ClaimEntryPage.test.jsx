import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import ClaimEntryPage from './ClaimEntryPage.jsx'

vi.mock('./MessageComposer.jsx', () => ({
  default: () => <div data-testid="claim-composer">Claim composer</div>,
}))

describe('ClaimEntryPage saved claim row', () => {
  it('keeps resume outside the new-claim composer and activates the existing callback by keyboard', async () => {
    const user = userEvent.setup()
    const onContinue = vi.fn()

    const { container } = render(
      <ClaimEntryPage
        composer={{}}
        continueCard={{
          claimId: 'clm_saved',
          title: 'Motor claim',
          statusLabel: 'Draft',
          savedLabel: 'Saved 23:06',
          detail: 'Describe the accident and any injuries.',
        }}
        onContinue={onContinue}
        onOpenHowItWorks={vi.fn()}
      />,
    )

    const composer = screen.getByTestId('claim-composer').closest('.claim-starter')
    const resume = screen.getByRole('button', {
      name: 'Motor claim, Draft. Continue your claim. Next: Describe the accident and any injuries. Saved 23:06',
    })

    expect(within(composer).queryByRole('button', { name: /Continue your claim/ })).not.toBeInTheDocument()
    expect(resume).toHaveTextContent('Motor claim · Draft')
    expect(resume).toHaveTextContent('Continue your claim')
    expect(resume).toHaveTextContent('Next: Describe the accident and any injuries.')
    expect(resume).toHaveTextContent('Saved 23:06')
    expect(resume).not.toHaveTextContent(/Step \d+ of \d+/)
    expect(resume.querySelector('progress')).not.toBeInTheDocument()
    expect(container.querySelector('.entry-claim-stack')).toContainElement(composer)
    expect(container.querySelector('.entry-claim-stack')).toContainElement(resume)

    await user.tab()
    await user.keyboard('{Enter}')

    expect(onContinue).toHaveBeenCalledWith('clm_saved')
  })
})
