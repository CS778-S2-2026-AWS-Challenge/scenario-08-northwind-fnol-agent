import {
  Bell,
  ChevronRight,
  ChevronsUpDown,
  CircleHelp,
  LogOut,
  Palette,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { initials } from '../format.js'
import { translate as t, useLanguage } from '../i18n.js'
import ConfirmDialog from './ConfirmDialog.jsx'

const ACCOUNT_MENU_ITEMS = [
  { key: 'profile', label: 'Profile', icon: UserRound, path: '/workbench/settings/profile' },
  { key: 'security', label: 'Account & Security', icon: ShieldCheck, path: '/workbench/settings/security' },
  { key: 'notifications', label: 'Notifications', icon: Bell, path: '/workbench/settings/notifications' },
  { key: 'appearance', label: 'Language & Display', icon: Palette, path: '/workbench/settings/appearance' },
  { key: 'help', label: 'Help & Feedback', icon: CircleHelp, path: '/workbench/settings/help' },
]

function accountRole(profile) {
  return profile?.roles?.[0]?.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) || t('Staff')
}

export default function AccountMenu({ profile, onLogout }) {
  useLanguage()
  const location = useLocation()
  const rootRef = useRef(null)
  const triggerRef = useRef(null)
  const itemRefs = useRef([])
  const openingFocusRef = useRef('first')
  const [open, setOpen] = useState(false)
  const [logoutOpen, setLogoutOpen] = useState(false)
  const [logoutBusy, setLogoutBusy] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  const currentIndex = useMemo(
    () => ACCOUNT_MENU_ITEMS.findIndex(({ path }) => location.pathname === path),
    [location.pathname],
  )

  useEffect(() => {
    if (!open) return undefined
    const items = itemRefs.current.filter(Boolean)
    const target = openingFocusRef.current === 'last' ? items.at(-1) : items[0]
    target?.focus()
    function onPointerDown(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  function openMenu(focus = 'first') {
    openingFocusRef.current = focus
    setOpen(true)
  }

  function closeMenu({ returnFocus = false } = {}) {
    setOpen(false)
    if (returnFocus) triggerRef.current?.focus()
  }

  function onTriggerKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      openMenu('first')
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      openMenu('last')
    }
  }

  function onMenuKeyDown(event) {
    const items = itemRefs.current.filter(Boolean)
    const index = items.indexOf(document.activeElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      closeMenu({ returnFocus: true })
    } else if (event.key === 'Tab') {
      closeMenu()
    } else if (event.key === 'Home') {
      event.preventDefault()
      items[0]?.focus()
    } else if (event.key === 'End') {
      event.preventDefault()
      items.at(-1)?.focus()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const offset = event.key === 'ArrowDown' ? 1 : -1
      const next = index < 0 ? 0 : (index + offset + items.length) % items.length
      items[next]?.focus()
    }
  }

  async function confirmLogout() {
    if (logoutBusy) return
    setLogoutBusy(true)
    setLogoutError('')
    try {
      await onLogout()
      setLogoutOpen(false)
    } catch {
      setLogoutError(t('Sign out could not finish because the session service did not respond. Your local session was cleared; return to sign in to continue.'))
    } finally {
      setLogoutBusy(false)
    }
  }

  const displayName = profile?.display_name || t('Claims Professional')
  const role = accountRole(profile)

  return (
    <div className="navigation-profile" ref={rootRef}>
      {open && (
        <div className="account-menu" onKeyDown={onMenuKeyDown}>
          <div className="account-menu__header">
            <Avatar profile={profile} />
            <span><strong>{displayName}</strong><small>{role}</small></span>
          </div>
          <div className="account-menu__items" role="menu" aria-labelledby="account-menu-trigger">
            {ACCOUNT_MENU_ITEMS.map(({ key, label, icon: Icon, path }, index) => {
              const selected = index === currentIndex
              return (
                <Link
                  key={key}
                  ref={(node) => { itemRefs.current[index] = node }}
                  role="menuitem"
                  tabIndex={-1}
                  className={`account-menu__item${selected ? ' is-selected' : ''}`}
                  aria-current={selected ? 'page' : undefined}
                  to={path}
                  onClick={() => closeMenu()}
                >
                  <Icon size={18} aria-hidden="true" />
                  <span>{t(label)}</span>
                  <ChevronRight size={16} aria-hidden="true" />
                </Link>
              )
            })}
            <div className="account-menu__separator" role="separator" />
            <button
              ref={(node) => { itemRefs.current[ACCOUNT_MENU_ITEMS.length] = node }}
              className="account-menu__item account-menu__item--danger"
              role="menuitem"
              tabIndex={-1}
              type="button"
              onClick={() => {
                setOpen(false)
                setLogoutError('')
                setLogoutOpen(true)
              }}
            >
              <LogOut size={18} aria-hidden="true" />
              <span>{t('Sign out')}</span>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
      <button
        id="account-menu-trigger"
        ref={triggerRef}
        className="account-menu-trigger"
        type="button"
        aria-label={t('Account menu for {name}', { name: displayName })}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => open ? closeMenu() : openMenu('first')}
        onKeyDown={onTriggerKeyDown}
      >
        <Avatar profile={profile} />
        <span className="account-menu-trigger__identity">
          <strong>{displayName}</strong>
          <small>{role}</small>
        </span>
        <ChevronsUpDown className="account-menu-trigger__chevron" size={17} aria-hidden="true" />
      </button>
      <ConfirmDialog
        open={logoutOpen}
        title={t('Sign out of your account?')}
        description={t('After signing out, you will need to enter your account details again to continue working.')}
        cancelLabel={t('Cancel')}
        confirmLabel={t('Sign out')}
        busyLabel={t('Signing out...')}
        busy={logoutBusy}
        danger
        error={logoutError}
        returnFocusRef={triggerRef}
        onCancel={() => setLogoutOpen(false)}
        onConfirm={confirmLogout}
      />
    </div>
  )
}

function Avatar({ profile }) {
  return profile?.avatar_url ? (
    <span className="profile-avatar profile-avatar--image">
      <img src={profile.avatar_url} alt="" />
    </span>
  ) : (
    <span className="profile-avatar" aria-hidden="true">{initials(profile?.display_name)}</span>
  )
}
