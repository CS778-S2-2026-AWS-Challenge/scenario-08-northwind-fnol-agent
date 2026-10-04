import { AgentTurnDisclosure } from './AgentTurnActivity.jsx'
import AttachmentPreview from './AttachmentPreview.jsx'
import ClaimantAvatar from './ClaimantAvatar.jsx'
import { developerModeEnabled } from '../runtimeConfig.js'
import { documentTaskTitle } from '../claimDocumentProjection.js'
import { evidenceFileStatusLabel, messageText } from '../messagePresentation.js'

// Conversation building blocks: the opening prompts, one row per message, and
// the files attached to a claimant message. Rows take slots (children) for the
// parts that depend on workspace state, such as recovery and service actions.

const CLAIM_START_PROMPTS = [
  { icon: 'car', text: 'I was in a car accident' },
  { icon: 'home', text: 'My home or belongings were damaged' },
  { icon: 'search', text: 'Something was lost or stolen' },
]

function ClaimStartIcon({ name, className = '' }) {
  const paths = {
    car: (
      <>
        <path d="m5 17-1 2M19 17l1 2M3 13l2-6h14l2 6v5H3v-5Z" />
        <path d="M5 13h14M7 16h.01M17 16h.01" />
      </>
    ),
    home: (
      <>
        <path d="m3 11 9-8 9 8" />
        <path d="M5 10v10h14V10M9 20v-6h6v6" />
      </>
    ),
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 5 5M8 8h4v4H8z" />
      </>
    ),
  }

  return (
    <svg
      className={`claim-start-icon ${className}`.trim()}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}

// A new conversation opens with one line and three small starting chips.
export function ConversationStart({ onChoosePrompt }) {
  return (
    <section className="conversation-start" aria-labelledby="conversation-title">
      <h1 id="conversation-title">Tell us what happened, in your own words.</h1>
      <div className="conversation-start-options">
        <div className="conversation-start-prompt-list" role="group" aria-label="Choose a starting point">
          {CLAIM_START_PROMPTS.map((prompt) => (
            <button
              className="conversation-start-prompt"
              type="button"
              key={prompt.text}
              onClick={() => onChoosePrompt(prompt.text)}
            >
              <span className="conversation-start-prompt-icon" aria-hidden="true">
                <ClaimStartIcon name={prompt.icon} />
              </span>
              <span>{prompt.text}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

export function MessageTimestamp({ createdAt }) {
  const timestamp = new Date(createdAt)
  if (Number.isNaN(timestamp.getTime())) return null
  return (
    <time className="message-timestamp" dateTime={createdAt}>
      {timestamp.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
    </time>
  )
}

function localAttachmentFile(attachment) {
  return attachment?.previewFile || attachment?.stagedFile || attachment?.retryFile || null
}

const UNSPECIFIED_KINDS = new Set(['other_document', 'other'])

// A file sent in the chat has no kind until the assistant reads it; say what it
// was read as, or that it is still being looked at.
function attachmentStatus(evidence, readings) {
  const status = evidenceFileStatusLabel(evidence.file_status, evidence.status)
  if (!UNSPECIFIED_KINDS.has(evidence.kind) || evidence.status !== 'received') return status
  const read = readings?.get(evidence.evidence_id)
  return read ? `Read as: ${documentTaskTitle({ kind: read })}` : 'Received · being checked'
}

export function ClaimantMessageAttachments({ message, evidenceItems, attachments, previewFiles, readings }) {
  const presentedAttachments = Array.isArray(attachments)
    ? attachments.map((attachment) => ({
      ...attachment,
      previewFile: localAttachmentFile(attachment)
        || previewFiles?.get(attachment.evidenceId || attachment.uploadAttempt?.evidenceId),
    }))
    : (message?.evidence_refs || []).map((evidenceId, index) => {
      const evidence = evidenceItems.find((item) => item.evidence_id === evidenceId)
      return {
        id: evidenceId,
        name: evidence?.original_filename || evidence?.kind || `Attached file ${index + 1}`,
        previewFile: previewFiles?.get(evidenceId),
        statusLabel: evidence ? attachmentStatus(evidence, readings) : 'Attached',
      }
    })

  if (presentedAttachments.length === 0) return null

  return (
    <ul className="message-attachments" aria-label="Attached files">
      {presentedAttachments.map((attachment, index) => (
        <li className="message-attachment" key={attachment.id || attachment.name || index}>
          <AttachmentPreview
            attachment={attachment}
            fallbackClassName="message-attachment-icon"
            className="message-attachment-preview"
          />
          <span className="message-attachment-copy">
            <strong>{attachment.name || `Attached file ${index + 1}`}</strong>
            <small>{attachment.statusLabel || 'Attached'}</small>
          </span>
        </li>
      ))}
    </ul>
  )
}

export function ClaimantMessageRow({ message, displayName, evidenceItems, previewFiles, readings, children }) {
  const text = messageText(message)
  return (
    <article className="msg-user">
      <div className="chat-message-row">
        <div className="user-message-body">
          <div className="chat-bubble user-bubble">
            {text && <p className="user-bubble-text">{text}</p>}
            <ClaimantMessageAttachments
              message={message}
              evidenceItems={evidenceItems}
              previewFiles={previewFiles}
              readings={readings}
            />
          </div>
          {children}
        </div>
        <ClaimantAvatar className="message-avatar claimant-message-avatar" displayName={displayName} />
      </div>
    </article>
  )
}

// A person from Northwind writes in the same layout as the assistant; only the
// name and the mark differ.
export function StaffMessageRow({ message }) {
  return (
    <article className="msg-staff">
      <MessageTimestamp createdAt={message.created_at} />
      <div className="chat-message-row">
        <div className="message-avatar staff-mark" aria-hidden="true">N</div>
        <div className="staff-message-body">
          <div className="staff-label">Northwind staff</div>
          <div className="agent-text staff-text"><p>{messageText(message)}</p></div>
        </div>
      </div>
    </article>
  )
}

function speak(text) {
  if (!globalThis.speechSynthesis) return
  globalThis.speechSynthesis.cancel()
  globalThis.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
}

export function AgentMessageRow({ message, activity, children }) {
  const text = messageText(message)
  return (
    <article className="msg-agent">
      <MessageTimestamp createdAt={message.created_at} />
      <div className="chat-message-row">
        <div className="message-avatar agent-avatar" aria-hidden="true">N</div>
        <div className="agent-body">
          <div className="agent-label">Claims assistant</div>
          {developerModeEnabled() && <AgentTurnDisclosure progress={activity} />}
          <div className="agent-text">
            <p>{text}</p>
          </div>
          <div className="agent-message-menu">
            <button className="listen-message" type="button" onClick={() => speak(text)}>Listen</button>
          </div>
          {children}
        </div>
      </div>
    </article>
  )
}
