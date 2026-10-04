import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { api, ApiError, type DeploymentStatus, type SetupCheck, type SweepReport } from '../api'
import { Button, Card, ErrorNote, StatusBadge } from '../components/ui'
import { shortTime, timeLeft } from '../format'

const STOPPABLE: DeploymentStatus[] = ['active', 'awaiting_user', 'failed']
const STATE_STYLE = {
  ok: 'text-emerald-700',
  missing: 'text-amber-700',
  error: 'text-red-700',
  info: 'text-slate-600',
} as const
const STATE_ICON = { ok: '✓', missing: '–', error: '✗', info: 'i' } as const

export function AdminPage() {
  const queryClient = useQueryClient()
  const overview = useQuery({ queryKey: ['admin'], queryFn: api.adminOverview, refetchInterval: 10000 })
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<unknown>(null)

  const signIn = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await api.adminLogin(passcode)
      await queryClient.invalidateQueries({ queryKey: ['admin'] })
    } catch (err) {
      setError(err)
    }
  }

  if (overview.error instanceof ApiError && overview.error.status === 401) {
    return (
      <Card className="max-w-sm">
        <h1 className="font-semibold">Admin</h1>
        <form onSubmit={signIn} className="mt-4 space-y-3">
          <input
            type="password"
            name="admin-passcode"
            placeholder="Admin passcode"
            value={passcode}
            onChange={(e) => setPasscode(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <ErrorNote error={error} />
          <Button type="submit">Sign in</Button>
        </form>
      </Card>
    )
  }
  if (!overview.data) return <ErrorNote error={overview.error} />
  const data = overview.data
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Admin</h1>
      <p className="text-sm text-slate-600">
        {data.users.length} of {data.max_users} users · {data.fake_platforms ? 'fake platforms' : 'live platforms'}
      </p>
      <AdminTools />
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-sm" data-testid="admin-users">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-2">User</th>
              <th className="px-4 py-2">Last sign-in</th>
              <th className="px-4 py-2">Connections</th>
              <th className="px-4 py-2">Deployments</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.users.map((u) => (
              <tr key={u.username} className="align-top">
                <td className="px-4 py-2 font-medium">{u.username}</td>
                <td className="px-4 py-2 text-slate-600">{shortTime(u.last_login_at)}</td>
                <td className="px-4 py-2 text-slate-600">{u.connections.join(', ') || '—'}</td>
                <td className="space-y-1 px-4 py-2">
                  {u.deployments.length === 0 && <span className="text-slate-400">—</span>}
                  {u.deployments.map((d) => (
                    <div key={d.workflow_id} className="flex flex-wrap items-center gap-2">
                      <span>{d.workflow_id}</span>
                      <StatusBadge status={d.status} />
                      <span className="text-xs text-slate-500">{d.status === 'active' ? timeLeft(d.expires_at) : d.error}</span>
                      {STOPPABLE.includes(d.status) && <StopButton username={u.username} workflowId={d.workflow_id} />}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function StopButton({ username, workflowId }: { username: string; workflowId: string }) {
  const queryClient = useQueryClient()
  const stop = useMutation({
    mutationFn: () => api.adminStop(username, workflowId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['admin'] }),
  })
  return (
    <button
      className="text-xs font-medium text-red-700 hover:underline disabled:text-slate-400"
      disabled={stop.isPending}
      onClick={() => {
        if (window.confirm(`Stop ${workflowId} for ${username}?`)) stop.mutate()
      }}
    >
      Stop
    </button>
  )
}

function AdminTools() {
  const queryClient = useQueryClient()
  const setup = useMutation({ mutationFn: api.adminSetup })
  const sweep = useMutation({
    mutationFn: api.adminSweep,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['admin'] }),
  })
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">Setup check</h2>
          <Button variant="secondary" onClick={() => setup.mutate()} disabled={setup.isPending}>
            {setup.isPending ? 'Checking…' : 'Run setup check'}
          </Button>
        </div>
        <ErrorNote error={setup.error} />
        {setup.data && <SetupResults data={setup.data} />}
      </Card>
      <Card>
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold">Housekeeping</h2>
          <Button variant="secondary" onClick={() => sweep.mutate()} disabled={sweep.isPending}>
            {sweep.isPending ? 'Sweeping…' : 'Run sweeper now'}
          </Button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Runs on a schedule: stops deployments past their 24 h limit or with an unfinished popup, recovers lost
          jobs and (with ORPHAN_SWEEP on) removes demo items on n8n and Make that no deployment uses.
        </p>
        <ErrorNote error={sweep.error} />
        {sweep.data && <SweepResults report={sweep.data} />}
      </Card>
    </div>
  )
}

function SetupResults({ data }: { data: SetupCheck }) {
  return (
    <div className="mt-3 space-y-3 text-sm" data-testid="setup-check">
      <ul className="space-y-1">
        {data.checks.map((c) => (
          <li key={c.name} className="flex gap-2">
            <span className={`w-4 font-semibold ${STATE_STYLE[c.state]}`}>{STATE_ICON[c.state]}</span>
            <span className="font-medium">{c.name}</span>
            <span className="text-slate-600">{c.detail}</span>
          </li>
        ))}
      </ul>
      <ul className="space-y-1 border-t border-slate-100 pt-2">
        {data.workflows.map((w) => (
          <li key={w.id} className="flex gap-2">
            <span className={`w-4 font-semibold ${w.available ? STATE_STYLE.ok : STATE_STYLE.missing}`}>
              {w.available ? STATE_ICON.ok : STATE_ICON.missing}
            </span>
            <span className="font-medium">{w.name}</span>
            <span className="text-slate-600">{w.available ? w.platform : w.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function SweepResults({ report }: { report: SweepReport }) {
  const lines = [
    ...report.stopped.map((s) => `Stopped ${s}`),
    ...(report.recovered_jobs ? [`Recovered ${report.recovered_jobs} lost job(s)`] : []),
    ...report.orphans_removed.map((s) => `Removed ${s}`),
    ...report.errors.map((s) => `Error: ${s}`),
  ]
  return (
    <ul className="mt-3 space-y-1 text-sm text-slate-700" data-testid="sweep-report">
      {lines.length ? lines.map((line) => <li key={line}>{line}</li>) : <li>Nothing to do.</li>}
      {!report.orphan_sweep && (
        <li className="text-xs text-slate-500">Platform orphan clean-up is off on this server (ORPHAN_SWEEP).</li>
      )}
    </ul>
  )
}
