import { useState } from 'react'
import './App.css'

function Icon({ name, size = 18 }) {
  const paths = {
    headphones: (
      <>
        <path d="M4 14v-2a8 8 0 0 1 16 0v2" />
        <path d="M18 19c0 1.1-.9 2-2 2h-1" />
        <path d="M4 14h2a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1H4z" />
        <path d="M20 14h-2a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h2z" />
      </>
    ),
    image: (
      <>
        <rect width="16" height="16" x="3" y="3" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="m4 15 4-4 3 3 2-2 6 6" />
        <path d="M19 8v6M16 11h6" />
      </>
    ),
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    save: (
      <>
        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" />
        <path d="M17 21v-8H7v8M7 3v5h8" />
      </>
    ),
    file: (
      <>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
        <path d="M14 2v6h6M9 15l2 2 4-4" />
      </>
    ),
    users: (
      <>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
      </>
    ),
  }

  return (
    <svg
      aria-hidden="true"
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  )
}

function Benefit({ icon, title, children }) {
  return (
    <div className="benefit">
      <span className="benefit-icon">
        <Icon name={icon} size={16} />
      </span>
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </div>
  )
}

function App() {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [isSending, setIsSending] = useState(false)

  async function sendMessage(event) {
    event?.preventDefault()

    const trimmedMessage = message.trim()
    if (!trimmedMessage || isSending) return

    setIsSending(true)
    setReply('Sending...')

    try {
      const response = await fetch(
        'http://127.0.0.1:8000/api/claims/message',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: trimmedMessage,
          }),
        }
      )

      if (!response.ok) {
        throw new Error('Backend request failed')
      }

      const data = await response.json()
      setReply(data.reply)
    } catch (error) {
      setReply('Connection failed: ' + error.message)
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="customer-app">
      <header className="product-header">
        <a className="brand" href="/" aria-label="Northwind 主页">
          <span className="brand-mark">N</span>
          <span>Northwind</span>
        </a>

        <button className="human-help" type="button">
          <Icon name="headphones" />
          <span>人工帮助</span>
        </button>
      </header>

      <main className="entry-page">
        <section className="entry-main">
          <div className="entry-content">
            <p className="eyebrow">开始一次新的报案</p>
            <h1>先用自己的话告诉我们发生了什么</h1>
            <p className="entry-intro">
              不需要了解保险术语。我们会整理你提供的信息，只询问下一步真正需要的内容。
            </p>

            <form className="report-box" onSubmit={sendMessage}>
              <label htmlFor="incident-input">事故经过</label>
              <textarea
                id="incident-input"
                className="report-text"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="例如：今天早上，我的车在停车场被另一辆车撞到了后保险杠……"
                rows="5"
              />

              {reply && (
                <div className={`backend-status ${reply.startsWith('Connection failed') ? 'is-error' : ''}`} role="status">
                  <span className="status-dot" />
                  <span>{reply}</span>
                </div>
              )}

              <div className="report-actions">
                <button className="attach-action" type="button">
                  <Icon name="image" />
                  添加现场照片
                </button>
                <button
                  className="primary-button"
                  type="submit"
                  disabled={!message.trim() || isSending}
                >
                  {isSending ? '正在连接…' : '继续报案'}
                  {!isSending && <Icon name="arrow" />}
                </button>
              </div>
            </form>
          </div>
        </section>

        <aside className="entry-side">
          <div className="side-content">
            <h2>你可以随时停下来</h2>

            <Benefit icon="save" title="自动保存">
              已确认的信息会保留，不必重新开始。
            </Benefit>
            <Benefit icon="file" title="先推进可处理的部分">
              暂时缺少的材料可以在之后补充。
            </Benefit>
            <Benefit icon="users" title="人工接手时保留上下文">
              已经确认的内容会一起转交。
            </Benefit>

            <div className="resume-claim">
              <p>已有未完成报案？</p>
              <button className="secondary-button" type="button">
                <span>继续 NW-2026-08142</span>
                <Icon name="arrow" />
              </button>
            </div>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App
