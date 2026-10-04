import { describe, expect, it } from 'vitest'
import { formValue, inlineMarkdown, settingsFromForm, timeLeft } from './format'

describe('timeLeft', () => {
  const now = new Date('2026-10-04T00:00:00Z')
  it('formats hours and minutes', () => {
    expect(timeLeft('2026-10-04T23:10:00Z', now)).toBe('expires in 23 h 10 min')
    expect(timeLeft('2026-10-04T00:05:30Z', now)).toBe('expires in 5 min')
    expect(timeLeft('2026-10-03T00:00:00Z', now)).toBe('expiring now')
    expect(timeLeft(null, now)).toBeNull()
  })
})

describe('inlineMarkdown', () => {
  it('splits bold and code', () => {
    expect(inlineMarkdown('Click **Run now**, then `@bot hi`.')).toEqual([
      { text: 'Click ' },
      { text: 'Run now', bold: true },
      { text: ', then ' },
      { text: '@bot hi', code: true },
      { text: '.' },
    ])
  })
})

describe('settings form conversion', () => {
  it('converts per type', () => {
    expect(
      settingsFromForm(
        { sites: 'https://a.dev\n\n https://b.dev ', window: '24', version: '2.0', channel: 'C0123ABCD' },
        [
          { key: 'sites', type: 'url_list', options: null },
          { key: 'window', type: 'select', options: [24, 720] },
          { key: 'version', type: 'select', options: ['1.5', '2.0'] },
          { key: 'channel', type: 'slack_channel', options: null },
        ],
      ),
    ).toEqual({ sites: ['https://a.dev', 'https://b.dev'], window: 24, version: '2.0', channel: 'C0123ABCD' })
    expect(formValue(['x', 'y'], 'url_list')).toBe('x\ny')
    expect(formValue(undefined, 'string')).toBe('')
  })
})
