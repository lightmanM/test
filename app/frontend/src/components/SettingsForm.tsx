import { useQuery } from '@tanstack/react-query'
import { api, type Setting } from '../api'

export function SettingsForm({
  settings,
  values,
  errors,
  onChange,
  disabled,
  slackConnected,
}: {
  settings: Setting[]
  values: Record<string, string>
  errors: Record<string, string>
  onChange: (key: string, value: string) => void
  disabled: boolean
  slackConnected: boolean
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
          ) : s.type === 'slack_channel' ? (
            <SlackChannelField
              setting={s}
              value={values[s.key] ?? ''}
              disabled={disabled}
              slackConnected={slackConnected}
              onChange={(value) => onChange(s.key, value)}
            />
          ) : (
            <input
              name={s.key}
              type={s.type === 'number' ? 'number' : 'text'}
              value={values[s.key] ?? ''}
              disabled={disabled}
              onChange={(e) => onChange(s.key, e.target.value)}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
            />
          )}
          {s.type === 'url_list' && <span className="mt-1 block text-xs text-slate-500">One URL per line.</span>}
          {s.help && <span className="mt-1 block text-xs text-slate-500">{s.help}</span>}
          {errors[s.key] && <span className="mt-1 block text-xs text-red-600">{errors[s.key]}</span>}
        </label>
      ))}
    </div>
  )
}

/** A channel picker once Slack is connected; otherwise (or if listing fails) a channel ID box. */
function SlackChannelField({
  setting,
  value,
  disabled,
  slackConnected,
  onChange,
}: {
  setting: Setting
  value: string
  disabled: boolean
  slackConnected: boolean
  onChange: (value: string) => void
}) {
  const channels = useQuery({
    queryKey: ['slack-channels'],
    queryFn: api.slackChannels,
    enabled: slackConnected,
    staleTime: 60_000,
    retry: false,
  })
  const list = slackConnected ? (channels.data ?? []) : []
  if (list.length > 0) {
    const known = list.some((c) => c.id === value)
    return (
      <select
        name={setting.key}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
      >
        {(!setting.required || !value) && (
          <option value="" disabled={setting.required}>
            {setting.required ? 'Choose a channel…' : 'None'}
          </option>
        )}
        {value && !known && <option value={value}>{value}</option>}
        {list.map((c) => (
          <option key={c.id} value={c.id}>
            #{c.name}
          </option>
        ))}
      </select>
    )
  }
  return (
    <>
      <input
        name={setting.key}
        type="text"
        value={value}
        disabled={disabled}
        placeholder="Channel ID, e.g. C0123ABCD"
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2"
      />
      <span className="mt-1 block text-xs text-slate-500">
        {!slackConnected
          ? 'Connect Slack to pick from a list, or enter the ID: '
          : channels.isPending
            ? 'Loading your channels… or enter the ID: '
            : channels.isError
              ? "Couldn't list your Slack channels, so enter the ID: "
              : 'No public channels found, so enter the ID: '}
        in Slack, open the channel → channel name → the ID is at the bottom of the About tab.
      </span>
    </>
  )
}
