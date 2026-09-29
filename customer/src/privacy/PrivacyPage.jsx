import { useEffect, useMemo, useRef, useState } from 'react'
import {
  privacyContent,
  productPrivacySections,
  readPrivacyConfiguration,
  unresolvedPrivacyConfiguration,
} from './privacyContent.js'
import './PrivacyPage.css'

const MOBILE_PRIVACY_QUERY = '(max-width: 980px)'

function normaliseClaimFamily(claimType) {
  if (claimType === 'motor') return 'motor'
  if (claimType === 'home' || claimType === 'contents' || claimType === 'home_contents') {
    return 'homeContents'
  }
  return null
}

function initialExpandedSections(claimFamily) {
  const expanded = new Set(['information-we-collect', 'your-rights-and-choices'])
  if (claimFamily === 'motor') expanded.add(privacyContent.motor.id)
  else if (claimFamily === 'homeContents') expanded.add(privacyContent.homeContents.id)
  else {
    expanded.add(privacyContent.motor.id)
    expanded.add(privacyContent.homeContents.id)
  }
  return expanded
}

function useMobilePrivacyLayout() {
  const [query] = useState(() => (
    typeof globalThis.matchMedia === 'function'
      ? globalThis.matchMedia(MOBILE_PRIVACY_QUERY)
      : null
  ))
  const [isMobile, setIsMobile] = useState(Boolean(query?.matches))

  useEffect(() => {
    if (!query) return undefined
    const update = (event) => setIsMobile(event.matches)
    query.addEventListener?.('change', update)
    query.addListener?.(update)
    return () => {
      query.removeEventListener?.('change', update)
      query.removeListener?.(update)
    }
  }, [query])

  return isMobile
}

function ConfigValue({ path }) {
  return <span className="privacy-config-value">{readPrivacyConfiguration(path)}</span>
}

function ContentList({ intro, items }) {
  return (
    <>
      {intro && <p>{intro}</p>}
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </>
  )
}

function ContentBlock({ block }) {
  if (block.type === 'paragraph') return <p>{block.text}</p>

  if (block.type === 'parts') {
    return (
      <p>
        {block.parts.map((part, index) => (
          typeof part === 'string'
            ? <span key={`${part}-${index}`}>{part}</span>
            : <ConfigValue key={part.config} path={part.config} />
        ))}
      </p>
    )
  }

  if (block.type === 'list' || block.type === 'bullets') {
    return <ContentList intro={block.intro} items={block.items} />
  }

  if (block.type === 'subsection') {
    return (
      <div className="privacy-subsection">
        <h3>{block.title}</h3>
        {block.intro && <p>{block.intro}</p>}
        {block.items && <ContentList items={block.items} />}
        {block.paragraphs?.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </div>
    )
  }

  if (block.type === 'configuration') {
    return (
      <div className="privacy-configuration" role="note">
        <strong>{block.label}</strong>
        <ConfigValue path={block.config} />
      </div>
    )
  }

  if (block.type === 'configuration-list') {
    return (
      <>
        <p>{block.intro}</p>
        <ul className="privacy-configuration-list">
          {block.items.map(([label, path]) => (
            <li key={path}>
              <strong>{label}:</strong> <ConfigValue path={path} />
            </li>
          ))}
        </ul>
      </>
    )
  }

  if (block.type === 'privacy-contact') {
    return (
      <address className="privacy-contact">
        <strong>Privacy Officer</strong>
        <ConfigValue path="organisation.legalName" />
        <ConfigValue path="organisation.address" />
        <span>Email: <ConfigValue path="contact.privacyOfficerEmail" /></span>
        <span>Phone: <ConfigValue path="contact.privacyOfficerPhone" /></span>
        <span>Website: <ConfigValue path="organisation.websiteUrl" /></span>
      </address>
    )
  }

  if (block.type === 'privacy-commissioner-contact') {
    return (
      <address className="privacy-contact">
        <strong>Office of the Privacy Commissioner</strong>
        <span>
          Website:{' '}
          <a href="https://www.privacy.org.nz/">Office of the Privacy Commissioner website</a>
        </span>
        <span>Phone: 0800 803 909</span>
      </address>
    )
  }

  return null
}

function ProductBlocks({ section }) {
  return (
    <>
      <p>{section.intro}</p>
      <ContentList items={section.items} />
      <p>{section.closing}</p>
    </>
  )
}

function TableOfContents({ activeSection, isMobile, onSelect, sections }) {
  const links = (
    <ol>
      {sections.map((section) => (
        <li key={section.id}>
          <a
            href={`#${section.id}`}
            aria-current={activeSection === section.id ? 'location' : undefined}
            onClick={() => onSelect(section.id)}
          >
            {section.title}
          </a>
        </li>
      ))}
    </ol>
  )

  if (isMobile) {
    return (
      <details className="privacy-toc-mobile">
        <summary>On this page</summary>
        <nav aria-label="On this page">{links}</nav>
      </details>
    )
  }

  return (
    <nav className="privacy-toc-desktop" aria-label="On this page">
      <h2>On this page</h2>
      {links}
    </nav>
  )
}

function PrivacySection({
  active,
  expanded,
  isMobile,
  onToggle,
  section,
}) {
  const headingId = `${section.id}-heading`
  const panelId = `${section.id}-panel`
  const contents = section.blocks
    ? section.blocks.map((block, index) => <ContentBlock block={block} key={`${block.type}-${index}`} />)
    : <ProductBlocks section={section} />

  return (
    <section
      className={`privacy-section ${active ? 'is-current-section' : ''}`}
      id={section.id}
      aria-labelledby={headingId}
      data-claim-relevance={section.relevance || undefined}
    >
      {section.relevance === 'other' && <p className="privacy-section-context">Other claim types</p>}
      {section.relevance === 'current' && <p className="privacy-section-context">Your current claim</p>}
      <h2 className="privacy-section-heading">
        {isMobile ? (
          <button
            id={headingId}
            type="button"
            aria-expanded={expanded}
            aria-controls={panelId}
            onClick={onToggle}
          >
            <span>{section.title}</span>
            <span aria-hidden="true">{expanded ? '−' : '+'}</span>
          </button>
        ) : (
          <span id={headingId}>{section.title}</span>
        )}
      </h2>
      <div
        className={`privacy-section-content ${isMobile && !expanded ? 'is-collapsed' : ''}`}
        id={panelId}
        aria-labelledby={headingId}
      >
        {contents}
      </div>
    </section>
  )
}

export default function PrivacyPage({
  claimType = null,
  hasCurrentClaim = false,
  onViewClaim = null,
  showPrototypeNotice = import.meta.env.DEV,
}) {
  const articleRef = useRef(null)
  const isMobile = useMobilePrivacyLayout()
  const claimFamily = normaliseClaimFamily(claimType)
  const displayPrototypeNotice = import.meta.env.DEV && showPrototypeNotice
  const productSections = useMemo(() => productPrivacySections(claimFamily), [claimFamily])
  const sections = useMemo(() => [
    ...privacyContent.common.sectionsBeforeProducts,
    ...productSections,
    ...privacyContent.common.sectionsAfterProducts,
  ], [productSections])
  const sectionIds = useMemo(() => new Set(sections.map((section) => section.id)), [sections])
  const [activeSection, setActiveSection] = useState(sections[0].id)
  const [expandedSections, setExpandedSections] = useState(
    () => initialExpandedSections(claimFamily),
  )

  useEffect(() => {
    if (!displayPrototypeNotice) return
    const unresolved = unresolvedPrivacyConfiguration()
    if (unresolved.length > 0) {
      console.warn(`[Privacy prototype] Unresolved production configuration: ${unresolved.join(', ')}`)
    }
  }, [displayPrototypeNotice])

  useEffect(() => {
    const applyFragment = () => {
      const sectionId = globalThis.location?.hash?.slice(1)
      if (!sectionIds.has(sectionId)) return
      setActiveSection(sectionId)
      setExpandedSections((current) => new Set(current).add(sectionId))
      const scrollToSection = () => {
        globalThis.document?.getElementById(sectionId)?.scrollIntoView?.({ block: 'start' })
      }
      if (typeof globalThis.requestAnimationFrame === 'function') {
        globalThis.requestAnimationFrame(scrollToSection)
      } else {
        scrollToSection()
      }
    }
    applyFragment()
    globalThis.addEventListener?.('hashchange', applyFragment)
    return () => globalThis.removeEventListener?.('hashchange', applyFragment)
  }, [sectionIds])

  useEffect(() => {
    if (typeof globalThis.IntersectionObserver !== 'function') return undefined
    const root = articleRef.current?.closest('.conversation-panel') || null
    const observer = new globalThis.IntersectionObserver((entries) => {
      const nearest = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => Math.abs(left.boundingClientRect.top) - Math.abs(right.boundingClientRect.top))[0]
      if (nearest?.target?.id) setActiveSection(nearest.target.id)
    }, {
      root,
      rootMargin: '-15% 0px -70% 0px',
      threshold: 0,
    })
    sections.forEach((section) => {
      const element = globalThis.document?.getElementById(section.id)
      if (element) observer.observe(element)
    })
    return () => observer.disconnect()
  }, [sections])

  function selectSection(sectionId) {
    setActiveSection(sectionId)
    setExpandedSections((current) => new Set(current).add(sectionId))
  }

  function toggleSection(sectionId) {
    setExpandedSections((current) => {
      const next = new Set(current)
      if (next.has(sectionId)) next.delete(sectionId)
      else next.add(sectionId)
      return next
    })
  }

  const claimOrderMessage = claimFamily === 'motor'
    ? 'Motor claim information is shown first for your current claim.'
    : claimFamily === 'homeContents'
      ? 'Home & Contents claim information is shown first for your current claim.'
      : 'Motor and Home & Contents information is shown with equal prominence.'

  return (
    <article className="privacy-page" ref={articleRef}>
      {displayPrototypeNotice && (
        <div className="privacy-prototype-notice" role="note">
          {privacyContent.prototypeNotice}
        </div>
      )}

      <header className="privacy-header">
        <p className="privacy-eyebrow">{privacyContent.common.eyebrow}</p>
        <h1>{privacyContent.common.title}</h1>
        <p className="privacy-introduction">{privacyContent.common.introduction}</p>
        <p className="privacy-date">
          <strong>Last updated:</strong> {privacyContent.lastUpdated.prototype}
          <span>Prototype document date</span>
        </p>
      </header>

      <section className="privacy-commitments" aria-labelledby="privacy-commitments-title">
        <h2 id="privacy-commitments-title">{privacyContent.common.commitmentsHeading}</h2>
        <div className="privacy-commitment-grid">
          {privacyContent.common.commitments.map((commitment) => (
            <article className="privacy-commitment" key={commitment.title}>
              <h3>{commitment.title}</h3>
              <p>{commitment.text}</p>
            </article>
          ))}
        </div>
      </section>

      {hasCurrentClaim && (
        <aside className="privacy-current-claim" aria-labelledby="privacy-current-claim-title">
          <h2 id="privacy-current-claim-title">{privacyContent.common.currentClaim.title}</h2>
          <p>{privacyContent.common.currentClaim.text}</p>
          {typeof onViewClaim === 'function' && (
            <button type="button" className="privacy-claim-action" onClick={onViewClaim}>
              {privacyContent.common.currentClaim.action}
            </button>
          )}
        </aside>
      )}

      <p className="privacy-claim-order" role="status" aria-live="polite">{claimOrderMessage}</p>

      {isMobile && (
        <TableOfContents
          activeSection={activeSection}
          isMobile
          onSelect={selectSection}
          sections={sections}
        />
      )}

      <div className="privacy-layout">
        <div className="privacy-sections">
          {sections.map((section) => (
            <PrivacySection
              active={activeSection === section.id}
              expanded={!isMobile || expandedSections.has(section.id)}
              isMobile={isMobile}
              key={section.id}
              onToggle={() => toggleSection(section.id)}
              section={section}
            />
          ))}
        </div>

        {!isMobile && (
          <TableOfContents
            activeSection={activeSection}
            isMobile={false}
            onSelect={selectSection}
            sections={sections}
          />
        )}
      </div>
    </article>
  )
}
