export const PROFILE_CATEGORIES = [
  { key: 'personal-details', label: 'Personal details' },
  { key: 'insured-assets', label: 'Insured assets' },
  { key: 'payment-details', label: 'Payment details' },
  { key: 'identity-verification', label: 'Identity & verification' },
  { key: 'claim-auto-fill', label: 'Claim auto-fill' },
]

const PROFILE_CATEGORY_KEYS = new Set(PROFILE_CATEGORIES.map(({ key }) => key))

export function profileSectionFromPath(pathname = '') {
  const match = pathname.match(/^\/profile\/([^/]+)$/)
  if (!match) return null
  if (match[1] === 'policies') return 'personal-details'
  return PROFILE_CATEGORY_KEYS.has(match[1]) ? match[1] : null
}

export function profilePathForSection(section) {
  return section && PROFILE_CATEGORY_KEYS.has(section) ? `/profile/${section}` : '/profile'
}
