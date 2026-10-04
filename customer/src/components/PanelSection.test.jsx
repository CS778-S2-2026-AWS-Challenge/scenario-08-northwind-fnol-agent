import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import PanelSection from './PanelSection.jsx'

describe('PanelSection', () => {
  it('folds from its title text', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const { rerender } = render(<PanelSection id="files" title="Files" open onToggle={onToggle}><p>Repair quote</p></PanelSection>)

    const title = screen.getByRole('button', { name: 'Files' })
    expect(title).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Repair quote')).toBeVisible()
    await user.click(title)
    expect(onToggle).toHaveBeenCalledOnce()

    rerender(<PanelSection id="files" title="Files" open={false} onToggle={onToggle}><p>Repair quote</p></PanelSection>)
    expect(screen.getByRole('button', { name: 'Files' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Repair quote')).not.toBeVisible()
  })
})
