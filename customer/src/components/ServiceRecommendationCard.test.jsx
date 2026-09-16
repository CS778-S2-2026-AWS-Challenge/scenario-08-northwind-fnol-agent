import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import ServiceRecommendationCard from './ServiceRecommendationCard.jsx'

const BASE_RECOMMENDATION = {
  icon: '/provider-icons/repair-service.png',
  providerName: 'Repair Service',
  domain: 'repairservice.co.nz',
  serviceType: 'Repair estimate',
  title: 'Get a repair estimate online',
  description: 'Upload photos of the damaged item and request an estimated repair cost.',
  url: 'https://repairservice.co.nz/estimate',
  relationship: 'third_party',
  ctaLabel: 'Get estimate',
}

function renderCard(overrides = {}) {
  return render(
    <ServiceRecommendationCard {...BASE_RECOMMENDATION} {...overrides} />,
  )
}

describe('Service recommendation card', () => {
  it('renders explicit provider and service data as a compact external link card', async () => {
    const user = userEvent.setup()
    const { container } = renderCard()

    expect(screen.getByRole('heading', { name: 'Get a repair estimate online' }))
      .toBeInTheDocument()
    expect(screen.getByText('Repair Service')).toBeInTheDocument()
    expect(screen.getByText('repairservice.co.nz')).toBeInTheDocument()
    expect(screen.getByText('Repair estimate')).toBeInTheDocument()
    expect(screen.getByText(BASE_RECOMMENDATION.description)).toBeInTheDocument()
    expect(screen.getByText('Third-party service')).toBeInTheDocument()
    expect(screen.getByText('External')).toBeInTheDocument()

    const link = screen.getByRole('link', {
      name: 'Get estimate: Get a repair estimate online from Repair Service (opens in a new tab)',
    })
    expect(link).toHaveAttribute('href', BASE_RECOMMENDATION.url)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')

    await user.tab()
    expect(link).toHaveFocus()
    expect(container.querySelector('.service-recommendation-card')).toContainElement(link)
  })

  it('uses the Northwind partner label only for the explicit supported relationship value', () => {
    const { rerender } = renderCard({ relationship: 'partner' })

    expect(screen.getByText('Third-party service')).toBeInTheDocument()
    expect(screen.queryByText('Northwind partner')).not.toBeInTheDocument()

    rerender(
      <ServiceRecommendationCard
        {...BASE_RECOMMENDATION}
        relationship="northwind_partner"
      />,
    )

    expect(screen.getByText('Northwind partner')).toBeInTheDocument()
    expect(screen.queryByText('Third-party service')).not.toBeInTheDocument()
  })

  it('uses a compact provider initial when no usable icon is supplied', () => {
    const { container } = renderCard({ icon: 'javascript:alert(1)' })

    expect(container.querySelector('.service-recommendation-icon')).toHaveTextContent('R')
    expect(container.querySelector('img')).not.toBeInTheDocument()
  })

  it('falls back to the provider initial if the supplied icon cannot load', () => {
    const { container } = renderCard()
    const icon = container.querySelector('img')

    fireEvent.error(icon)

    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(container.querySelector('.service-recommendation-icon')).toHaveTextContent('R')
  })

  it.each([
    ['javascript:alert(1)', 'repairservice.co.nz'],
    ['ftp://repairservice.co.nz/estimate', 'repairservice.co.nz'],
    ['/estimate', 'repairservice.co.nz'],
    ['https://lookalike.example/estimate', 'repairservice.co.nz'],
  ])('does not render an external action for unsafe or misleading URL %s', (url, domain) => {
    const { container } = renderCard({ url, domain })

    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('can be composed directly after Agent text inside one conversation message', () => {
    render(
      <article aria-label="Claims assistant message">
        <p>I can point you to a service that may help with the estimate.</p>
        <ServiceRecommendationCard {...BASE_RECOMMENDATION} />
      </article>,
    )

    const message = screen.getByRole('article', { name: 'Claims assistant message' })
    const card = message.querySelector('.service-recommendation-card')
    expect(card).toBeInTheDocument()
    expect(message).toContainElement(
      screen.getByRole('link', { name: /Get estimate: Get a repair estimate online/ }),
    )
  })
})
