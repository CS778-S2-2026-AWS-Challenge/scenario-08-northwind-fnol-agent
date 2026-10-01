import { useCallback, useEffect, useMemo, useState } from 'react'
import { applyAppearanceSettings, browserStaffSettingsGateway } from '../account/settings-gateway.js'
import { clearStoredSession, readStoredSession, storeSession, workbenchApi } from '../api.js'
import { AuthContext } from './auth-context.js'

const STAFF_PRESENCE_LEASE_SECONDS = 300
const STAFF_PRESENCE_RENEWAL_INTERVAL_MS = 120_000

export function AuthProvider({ children }) {
  const [session, setSession] = useState(readStoredSession)
  const [profile, setProfile] = useState(null)
  const [presenceRevision, setPresenceRevision] = useState(null)
  const [checking, setChecking] = useState(Boolean(session))

  const clear = useCallback(() => {
    clearStoredSession()
    setSession(null)
    setProfile(null)
    setPresenceRevision(null)
    setChecking(false)
  }, [])

  useEffect(() => {
    if (!session) return
    let active = true
    Promise.all([
      workbenchApi.session(session.access_token),
      workbenchApi.profile(session.access_token),
    ])
      .then(async ([, nextProfile]) => {
        let presence = null
        try {
          presence = await renewStaffPresence(session.access_token)
        } catch {
          // Authentication remains usable when the presence service is temporarily unavailable.
        }
        if (active) {
          setPresenceRevision(presence?.revision ?? null)
          setProfile(nextProfile)
        }
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

  useEffect(() => {
    if (!profile || !session?.access_token) return undefined
    let active = true
    let inFlight = null
    const renew = () => {
      if (inFlight) return inFlight
      inFlight = renewStaffPresence(session.access_token)
        .then((presence) => {
          if (active) setPresenceRevision(presence.revision)
          return presence
        })
        .catch(() => null)
        .finally(() => { inFlight = null })
      return inFlight
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') renew()
    }
    const interval = window.setInterval(renew, STAFF_PRESENCE_RENEWAL_INTERVAL_MS)
    window.addEventListener('focus', renew)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      active = false
      window.clearInterval(interval)
      window.removeEventListener('focus', renew)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [profile, session])

  useEffect(() => {
    if (!profile) return undefined
    let active = true
    browserStaffSettingsGateway.load(profile).then((settings) => {
      if (active) applyAppearanceSettings(settings.appearance)
    }).catch(() => null)
    return () => { active = false }
  }, [profile])

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
    () => ({ session, profile, presenceRevision, checking, token: session?.access_token || null, login, logout }),
    [session, profile, presenceRevision, checking, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function renewStaffPresence(token) {
  return workbenchApi.updatePresence(token, {
    leaseSeconds: STAFF_PRESENCE_LEASE_SECONDS,
  })
}
