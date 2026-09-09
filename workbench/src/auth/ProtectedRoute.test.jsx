import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import ProtectedRoute from './ProtectedRoute.jsx'
import { AuthContext } from './auth-context.js'

function LocationText() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

describe('ProtectedRoute', () => {
  it('preserves a deep-link path and query for staff login redirect', () => {
    render(
      <AuthContext.Provider value={{ session: null, checking: false }}>
        <MemoryRouter initialEntries={["/workbench/conversations/ses_1?session=ses_1"]}>
          <Routes>
            <Route path="*" element={<ProtectedRoute><div>protected</div></ProtectedRoute>} />
            <Route path="/workbench/login" element={<LocationText />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>,
    )

    expect(screen.getByTestId('location')).toHaveTextContent('/workbench/login')
  })
})
