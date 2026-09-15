import { useId, useState } from 'react'

const HTTP_PROTOCOLS = new Set(['http:', 'https:'])
const NORTHWIND_PARTNER = 'northwind_partner'

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0
}

function normaliseDomain(domain) {
  if (!nonEmptyString(domain)) return null
  return domain.trim().toLowerCase().replace(/^www\./, '').replace(/\.$/, '')
}

function safeExternalHref(url, domain) {
  if (!nonEmptyString(url)) return null

  try {
    const parsed = new URL(url)
    const displayedDomain = normaliseDomain(domain)
    const destinationDomain = parsed.hostname.toLowerCase().replace(/^www\./, '')
    const domainMatches = displayedDomain
      && (destinationDomain === displayedDomain || destinationDomain.endsWith(`.${displayedDomain}`))

    if (!HTTP_PROTOCOLS.has(parsed.protocol) || !domainMatches) return null
    return parsed.href
  } catch {
    return null
  }
}

function safeIconSource(icon) {
  if (!nonEmptyString(icon)) return null
  const source = icon.trim()

  if (/^\/(?!\/)/.test(source) || source.startsWith('./') || source.startsWith('../')) {
    return source
  }
  if (/^data:image\/(?:gif|jpeg|png|webp);base64,/i.test(source)) {
    return source
  }

  try {
    const parsed = new URL(source)
    return HTTP_PROTOCOLS.has(parsed.protocol) ? parsed.href : null
  } catch {
    return null
  }
}

function relationshipLabel(relationship) {
  return relationship === NORTHWIND_PARTNER
    ? 'Northwind partner'
    : 'Third-party service'
}

/**
 * Presentational claimant link card. Its caller owns recommendation selection and
 * must supply claimant-safe data from an authoritative projection. The component
 * never infers a Northwind relationship from a provider name, domain, or URL.
 */
export default function ServiceRecommendationCard({
  icon,
  providerName,
  domain,
  serviceType,
  title,
  description,
  url,
  relationship,
  ctaLabel = 'Visit service',
}) {
  const titleId = useId()
  const descriptionId = useId()
  const [failedIconSource, setFailedIconSource] = useState(null)
  const href = safeExternalHref(url, domain)
  const iconSource = safeIconSource(icon)

  if (
    !href
    || !nonEmptyString(providerName)
    || !nonEmptyString(domain)
    || !nonEmptyString(serviceType)
    || !nonEmptyString(title)
    || !nonEmptyString(description)
    || !nonEmptyString(ctaLabel)
  ) {
    return null
  }

  const providerInitial = providerName.trim().charAt(0).toUpperCase()
  const accessibleLinkLabel = `${ctaLabel}: ${title} from ${providerName} (opens in a new tab)`

  return (
    <section
      className="service-recommendation-card"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <span className="service-recommendation-icon" aria-hidden="true">
        {iconSource && failedIconSource !== iconSource ? (
          <img
            src={iconSource}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setFailedIconSource(iconSource)}
          />
        ) : (
          <span>{providerInitial}</span>
        )}
      </span>

      <div className="service-recommendation-provider">
        <strong>{providerName}</strong>
        <span>{domain}</span>
        <span className="service-recommendation-external">
          External <span aria-hidden="true">↗</span>
        </span>
      </div>

      <div className="service-recommendation-purpose">
        <h3 id={titleId} className="service-recommendation-title">{title}</h3>
        <span id={descriptionId} className="service-recommendation-description">
          {description}
        </span>
      </div>

      <div className="service-recommendation-meta">
        <span className="service-recommendation-type">{serviceType}</span>
        <span aria-hidden="true">·</span>
        <span className="service-recommendation-relationship">
          {relationshipLabel(relationship)}
        </span>
      </div>

      <a
        className="service-recommendation-cta"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={accessibleLinkLabel}
      >
        <span>{ctaLabel}</span>
        <span aria-hidden="true">↗</span>
      </a>
    </section>
  )
}
