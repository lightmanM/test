import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { api, type ConnectorStatus, refreshAll, type WorkflowDetail } from '../api'
import { useHealth } from '../hooks'
import { connectWithNango } from '../nango'
import { Button, ErrorNote } from './ui'

export function ConnectStep({ workflow }: { workflow: WorkflowDetail }) {
  return (
    <ul className="divide-y divide-slate-100">
      {workflow.connectors.map((c) => (
        <ConnectorRow key={c.id} connector={c} />
      ))}
    </ul>
  )
}

function ConnectorRow({ connector }: { connector: ConnectorStatus }) {
  const queryClient = useQueryClient()
  const health = useHealth().data
  const [error, setError] = useState<unknown>(null)
  const [editing, setEditing] = useState(false)
  const options = { onMutate: () => setError(null), onSuccess: () => refreshAll(queryClient), onError: setError }
  const popup = useMutation({ mutationFn: () => connectWithNango(connector.id), ...options })
  const fake = useMutation({ mutationFn: () => api.fakeConnect(connector.id), ...options })
  const disconnect = useMutation({ mutationFn: () => api.disconnect(connector.id), ...options })
  const busy = popup.isPending || fake.isPending || disconnect.isPending

  let actions
  if (connector.managed_by_platform) {
    actions = <span className="max-w-48 text-right text-xs text-violet-700">Connected in Make's popup when you deploy</span>
  } else if (connector.kind === 'manual') {
    actions = connector.connected && !editing && (
      <div className="flex gap-2">
        <Button variant="secondary" onClick={() => setEditing(true)} disabled={busy}>
          Change
        </Button>
        <Button variant="secondary" onClick={() => disconnect.mutate()} disabled={busy}>
          Remove
        </Button>
      </div>
    )
  } else {
    const canPopup = !!health?.nango_enabled
    const connectButton = canPopup ? (
      <Button variant={connector.connected ? 'secondary' : 'primary'} onClick={() => popup.mutate()} disabled={busy}>
        {connector.connected ? 'Reconnect' : 'Connect'}
      </Button>
    ) : health?.fake_platforms ? (
      !connector.connected && (
        <Button onClick={() => fake.mutate()} disabled={busy}>
          Connect (demo data)
        </Button>
      )
    ) : (
      !connector.connected && (
        <Button disabled title="Account connections aren't configured on this server yet">
          Connect
        </Button>
      )
    )
    actions = (
      <div className="flex gap-2">
        {connectButton}
        {connector.connected && (
          <Button variant="secondary" onClick={() => disconnect.mutate()} disabled={busy}>
            Disconnect
          </Button>
        )}
      </div>
    )
  }

  const showForm = connector.kind === 'manual' && (!connector.connected || editing)
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3" data-testid={`connector-${connector.id}`}>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          {connector.name}
          {connector.connected && <span className="ml-2 text-xs font-semibold text-emerald-700">Connected</span>}
        </p>
        {connector.connected && connector.label && <p className="text-xs text-slate-500">{connector.label}</p>}
        <p className="text-sm text-slate-600">{connector.purpose}</p>
        {connector.help && (!connector.connected || editing) && (
          <p className="mt-1 text-xs text-slate-500">{connector.help}</p>
        )}
        {showForm && (
          <ManualValueForm
            connector={connector}
            onSaved={() => setEditing(false)}
            onCancel={connector.connected ? () => setEditing(false) : undefined}
          />
        )}
        <div className="mt-2">
          <ErrorNote error={error} />
        </div>
      </div>
      {actions}
    </li>
  )
}

function ManualValueForm({
  connector,
  onSaved,
  onCancel,
}: {
  connector: ConnectorStatus
  onSaved: () => void
  onCancel?: () => void
}) {
  const queryClient = useQueryClient()
  const [value, setValue] = useState('')
  const save = useMutation({
    mutationFn: () => api.saveSecret(connector.id, value),
    onSuccess: async () => {
      setValue('')
      onSaved()
      await refreshAll(queryClient)
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-2">
        <input
          name={connector.id}
          aria-label={connector.name}
          type={connector.secret ? 'password' : 'text'}
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={connector.secret ? 'Paste the token' : 'Enter the value'}
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <Button type="submit" disabled={save.isPending || !value.trim()}>
          Save
        </Button>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={save.isPending}>
            Cancel
          </Button>
        )}
      </div>
      {connector.secret && (
        <p className="text-xs text-slate-500">Stored encrypted and only used when you deploy. It's never shown again.</p>
      )}
      <ErrorNote error={save.error} />
    </form>
  )
}
