import { useState } from 'react'
import './App.css'

function App() {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [status, setStatus] = useState('idle')

  const isSending = status === 'sending'

  async function sendMessage(event) {
    event.preventDefault()

    const trimmedMessage = message.trim()
    if (!trimmedMessage || isSending) return

    setStatus('sending')
    setReply('Sending your description...')

    try {
      const response = await fetch('/api/claims/message', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: trimmedMessage,
        }),
      })

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`)
      }

      const data = await response.json()
      setReply(data.reply || 'Your description was received.')
      setStatus('success')
    } catch (error) {
      setReply(`We could not reach the claim service. ${error.message}`)
      setStatus('error')
    }
  }

  return (
    <div className="customer-app">
      <header className="product-header">
        <a className="brand" href="/" aria-label="Northwind home">
          <span className="brand-mark">N</span>
          <span>Northwind</span>
        </a>
      </header>

      <main className="entry-page">
        <section className="entry-main">
          <div className="entry-content">
            <p className="eyebrow">Start a new claim</p>
            <h1>Tell us what happened in your own words</h1>
            <p className="entry-intro">
              You do not need to use insurance terms. Start with the details you
              know now.
            </p>

            <form className="report-box" onSubmit={sendMessage}>
              <label htmlFor="incident-input">Incident description</label>
              <textarea
                id="incident-input"
                className="report-text"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="For example: This morning, another vehicle hit the rear bumper of my car in a car park..."
                rows="5"
              />

              {status !== 'idle' && (
                <div
                  className={`backend-status ${status === 'error' ? 'is-error' : ''}`}
                  role="status"
                  aria-live="polite"
                >
                  <span className="status-dot" />
                  <span>{reply}</span>
                </div>
              )}

              <div className="report-actions">
                <button
                  className="primary-button"
                  type="submit"
                  disabled={!message.trim() || isSending}
                >
                  {isSending ? 'Sending...' : 'Continue claim'}
                </button>
              </div>
            </form>
          </div>
        </section>

        <aside className="entry-side" aria-labelledby="helpful-details-title">
          <div className="side-content">
            <p className="side-label">When available</p>
            <h2 id="helpful-details-title">Helpful details to include</h2>
            <ul className="detail-list">
              <li>When and where the incident happened</li>
              <li>Who or what was involved</li>
              <li>Any damage, injuries, or immediate safety concerns</li>
            </ul>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App
