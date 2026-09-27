import { KeyRound, Laptop, MapPin, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime } from '../../format.js'
import { translate as t } from '../../i18n.js'
import ConfirmDialog from '../ConfirmDialog.jsx'

export default function SecuritySettings({ values, onAction }) {
  const [pendingAction, setPendingAction] = useState(null)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)

  async function runAction(action, payload = {}) {
    if (busy) return
    setBusy(true)
    setFeedback(null)
    try {
      await onAction(action, payload)
      setFeedback({ kind: 'success', message: t('The security change was completed.') })
      setPendingAction(null)
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
      if (!pendingAction) setPendingAction(null)
    } finally {
      setBusy(false)
    }
  }

  const twoFactorLabel = values.twoFactorEnabled === null
    ? t('Status unavailable')
    : values.twoFactorEnabled
      ? t('Enabled')
      : t('Not enabled')
  const changePassword = values.actions?.changePassword
  const changeTwoFactor = values.actions?.changeTwoFactor
  const manageDevices = values.actions?.manageDevices

  return (
    <div className="settings-form">
      {values.managedByOrganization && (
        <div className="settings-managed-notice" role="status">
          <ShieldCheck size={19} aria-hidden="true" />
          <div><strong>{t('Account managed by your organisation')}</strong><p>{t('Password changes are handled by your enterprise sign-in provider.')}</p></div>
        </div>
      )}
      <section className="settings-card" aria-labelledby="security-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="security-heading">{t('Account security')}</h2>
            <p>{t('Review sign-in protection and devices connected to this staff account.')}</p>
          </div>
        </div>
        <div className="settings-security-list">
          {!values.managedByOrganization && (
            <SecurityRow
              icon={KeyRound}
              title={t('Login password')}
              description={values.passwordLastChangedAt
                ? t('Last changed {date}', { date: formatDateTime(values.passwordLastChangedAt) })
                : t('Last changed date is unavailable from the current identity service.')}
              action={t('Change password')}
              disabled={busy || changePassword?.available === false}
              unavailableReason={changePassword?.available === false ? changePassword.reason : null}
              onAction={() => runAction('change_password')}
            />
          )}
          <SecurityRow
            icon={ShieldCheck}
            title={t('Two-factor authentication')}
            description={twoFactorLabel}
            status={twoFactorLabel}
            action={values.twoFactorEnabled ? t('Turn off') : t('Set up')}
            disabled={busy || changeTwoFactor?.available === false}
            unavailableReason={changeTwoFactor?.available === false ? changeTwoFactor.reason : null}
            onAction={() => values.twoFactorEnabled
              ? setPendingAction({ kind: 'disable_mfa' })
              : runAction('enable_mfa')}
          />
        </div>
      </section>

      <section className="settings-card" aria-labelledby="devices-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="devices-heading">{t('Login devices')}</h2>
            <p>{t('Only the current browser can be identified until the identity service exposes account devices.')}</p>
            {manageDevices?.available === false && <p className="settings-unavailable-note">{t(manageDevices.reason)}</p>}
          </div>
          <button className="button button--secondary" type="button" disabled={busy || manageDevices?.available === false} onClick={() => runAction('manage_devices')}>{t('Manage devices')}</button>
        </div>
        <div className="settings-device-list">
          {values.devices.map((device) => (
            <article className="settings-device" key={device.id}>
              <span className="settings-row__icon"><Laptop size={18} aria-hidden="true" /></span>
              <div>
                <strong>{t(device.name)}</strong>
                <span><MapPin size={15} aria-hidden="true" />{t(device.location)}</span>
                <small>{t(device.lastActive)}{device.current ? ` · ${t('Current device')}` : ''}</small>
              </div>
              <button className="button button--quiet" type="button" disabled={busy || manageDevices?.available === false} onClick={() => setPendingAction({ kind: 'remove_device', device })}>{t('Remove')}</button>
            </article>
          ))}
        </div>
      </section>

      <div className="settings-form__actions" aria-live="polite">
        {feedback && <p className={`settings-feedback settings-feedback--${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>}
      </div>

      <ConfirmDialog
        open={pendingAction?.kind === 'disable_mfa'}
        title={t('Turn off two-factor authentication?')}
        description={t('Turning off two-factor authentication reduces protection for this staff account. Confirm only if your organisation has approved the change.')}
        confirmLabel={t('Turn off')}
        busyLabel={t('Turning off...')}
        busy={busy}
        danger
        error={feedback?.kind === 'error' ? feedback.message : null}
        onCancel={() => { setPendingAction(null); setFeedback(null) }}
        onConfirm={() => runAction('disable_mfa')}
      />
      <ConfirmDialog
        open={pendingAction?.kind === 'remove_device'}
        title={t('Remove this login device?')}
        description={t('This device will need to sign in again before it can access the Workbench.')}
        confirmLabel={t('Remove device')}
        busyLabel={t('Removing...')}
        busy={busy}
        danger
        error={feedback?.kind === 'error' ? feedback.message : null}
        onCancel={() => { setPendingAction(null); setFeedback(null) }}
        onConfirm={() => runAction('remove_device', { deviceId: pendingAction.device.id })}
      />
    </div>
  )
}

function SecurityRow({ icon: Icon, title, description, status, action, disabled, unavailableReason, onAction }) {
  return (
    <div className="settings-security-row">
      <span className="settings-row__icon"><Icon size={18} aria-hidden="true" /></span>
      <span className="settings-row__copy">
        <strong>{title}</strong>
        <small>{description}</small>
        {unavailableReason && <small className="settings-unavailable-note">{t(unavailableReason)}</small>}
      </span>
      {status && <span className="settings-status-chip">{status}</span>}
      <button className="button button--secondary" type="button" disabled={disabled} onClick={onAction}>{action}</button>
    </div>
  )
}
