import { ArrowRightLeft, RotateCcw, UserRoundPlus, UsersRound } from 'lucide-react'
import { useState } from 'react'

const REQUEST_ACTIONS = {
  'ownership.request_cowork': {
    icon: UsersRound,
    submitLabel: 'Send request',
    reasonLabel: 'Why do you need access?',
  },
  'ownership.invite_cowork': {
    icon: UserRoundPlus,
    submitLabel: 'Send invitation',
    reasonLabel: 'Why is this collaboration needed?',
    staffLabel: 'Staff ID to invite',
  },
  'ownership.request_transfer': {
    icon: ArrowRightLeft,
    submitLabel: 'Request transfer',
    reasonLabel: 'Why should ownership transfer?',
    staffLabel: 'Target staff ID',
  },
  'ownership.requeue': {
    icon: RotateCcw,
    submitLabel: 'Return to queue',
    reasonLabel: 'Why are you releasing this Claim?',
  },
}

export default function OwnershipActions({
  actions = [],
  requests = [],
  onCoworkRequest,
  onTransferRequest,
  onRequeue,
  onDecision,
}) {
  const ownershipActions = actions.filter((action) => (
    action.action_code.startsWith('ownership.') && action.availability !== 'blocked'
  ))
  if (!ownershipActions.length) return null

  return (
    <section className="ownership-actions" aria-labelledby="ownership-actions-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Access and ownership</p>
          <h2 id="ownership-actions-title">Work with this Claim</h2>
        </div>
      </div>
      <div className="ownership-action-list">
        {ownershipActions.map((action) => (
          action.action_code.startsWith('ownership.decide_')
            ? <DecisionAction key={action.action_code + action.target_ref} action={action} request={requests.find((item) => item.request_id === action.target_ref)} onDecision={onDecision} />
            : <RequestAction key={action.action_code} action={action} onCoworkRequest={onCoworkRequest} onTransferRequest={onTransferRequest} onRequeue={onRequeue} />
        ))}
      </div>
    </section>
  )
}

function RequestAction({ action, onCoworkRequest, onTransferRequest, onRequeue }) {
  const config = REQUEST_ACTIONS[action.action_code]
  const [expanded, setExpanded] = useState(false)
  const [reason, setReason] = useState('')
  const [staffId, setStaffId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!config) return null
  const Icon = config.icon

  async function submit(event) {
    event.preventDefault()
    if (!reason.trim() || (config.staffLabel && !staffId.trim())) return
    setBusy(true)
    setError('')
    try {
      if (action.action_code === 'ownership.request_cowork') {
        await onCoworkRequest({ reason: reason.trim() })
      } else if (action.action_code === 'ownership.invite_cowork') {
        await onCoworkRequest({ staff_id: staffId.trim(), reason: reason.trim() })
      } else if (action.action_code === 'ownership.request_transfer') {
        await onTransferRequest({ target_staff_id: staffId.trim(), reason: reason.trim() })
      } else {
        await onRequeue(reason.trim())
      }
      setExpanded(false)
      setReason('')
      setStaffId('')
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="ownership-action">
      <button
        type="button"
        className="ownership-action__toggle"
        aria-expanded={expanded}
        aria-controls={`ownership-form-${action.action_code}`}
        onClick={() => setExpanded((value) => !value)}
      >
        <Icon size={18} />
        <span><strong>{action.label}</strong><small>{action.purpose}</small></span>
      </button>
      {expanded && (
        <form id={`ownership-form-${action.action_code}`} className="ownership-action__form" onSubmit={submit}>
          {config.staffLabel && <label>{config.staffLabel}<input value={staffId} onChange={(event) => setStaffId(event.target.value)} autoComplete="off" /></label>}
          <label>{config.reasonLabel}<textarea rows="2" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
          {action.confirmation?.message && <p>{action.confirmation.message}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="ownership-action__controls">
            <button type="button" className="button button--quiet" onClick={() => setExpanded(false)}>Cancel</button>
            <button type="submit" className="button button--primary" disabled={busy || !reason.trim() || Boolean(config.staffLabel && !staffId.trim())}>{busy ? 'Working...' : config.submitLabel}</button>
          </div>
        </form>
      )}
    </article>
  )
}

function DecisionAction({ action, request, onDecision }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function decide(decision) {
    setBusy(true)
    setError('')
    try {
      await onDecision(action.target_ref, decision)
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="ownership-decision">
      <div>
        <strong>{action.label}</strong>
        <p>{action.purpose}</p>
        {request?.reason && <small>Reason: {request.reason}</small>}
      </div>
      <div className="ownership-action__controls">
        <button type="button" className="button button--quiet" disabled={busy} onClick={() => decide('rejected')}>Decline</button>
        <button type="button" className="button button--primary" disabled={busy} onClick={() => decide('accepted')}>Accept</button>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </article>
  )
}
