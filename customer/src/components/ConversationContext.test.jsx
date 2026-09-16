import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ClaimProgressDisclosure } from './ConversationContext.jsx'

const BASE_PROGRESS = {
  available: true,
  label: 'In progress',
  items: [],
}

function ProgressHarness({ progress }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <ClaimProgressDisclosure
      progress={progress}
      expanded={expanded}
      onToggle={() => setExpanded((current) => !current)}
    />
  )
}

describe('Claim progress disclosure', () => {
  it.each([
    [0, 6, '0%'],
    [3, 6, '50%'],
    [6, 6, '100%'],
  ])('renders the backend aggregate %s/%s as %s', (current, total, width) => {
    const { container } = render(
      <ClaimProgressDisclosure
        progress={{ ...BASE_PROGRESS, current, total }}
        expanded={false}
        onToggle={vi.fn()}
      />,
    )

    const progressbar = screen.getByRole('progressbar', {
      name: `${current} of ${total} required details complete`,
    })
    expect(progressbar).toHaveAttribute('aria-valuenow', String(current))
    expect(progressbar).toHaveAttribute('aria-valuemax', String(total))
    expect(container.querySelector('.claim-progress-fill').style.getPropertyValue('--progress-width'))
      .toBe(width)
  })

  it('reveals the projected requirement states only after the claimant expands it', async () => {
    const user = userEvent.setup()
    render(
      <ProgressHarness progress={{
        ...BASE_PROGRESS,
        current: 1,
        total: 2,
        items: [
          { fieldCode: 'incident.description', label: 'Incident description', state: 'complete' },
          { fieldCode: 'incident.location', label: 'Incident location', state: 'required' },
        ],
      }} />,
    )

    const trigger = screen.getByRole('button', { name: /Claim progress:/ })
    const requirements = screen.getByRole('list', { name: 'Claim requirements', hidden: true })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(requirements).not.toBeVisible()

    await user.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(requirements).toBeVisible()
    expect(requirements).toHaveTextContent('Complete: Incident description')
    expect(requirements).toHaveTextContent('Required: Incident location')
  })
})
