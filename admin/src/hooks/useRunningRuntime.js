import { useEffect, useState } from 'react'

// The environment and data runtime profile the backend is running now, read from the
// readiness check. Forms use them as defaults so an operator edits the live runtime.
export default function useRunningRuntime() {
  const [running, setRunning] = useState(null)
  useEffect(() => {
    let active = true
    fetch('/health/ready', { headers: { Accept: 'application/json' } })
      .then((response) => response.json())
      .then((payload) => {
        if (!active) return
        setRunning({
          environment: payload?.checks?.environment || '',
          runtimeProfile: payload?.checks?.data_runtime_profile || '',
        })
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])
  return running
}
