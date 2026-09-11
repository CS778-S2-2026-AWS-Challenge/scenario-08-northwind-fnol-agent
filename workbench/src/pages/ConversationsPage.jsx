import { Bot, MessageSquareText } from 'lucide-react'
import { failureReason, failureReference } from '../failure.js'

export default function ConversationsPage({ conversations, loading, error, onRetry, onOpenConversation }) {
  const claimConversations = conversations.filter((item) => item.kind === 'claim')
  const agentConversations = conversations.filter((item) => item.kind === 'staff_agent')
  return (
    <main className="conversations-page">
      <header className="content-header"><div><p className="eyebrow">Sessions</p><h1>Claim conversations</h1><p>Claim-bound conversations remain attached to their Claim workspace. Staff Agent sessions are kept separate.</p></div></header>
      <div className="conversation-groups">
        <section><div className="section-heading"><div><p className="eyebrow">Claimant and staff</p><h2>Claim conversations</h2></div><span className="count-badge">{claimConversations.length}</span></div>{loading && <p className="empty-note" aria-live="polite">Loading conversations...</p>}{error && <div className="form-error" role="alert"><strong>Conversations are unavailable.</strong> {failureReason(error)} <button className="button button--quiet" type="button" onClick={onRetry}>Retry</button>{failureReference(error) && <small>{failureReference(error)}</small>}</div>}<div className="conversation-cards">{claimConversations.map((conversation) => <button type="button" key={conversation.conversation_id} onClick={() => onOpenConversation(conversation)}><MessageSquareText size={18} /><span><strong>{conversation.title}</strong><small>{conversation.summary || 'No summary is available.'}</small></span><small>{conversation.status}</small></button>)}{!loading && !error && !claimConversations.length && <p className="empty-note">No Claim conversation is assigned to you.</p>}</div></section>
        <section><div className="section-heading"><div><p className="eyebrow">Internal assistance</p><h2>Staff Agent sessions</h2></div><span className="count-badge">{agentConversations.length}</span></div><div className="conversation-cards">{agentConversations.map((conversation) => <button type="button" key={conversation.conversation_id} onClick={() => onOpenConversation(conversation)}><Bot size={18} /><span><strong>{conversation.title}</strong><small>{conversation.summary || 'No summary is available.'}</small></span></button>)}{!loading && !error && !agentConversations.length && <p className="empty-note">No Staff Agent session has been created.</p>}</div></section>
      </div>
    </main>
  )
}
