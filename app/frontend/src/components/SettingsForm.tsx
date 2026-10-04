import type { Setting } from '../api'

export function SettingsForm({
  settings,
  values,
  errors,
  onChange,
  disabled,
}: {
  settings: Setting[]
  values: Record<string, string>
  errors: Record<string, string>
  onChange: (key: string, value: string) => void
  disabled: boolean
}) {
  if (settings.length === 0) {
    return <p className="text-sm text-slate-600">Nothing to configure here.</p>
  }
  return (
    <div className="space-y-4">
      {settings.map((s) => (
        <label key={s.key} className="block text-sm">
          <span className="font-medium">
            {s.label}
            {!s.required && <span className="font-normal text-slate-500"> (optional)</span>}
          </span>
          {s.type === 'select' ? (
            <select
              name={s.key}
              value={values[s.key] ?? ''}
              disabled={disabled}
              onChange={(e) => onChange(s.key, e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            >
              {!(s.options ?? []).some((o) => String(o) === (values[s.key] ?? '')) && (
                <option value={values[s.key] ?? ''} disabled>
                  Choose…
                </option>
              )}
              {(s.options ?? []).map((o) => (
                <option key={String(o)} value={String(o)}>
                  {String(o)}
                </option>
              ))}
            </select>
          ) : s.type === 'url_list' ? (
            <textarea
              name={s.key}
              rows={3}
              value={values[s.key] ?? ''}
              disabled={disabled}
              onChange={(e) => onChange(s.key, e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
            />
          ) : (
            <input
              name={s.key}
              type={s.type === 'number' ? 'number' : 'text'}
              value={values[s.key] ?? ''}
              disabled={disabled}
              placeholder={s.type === 'slack_channel' ? 'Channel ID, e.g. C0123ABCD' : undefined}
              onChange={(e) => onChange(s.key, e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            />
          )}
          {s.type === 'url_list' && <span className="mt-1 block text-xs text-slate-500">One URL per line.</span>}
          {s.type === 'slack_channel' && (
            <span className="mt-1 block text-xs text-slate-500">
              In Slack, open the channel → channel name → the ID is at the bottom of the About tab.
            </span>
          )}
          {s.help && <span className="mt-1 block text-xs text-slate-500">{s.help}</span>}
          {errors[s.key] && <span className="mt-1 block text-xs text-red-600">{errors[s.key]}</span>}
        </label>
      ))}
    </div>
  )
}
