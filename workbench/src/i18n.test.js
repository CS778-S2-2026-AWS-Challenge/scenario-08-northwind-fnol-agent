import { afterEach, describe, expect, it } from 'vitest'
import { formatDateTime, words } from './format.js'
import { getLanguage, setLanguage, translate } from './i18n.js'

describe('Workbench localisation', () => {
  afterEach(() => setLanguage('en'))

  it('switches supported language immediately and interpolates translated copy', () => {
    setLanguage('zh-CN')

    expect(getLanguage()).toBe('zh-CN')
    expect(document.documentElement).toHaveAttribute('lang', 'zh-CN')
    expect(translate('Account menu for {name}', { name: 'Alex' })).toBe('Alex 的账户菜单')
    expect(formatDateTime('2026-09-27T05:08:00Z')).toMatch(/2026/)
    expect(words('standard')).toBe('Standard')
  })

  it('falls back to the English source for missing translations and unsupported languages', () => {
    setLanguage('zh-CN')
    expect(translate('Server-authored text')).toBe('Server-authored text')

    setLanguage('fr')
    expect(getLanguage()).toBe('en')
    expect(translate('Profile')).toBe('Profile')
  })
})
