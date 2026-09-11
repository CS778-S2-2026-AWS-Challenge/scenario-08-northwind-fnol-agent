import { ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { canSubmitProjectedAction } from '../projected-action.js'
import { ActionDetails } from './ProjectedAction.jsx'
import { ProjectedOwnershipAction } from './OwnershipActions.jsx'
import ReopenClaimDialog from './ReopenClaimDialog.jsx'

export default function PrimaryAction({ action, handoff, request, onAccept, onOwnershipAction, onReopen, onSection }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const executable = canSubmitProjectedAction(action)
  const section = actionSection(action?.action_code)

  async function accept() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await onAccept(handoff)
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="primary-action" aria-labelledby="primary-action-title">
      <div className="primary-action__icon"><ShieldCheck size={22} /></div>
      <div className="primary-action__copy">
        <p className="eyebrow">Staff next action</p>
        <h2 id="primary-action-title">{action?.label || 'No staff action is currently authorised'}</h2>
        <p>{action?.purpose || 'Continue reviewing the projected context. No controlled staff action is available for this Claim.'}</p>
        {action?.availability === 'blocked' && <p className="record-note record-note--blocked"><strong>Blocked</strong>{action.blocked_reason || 'This action is not available for the current Claim state.'}</p>}
        {action && <ActionDetails action={action} />}
      </div>
      {action?.action_code === 'human.accept_handoff' && executable && handoff && (
        confirming
          ? <div className="primary-action__confirm"><p>{action.confirmation?.message}</p><button className="button button--primary" type="button" disabled={busy} onClick={accept}>{busy ? 'Accepting...' : `Confirm ${action.label}`}</button>{error && <p className="form-error" role="alert">{error}</p>}</div>
          : <button className="button button--primary" type="button" onClick={() => setConfirming(true)}>Review acceptance</button>
      )}
      {action?.action_code?.startsWith('ownership.') && executable && (
        <div className="primary-action__form"><ProjectedOwnershipAction action={action} request={request} onAction={onOwnershipAction} compact /></div>
      )}
      {action?.action_code === 'claim.reopen' && action.availability === 'confirmation_required' && (
        <ReopenClaimDialog key={action.target_ref} action={action} onReopen={onReopen} />
      )}
      {action && executable && section && action.action_code !== 'human.accept_handoff' && (
        <button className="button button--primary" type="button" onClick={() => onSection(section)}>Open {sectionLabel(section)}</button>
      )}
    </section>
  )
}

function actionSection(code) {
  if (code === 'human.resolve_handoff' || code === 'work_item.update') return 'activity'
  if (code === 'signal.record_decision') return 'signals'
  if (code === 'conversation.send_claimant_message') return 'conversation'
  return null
}

function sectionLabel(section) {
  return section === 'activity' ? 'work activity' : section
}
