import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import AccountMenu from './AccountMenu.jsx'

const profile = {
  staff_id: 'stf_menu',
  display_name: 'Alex Morgan',
  email: 'alex@example.invalid',
  roles: ['claims_professional'],
}

function renderMenu(onLogout = vi.fn().mockResolvedValue(undefined)) {
  render(
    <MemoryRouter initialEntries={['/workbench/settings/profile']}>
      <main><h1>Workbench</h1><AccountMenu profile={profile} onLogout={onLogout} /></main>
    </MemoryRouter>,
  )
  return onLogout
}

describe('AccountMenu', () => {
  it('opens the account menu without signing out and closes outside it', async () => {
    const user = userEvent.setup()
    const onLogout = renderMenu()
    const trigger = screen.getByRole('button', { name: 'Account menu for Alex Morgan' })

    await user.click(trigger)

    expect(onLogout).not.toHaveBeenCalled()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menuitem', { name: /Profile/ })).toHaveAttribute('aria-current', 'page')

    await user.click(screen.getByRole('heading', { name: 'Workbench' }))
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('supports arrow navigation and returns focus to the trigger on Escape', async () => {
    const user = userEvent.setup()
    renderMenu()
    const trigger = screen.getByRole('button', { name: 'Account menu for Alex Morgan' })

    trigger.focus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: /Profile/ })).toHaveFocus()

    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: /Account & Security/ })).toHaveFocus()

    await user.keyboard('{End}')
    expect(screen.getByRole('menuitem', { name: /Sign out/ })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('runs the existing logout callback only after confirmation', async () => {
    const user = userEvent.setup()
    const onLogout = renderMenu()
    const trigger = screen.getByRole('button', { name: 'Account menu for Alex Morgan' })

    await user.click(trigger)
    await user.click(screen.getByRole('menuitem', { name: /Sign out/ }))

    expect(onLogout).not.toHaveBeenCalled()
    const dialog = screen.getByRole('alertdialog', { name: 'Sign out of your account?' })
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    const confirm = screen.getByRole('button', { name: 'Sign out' })
    expect(dialog).toBeInTheDocument()
    expect(cancel).toHaveFocus()

    await user.tab({ shift: true })
    expect(confirm).toHaveFocus()
    await user.tab()
    expect(cancel).toHaveFocus()

    await user.click(cancel)
    expect(onLogout).not.toHaveBeenCalled()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    await user.click(screen.getByRole('menuitem', { name: /Sign out/ }))
    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})
