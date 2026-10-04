import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, BUSY, type WorkflowSummary } from '../api'
import { Card, ErrorNote, PlatformBadge, StatusBadge } from '../components/ui'
import { timeLeft } from '../format'

export function CatalogPage() {
  const workflows = useQuery({
    queryKey: ['workflows'],
    queryFn: api.workflows,
    refetchInterval: (q) =>
      q.state.data?.some((w) => w.deployment && (BUSY.includes(w.deployment.status) || w.deployment.status === 'awaiting_user'))
        ? 2000
        : false,
  })
  return (
    <div>
      <h1 className="text-xl font-semibold">Workflows</h1>
      <p className="mt-1 text-sm text-slate-600">
        Connect the accounts a workflow needs, deploy it, then try it. Deployments stop automatically after 24 hours.
      </p>
      <ErrorNote error={workflows.error} />
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {workflows.data?.map((w) => <WorkflowCard key={w.id} workflow={w} />)}
      </div>
    </div>
  )
}

function WorkflowCard({ workflow }: { workflow: WorkflowSummary }) {
  const dep = workflow.deployment
  const left = dep?.status === 'active' ? timeLeft(dep.expires_at) : null
  return (
    <Link to={`/workflows/${workflow.id}`} data-testid={`card-${workflow.id}`} className="group">
      <Card className="h-full transition group-hover:ring-indigo-300">
        <div className="flex items-start justify-between gap-2">
          <h2 className="font-semibold">{workflow.name}</h2>
          <PlatformBadge platform={workflow.platform} />
        </div>
        <p className="mt-2 text-sm text-slate-600">{workflow.summary}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {workflow.connectors.map((c) => (
            <span
              key={c.id}
              className={`rounded px-2 py-0.5 text-xs ${
                c.managed_by_platform
                  ? 'bg-violet-50 text-violet-700'
                  : c.connected
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-slate-100 text-slate-500'
              }`}
            >
              {c.connected ? '✓ ' : ''}
              {c.name}
            </span>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
          {workflow.available ? (
            <StatusBadge status={dep?.status} />
          ) : (
            <span className="rounded-full bg-slate-200 px-2.5 py-0.5 font-semibold text-slate-700">
              Deploy unavailable
            </span>
          )}
          {left && <span>{left}</span>}
        </div>
      </Card>
    </Link>
  )
}
