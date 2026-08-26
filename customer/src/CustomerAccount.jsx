import { useEffect, useRef, useState } from 'react'

const PROFILE_KEY = 'northwind-customer-profile-prototype'

const DEFAULT_PROFILE = {
  firstName: 'Alex',
  lastName: 'Morgan',
  email: 'alex.morgan@example.com',
  phone: '+64 21 555 0182',
  contactPreference: 'email',
}

const INITIAL_MESSAGES = [
  {
    id: 'msg-1',
    subject: 'Your claim update',
    preview: 'We received the materials you added to your Motor claim.',
    date: 'Today, 9:42 AM',
    unread: true,
  },
  {
    id: 'msg-2',
    subject: 'A document is still needed',
    preview: 'You can add the police report when it becomes available.',
    date: '18 Aug',
    unread: true,
  },
  {
    id: 'msg-3',
    subject: 'Welcome to your Northwind account',
    preview: 'Manage your details, claims and communication preferences here.',
    date: '12 Aug',
    unread: false,
  },
]

function savedProfile() {
  try {
    return { ...DEFAULT_PROFILE, ...JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}') }
  } catch {
    return DEFAULT_PROFILE
  }
}

export default function CustomerAccount({ initialSection = 'overview', onSignOut, onStartClaim }) {
  const [section, setSection] = useState(initialSection)
  const [profile, setProfile] = useState(savedProfile)
  const [draft, setDraft] = useState(profile)
  const [avatarUrl, setAvatarUrl] = useState('')
  const [messages, setMessages] = useState(INITIAL_MESSAGES)
  const [saved, setSaved] = useState(false)
  const avatarInput = useRef(null)

  useEffect(() => () => {
    if (avatarUrl) URL.revokeObjectURL(avatarUrl)
  }, [avatarUrl])

  const initials = `${profile.firstName[0] || ''}${profile.lastName[0] || ''}`.toUpperCase()
  const unreadCount = messages.filter((message) => message.unread).length

  function updateDraft(event) {
    setDraft((current) => ({ ...current, [event.target.name]: event.target.value }))
    setSaved(false)
  }

  function saveProfile(event) {
    event.preventDefault()
    setProfile(draft)
    localStorage.setItem(PROFILE_KEY, JSON.stringify(draft))
    setSaved(true)
  }

  function chooseAvatar(event) {
    const file = event.target.files?.[0]
    if (!file) return
    if (avatarUrl) URL.revokeObjectURL(avatarUrl)
    setAvatarUrl(URL.createObjectURL(file))
  }

  function openMessage(messageId) {
    setMessages((current) => current.map((message) => (
      message.id === messageId ? { ...message, unread: false } : message
    )))
  }

  return (
    <main className="account-page">
      <aside className="account-sidebar" aria-label="Account navigation">
        <div className="account-person">
          <div className="account-avatar">
            {avatarUrl ? <img src={avatarUrl} alt="Customer profile" /> : <span>{initials}</span>}
          </div>
          <div><strong>{profile.firstName} {profile.lastName}</strong><small>Northwind customer</small></div>
        </div>
        <nav>
          <button className={section === 'overview' ? 'active' : ''} onClick={() => setSection('overview')} type="button">Overview</button>
          <button className={section === 'profile' ? 'active' : ''} onClick={() => setSection('profile')} type="button">Profile and preferences</button>
          <button className={section === 'messages' ? 'active' : ''} onClick={() => setSection('messages')} type="button">Messages {unreadCount > 0 && <span>{unreadCount}</span>}</button>
        </nav>
        <button className="account-signout" type="button" onClick={onSignOut}>Sign out</button>
      </aside>

      <div className="account-content">
        <div className="account-prototype-note" role="note">Prototype account · Information is stored only in this browser.</div>

        {section === 'overview' && <>
          <header className="account-heading">
            <div><p className="eyebrow">Your account</p><h1>Good morning, {profile.firstName}</h1><p>Manage your claims, messages and personal details in one place.</p></div>
            <button className="primary-button" type="button" onClick={onStartClaim}>Start a new claim</button>
          </header>
          <section className="account-summary-grid" aria-label="Account summary">
            <article><span>Active claims</span><strong>1</strong><small>One claim needs your attention</small></article>
            <article><span>Unread messages</span><strong>{unreadCount}</strong><small>Updates from Northwind</small></article>
            <article><span>Profile</span><strong>Complete</strong><small>Contact preferences saved</small></article>
          </section>
          <section className="account-card account-claim-card">
            <div className="account-card-heading"><div><p className="eyebrow">Active claim</p><h2>Motor claim</h2></div><span className="account-status">Awaiting document</span></div>
            <div className="account-claim-details"><div><small>Claim number</small><strong>NW-2026-1048</strong></div><div><small>Last updated</small><strong>Today, 9:42 AM</strong></div><div><small>Next step</small><strong>Add police report when available</strong></div></div>
            <button className="secondary-button" type="button">View claim details</button>
          </section>
        </>}

        {section === 'profile' && <section className="account-card profile-card">
          <div className="account-card-heading"><div><p className="eyebrow">Personal details</p><h1>Profile and preferences</h1></div></div>
          <div className="avatar-editor">
            <div className="account-avatar large">{avatarUrl ? <img src={avatarUrl} alt="Customer profile" /> : <span>{initials}</span>}</div>
            <div><strong>Profile photo</strong><p>JPG or PNG. This prototype keeps the image for the current session only.</p><button className="secondary-button" type="button" onClick={() => avatarInput.current?.click()}>Choose photo</button><input ref={avatarInput} type="file" accept="image/png,image/jpeg" onChange={chooseAvatar} hidden /></div>
          </div>
          <form className="account-profile-form" onSubmit={saveProfile}>
            <label>First name<input name="firstName" value={draft.firstName} onChange={updateDraft} required /></label>
            <label>Last name<input name="lastName" value={draft.lastName} onChange={updateDraft} required /></label>
            <label>Email address<input name="email" type="email" value={draft.email} onChange={updateDraft} required /></label>
            <label>Phone number<input name="phone" type="tel" value={draft.phone} onChange={updateDraft} /></label>
            <label className="wide">Preferred contact method<select name="contactPreference" value={draft.contactPreference} onChange={updateDraft}><option value="email">Email</option><option value="sms">Text message</option><option value="phone">Phone call</option><option value="in_app">Account message</option></select></label>
            <div className="account-form-actions"><button className="primary-button" type="submit">Save changes</button>{saved && <span role="status">Changes saved</span>}</div>
          </form>
        </section>}

        {section === 'messages' && <section className="account-card messages-card">
          <div className="account-card-heading"><div><p className="eyebrow">Communication</p><h1>Messages</h1><p>Updates about your claims and account.</p></div><span className="message-count">{unreadCount} unread</span></div>
          <div className="account-message-list">
            {messages.map((message) => <button key={message.id} className={message.unread ? 'unread' : ''} type="button" onClick={() => openMessage(message.id)}>
              <span className="message-dot" aria-hidden="true" /><span><strong>{message.subject}</strong><small>{message.preview}</small></span><time>{message.date}</time>
            </button>)}
          </div>
        </section>}
      </div>
    </main>
  )
}
