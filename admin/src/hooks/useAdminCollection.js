import { useCallback, useEffect, useState } from 'react'
import { adminFetch } from '../api.js'

export default function useAdminCollection(endpoint, token) {
  const [items, setItems] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [reloadVersion, setReloadVersion] = useState(0)
  const [resolvedRequest, setResolvedRequest] = useState('')

  const reload = useCallback(() => setReloadVersion((value) => value + 1), [])

  useEffect(() => {
    let cancelled = false
    const requestKey = `${endpoint}:${reloadVersion}`
    adminFetch(endpoint, { token })
      .then((payload) => {
        if (!cancelled) {
          setItems(payload.items || [])
          setStatus('ready')
          setError(null)
          setResolvedRequest(requestKey)
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setStatus('error')
          setError(reason)
          setResolvedRequest(requestKey)
        }
      })
    return () => { cancelled = true }
  }, [endpoint, reloadVersion, token])

  const requestKey = `${endpoint}:${reloadVersion}`
  return { items, status: resolvedRequest === requestKey ? status : 'loading', error, reload }
}
