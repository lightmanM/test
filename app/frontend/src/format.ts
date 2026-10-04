// Small formatting helpers (pure, unit-tested in format.test.ts).

export function timeLeft(iso: string | null, now: Date = new Date()): string | null {
  if (!iso) return null
  const ms = new Date(iso).getTime() - now.getTime()
  if (ms <= 0) return 'expiring now'
  const minutes = Math.floor(ms / 60000)
  const hours = Math.floor(minutes / 60)
  if (hours >= 1) return `expires in ${hours} h ${minutes % 60} min`
  return `expires in ${Math.max(minutes, 1)} min`
}

export function shortTime(iso: string | null): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export type Segment = { text: string; bold?: boolean; code?: boolean }

/** Minimal inline markdown: **bold** and `code`. Everything else stays text (React escapes it). */
export function inlineMarkdown(text: string): Segment[] {
  const out: Segment[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > last) out.push({ text: text.slice(last, index) })
    const token = match[0]
    out.push(token.startsWith('**') ? { text: token.slice(2, -2), bold: true } : { text: token.slice(1, -1), code: true })
    last = index + token.length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

export interface SettingShape {
  key: string
  type: string
  options: unknown[] | null
}

export function settingsFromForm(values: Record<string, string>, settings: SettingShape[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const setting of settings) {
    const raw = values[setting.key] ?? ''
    const { key, type } = setting
    if (type === 'url_list') {
      out[key] = raw
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    } else if (type === 'number') {
      out[key] = raw === '' ? null : Number(raw)
    } else if (type === 'select') {
      // Send the option itself so its type (number or string) matches the catalog.
      const option = (setting.options ?? []).find((o) => String(o) === raw)
      out[key] = option === undefined ? raw : option
    } else {
      out[key] = raw
    }
  }
  return out
}

export function formValue(value: unknown, type: string): string {
  if (value === null || value === undefined) return ''
  if (type === 'url_list' && Array.isArray(value)) return value.join('\n')
  return String(value)
}
