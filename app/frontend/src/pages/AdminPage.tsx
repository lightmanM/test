import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Card, ErrorNote, StatusBadge } from '../components/ui'
import { shortTime, timeLeft } from '../format'

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
