import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage.jsx'
import { AuthContext } from '../auth/auth-context.js'

function LocationText() {
  const location = useLocation()
  return <output data-testid="destination">{location.pathname}{location.search}</output>
}

describe('LoginPage', () => {
  it('returns to the requested Workbench deep link after staff authentication', async () => {
    const user = userEvent.setup()
    const login = vi.fn().mockResolvedValue({ access_token: 'staff-token' })
    render(
      <AuthContext.Provider value={{ session: null, login }}>
        <MemoryRouter
          initialEntries={[{
            pathname: '/workbench/login',
            state: { from: '/workbench/conversations/ses_1?session=ses_1' },
          }]}
        >
          <Routes>
            <Route path="/workbench/login" element={<LoginPage />} />
            <Route path="*" element={<LocationText />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>,
    )

    await user.type(screen.getByLabelText('Work email'), 'staff@example.invalid')
    await user.type(screen.getByLabelText('Password'), 'password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(login).toHaveBeenCalledWith('staff@example.invalid', 'password')
    expect(await screen.findByTestId('destination')).toHaveTextContent(
      '/workbench/conversations/ses_1?session=ses_1',
    )
  })
})
