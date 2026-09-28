import { useCallback, useEffect, useState } from 'react'
import { browserStaffSettingsGateway } from './settings-gateway.js'

export function useStaffSettings(profile, gateway = browserStaffSettingsGateway, token = null) {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    gateway.load(profile).then(
      (value) => {
        if (active) setSettings(value)
      },
      (loadError) => {
        if (active) setError(loadError)
      },
    ).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [attempt, gateway, profile])

  const update = useCallback(async (operation) => {
    const next = await operation()
    setSettings(next)
    return next
  }, [])

  return {
    settings,
    loading,
    error,
    retry: () => {
      setLoading(true)
      setError(null)
      setAttempt((value) => value + 1)
    },
    saveProfile: (values) => update(() => gateway.saveProfile(profile, values)),
    saveAvatar: (file) => update(() => gateway.saveAvatar(profile, file)),
    saveNotifications: (values) => update(() => gateway.saveNotifications(profile, values)),
    saveAppearance: (values) => update(() => gateway.saveAppearance(profile, values)),
    performSecurityAction: (action, payload) => gateway.performSecurityAction(profile, action, payload),
    openHelpTarget: (kind) => gateway.openHelpTarget(profile, kind),
    submitFeedback: (message) => gateway.submitFeedback(profile, message, token),
  }
}
