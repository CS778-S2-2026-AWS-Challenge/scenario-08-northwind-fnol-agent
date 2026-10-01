import { describe, expect, it } from 'vitest'

import { claimReviewRequirements, claimReviewSections } from './claimReviewProjection.js'

describe('claim review projection', () => {
  it('groups claimant-visible Claim fields without copying their values', () => {
    const form = {
      'claim.product_family': { value: 'home', status: 'confirmed' },
      'incident.description': { value: 'A pipe burst.', status: 'confirmed' },
      'incident.location': { value: 'Kitchen', status: 'proposed' },
      'property.address': { value: '1 Queen Street', status: 'confirmed' },
      'parties.other_parties': { value: 'None', status: 'confirmed' },
      'property.habitable': { value: true, status: 'confirmed' },
      'custom.claimant_note': { value: 'Call after 4pm', status: 'confirmed' },
    }

    expect(claimReviewSections(form)).toEqual([
      {
        id: 'overview',
        title: 'Claim overview',
        fields: [
          ['claim.product_family', form['claim.product_family']],
          ['custom.claimant_note', form['custom.claimant_note']],
        ],
        contentsItems: [],
        missingFields: [],
      },
      {
        id: 'incident',
        title: 'Incident details',
        fields: [
          ['incident.description', form['incident.description']],
          ['incident.location', form['incident.location']],
          ['parties.other_parties', form['parties.other_parties']],
        ],
        contentsItems: [],
        missingFields: [],
      },
      {
        id: 'loss',
        title: 'Insured item and loss',
        fields: [['property.address', form['property.address']]],
        contentsItems: [],
        missingFields: [],
      },
      {
        id: 'safety',
        title: 'Safety and ongoing risk',
        fields: [['property.habitable', form['property.habitable']]],
        contentsItems: [],
        missingFields: [],
      },
    ])
  })

  it('keeps contents items in the loss section instead of inventing form fields', () => {
    const contentsItems = [
      { item_id: 'item-1', description: 'Laptop', status: 'proposed' },
    ]

    const sections = claimReviewSections({}, contentsItems)

    expect(sections).toHaveLength(4)
    expect(sections.find((section) => section.id === 'loss')).toEqual({
      id: 'loss',
      title: 'Insured item and loss',
      fields: [],
      contentsItems,
      missingFields: [],
    })
  })

  it('reads missing and later requirements only from the backend projection', () => {
    const dynamicForm = {
      requirements: {
        ready: false,
        missing_required_now: ['incident.occurred_at', 'incident.occurred_at'],
        pending_later: ['property.address'],
        current_action_total: 5,
        current_action_satisfied: 3,
      },
    }

    expect(claimReviewRequirements(dynamicForm)).toEqual({
      available: true,
      ready: false,
      missingRequiredNow: ['incident.occurred_at'],
      pendingLater: ['property.address'],
      currentActionTotal: 5,
      currentActionSatisfied: 3,
    })
  })

  it('does not infer readiness when the backend requirements projection is absent', () => {
    expect(claimReviewRequirements(null)).toEqual({
      available: false,
      ready: false,
      missingRequiredNow: [],
      pendingLater: [],
      currentActionTotal: null,
      currentActionSatisfied: null,
    })
  })

  it('maps missing safety information into the dedicated summary section', () => {
    const sections = claimReviewSections({}, [], ['property.habitable'])

    expect(sections.find((section) => section.id === 'safety').missingFields).toEqual([
      'property.habitable',
    ])
  })
})
