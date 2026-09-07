import { useState } from 'react'
import { Search } from 'lucide-react'
import { adminFetch, getToken, withQuery } from '../api.js'
import DetailPanel from '../components/DetailPanel.jsx'
import { Feedback, Field } from '../components/FormControls.jsx'
import PageHeader from '../components/PageHeader.jsx'

export default function RuntimeSnapshotPage() {
  const [environment, setEnvironment] = useState('test')
  const [runtimeProfile, setRuntimeProfile] = useState('fixture')
  const [snapshot, setSnapshot] = useState(null)
  const [feedback, setFeedback] = useState(null)

  async function load(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Resolving the active published Runtime Snapshot...' })
    try {
      const result = await adminFetch(withQuery('/internal/v1/admin/runtime-snapshots', { environment, runtime_profile: runtimeProfile }), { token: getToken() })
      setSnapshot(result)
      setFeedback({ kind: 'success', message: 'The active Runtime Snapshot was loaded from the server.' })
    } catch (error) {
      setSnapshot(null)
      setFeedback({ kind: 'error', error })
    }
  }
  return (
    <>
      <PageHeader title="Runtime Snapshot" summary="Inspect the exact published configuration loaded for one environment and runtime profile" />
      <form className="query-bar" onSubmit={load}>
        <Field label="Environment"><input value={environment} onChange={(event) => setEnvironment(event.target.value)} required /></Field>
        <Field label="Runtime profile"><input value={runtimeProfile} onChange={(event) => setRuntimeProfile(event.target.value)} required /></Field>
        <button className="primary"><Search aria-hidden="true" />Resolve snapshot</button>
      </form>
      <Feedback state={feedback} />
      <DetailPanel title="Runtime Snapshot" item={snapshot} />
    </>
  )
}
