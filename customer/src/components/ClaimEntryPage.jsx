import MessageComposer from './MessageComposer.jsx'

// Start page: one composer in the centre of the screen. Sending the first
// message opens the conversation workspace straight away.
export default function ClaimEntryPage({
  composer,
  failure = null,
  continueCard = null,
  onContinue,
  onOpenHowItWorks,
}) {
  return (
    <main className="entry-page">
      <section className="entry-hero" aria-labelledby="entry-title">
        <div className="entry-content">
          <p className="entry-brand-line">
            <span>Understand insurance.</span>
            {' '}
            <span>Understand you better.</span>
          </p>
          <h1 className="entry-task-title" id="entry-title">Start your insurance claim</h1>
          <p className="entry-intro">Tell us what happened — we&apos;ll guide you through the next steps.</p>
          <div className="entry-claim-stack">
            <section id="claims" className="claim-starter" aria-label="Start a claim">
              <MessageComposer
                {...composer}
                inputLabel="Incident description"
                placeholder="Tell us what happened…"
                showModelControl
              />
              {failure}
            </section>
            {continueCard && (
              <button
                className="entry-continue-card"
                type="button"
                aria-label={`${continueCard.title}, ${continueCard.statusLabel}. Continue your claim. Next: ${continueCard.detail} ${continueCard.savedLabel}`}
                onClick={() => onContinue(continueCard.claimId)}
              >
                <span className="entry-continue-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" focusable="false">
                    <path d="M6 3h7l5 5v4" />
                    <path d="M13 3v5h5" />
                    <path d="M10 21H6V3" />
                    <circle cx="16" cy="17" r="4" />
                    <path d="M16 15v2l1.5 1" />
                  </svg>
                </span>
                <span className="entry-continue-copy">
                  <span className="entry-continue-kicker">
                    {continueCard.title} · {continueCard.statusLabel}
                  </span>
                  <strong>Continue your claim</strong>
                  <span className="entry-continue-detail">Next: {continueCard.detail}</span>
                </span>
                <span className="entry-continue-meta">{continueCard.savedLabel}</span>
                <span className="entry-continue-arrow" aria-hidden="true">
                  <svg viewBox="0 0 24 24" focusable="false">
                    <path d="M5 12h14" />
                    <path d="m13 6 6 6-6 6" />
                  </svg>
                </span>
              </button>
            )}
          </div>
          <div className="entry-tertiary-links">
            <button className="text-link entry-process-link" type="button" onClick={onOpenHowItWorks}>
              How does the claim process work?
            </button>
          </div>
        </div>
      </section>
    </main>
  )
}
