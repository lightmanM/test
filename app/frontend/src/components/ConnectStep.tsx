import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ConnectorStatus, type WorkflowDetail } from '../api'
import { Button, ErrorNote } from './ui'

export function ConnectStep({ workflow, fakeMode }: { workflow: WorkflowDetail; fakeMode: boolean }) {
  return (
    <ul className="divide-y divide-slate-100">
      {workflow.connectors.map((c) => (
        <ConnectorRow key={c.id} connector={c} fakeMode={fakeMode} />
      ))}
    </ul>
  )
}

function ConnectorRow({ connector, fakeMode }: { connector: ConnectorStatus; fakeMode: boolean }) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const refresh = () => queryClient.invalidateQueries()
  const connect = useMutation({
    mutationFn: () => api.fakeConnect(connector.id),
    onSuccess: refresh,
    onError: setError,
  })
  const disconnect = useMutation({ mutationFn: () => api.disconnect(connector.id), onSuccess: refresh, onError: setError })

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3" data-testid={`connector-${connector.id}`}>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          {connector.name}
          {connector.connected && <span className="ml-2 text-xs font-semibold text-emerald-700">Connected</span>}
        </p>
        <p className="text-sm text-slate-600">{connector.purpose}</p>
        {connector.help && !connector.connected && <p className="mt-1 text-xs text-slate-500">{connector.help}</p>}
        <div className="mt-2">
          <ErrorNote error={error} />
        </div>
      </div>
      {connector.managed_by_platform ? (
        <span className="max-w-48 text-right text-xs text-violet-700">Connected in Make's popup when you deploy</span>
      ) : connector.connected ? (
        <Button variant="secondary" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
          Disconnect
        </Button>
      ) : fakeMode ? (
        <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
          Connect (demo data)
        </Button>
      ) : (
        <Button disabled title="Real account connections arrive in the next release">
          Connect
        </Button>
      )}
    </li>
  )
}
