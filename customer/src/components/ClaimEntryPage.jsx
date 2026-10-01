import MessageComposer from './MessageComposer.jsx'

// Start page: one composer in the centre of the screen. Sending the first
// message opens the conversation workspace straight away.
export default function ClaimEntryPage({
  composer,
  failure = null,
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
          <section id="claims" className="claim-starter" aria-label="Start a claim">
            <MessageComposer
              {...composer}
              inputLabel="Incident description"
              placeholder="Tell us what happened…"
              showModelControl
            />
            {failure}
          </section>
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
