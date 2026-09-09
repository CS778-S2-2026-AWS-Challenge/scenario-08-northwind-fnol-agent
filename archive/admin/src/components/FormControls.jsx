import { AlertCircle, CheckCircle2, LoaderCircle } from 'lucide-react'

export function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  )
}

export function JsonField({ label, value, onChange, rows = 8, hint }) {
  return (
    <Field label={label} hint={hint}>
      <textarea rows={rows} value={value} onChange={(event) => onChange(event.target.value)} spellCheck="false" />
    </Field>
  )
}

export function Feedback({ state }) {
  if (!state) return null
  if (state.kind === 'working') {
    return <p className="feedback" role="status"><LoaderCircle aria-hidden="true" />{state.message}</p>
  }
  if (state.kind === 'success') {
    return <p className="feedback success" role="status"><CheckCircle2 aria-hidden="true" />{state.message}</p>
  }
  return (
    <div className="feedback error" role="alert">
      <AlertCircle aria-hidden="true" />
      <div>
        <strong>Action not completed.</strong>
        <span>{state.error.message}</span>
        <span>Review the current server state and form values, then retry.</span>
        {state.error.requestId && <small>Request {state.error.requestId}</small>}
      </div>
    </div>
  )
}
