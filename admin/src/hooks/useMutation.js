import { useCallback, useState } from 'react'

export default function useMutation(onSuccess) {
  const [feedback, setFeedback] = useState(null)
  const run = useCallback(async (operation, successMessage) => {
    setFeedback({ kind: 'working', message: 'Applying the action to the current server state...' })
    try {
      const result = await operation()
      setFeedback({ kind: 'success', message: successMessage })
      onSuccess?.(result)
      return result
    } catch (error) {
      setFeedback({ kind: 'error', error })
      return null
    }
  }, [onSuccess])
  return { feedback, setFeedback, run }
}
