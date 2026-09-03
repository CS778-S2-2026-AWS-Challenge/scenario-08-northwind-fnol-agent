import { useCallback, useEffect, useMemo, useState } from 'react'
import { clearStoredSession, readStoredSession, storeSession, workbenchApi } from '../api.js'
import { AuthContext } from './auth-context.js'

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readStoredSession)
  const [profile, setProfile] = useState(null)
  const [checking, setChecking] = useState(Boolean(session))

  const clear = useCallback(() => {
    clearStoredSession()
    setSession(null)
    setProfile(null)
    setChecking(false)
  }, [])

  useEffect(() => {
    if (!session) return
    let active = true
    Promise.all([
      workbenchApi.session(session.access_token),
      workbenchApi.profile(session.access_token),
    ])
      .then(([, nextProfile]) => {
        if (active) setProfile(nextProfile)
      })
      .catch(() => {
        if (active) clear()
      })
      .finally(() => {
        if (active) setChecking(false)
      })
    return () => {
      active = false
    }
  }, [clear, session])

  const login = useCallback(async (email, password) => {
    const nextSession = await workbenchApi.login(email, password)
    storeSession(nextSession)
    setSession(nextSession)
    setChecking(true)
    return nextSession
  }, [])

  const logout = useCallback(async () => {
    const token = session?.access_token
    clear()
    if (token) await workbenchApi.logout(token).catch(() => null)
  }, [clear, session])

  const value = useMemo(
    () => ({ session, profile, checking, token: session?.access_token || null, login, logout }),
    [session, profile, checking, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
