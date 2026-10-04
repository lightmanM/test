import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type WorkflowDetail } from '../api'
import { shortTime } from '../format'
import { Button, ErrorNote, Markdown } from './ui'

export function RunsPanel({ workflow }: { workflow: WorkflowDetail }) {
  const active = workflow.deployment?.status === 'active'
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const runs = useQuery({
    queryKey: ['runs', workflow.id],
    queryFn: () => api.runs(workflow.id),
    enabled: active,
    refetchInterval: active ? 10000 : false,
  })
  const runNow = useMutation({
    mutationFn: () => api.runNow(workflow.id),
    onMutate: () => setError(null),
    onError: setError,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['runs', workflow.id] }),
  })

  return (
    <div className="space-y-4">
      <Markdown text={workflow.try_it} />
      {workflow.run_now && (
        <Button onClick={() => runNow.mutate()} disabled={!active || runNow.isPending}>
          {runNow.isPending ? 'Starting…' : 'Run now'}
        </Button>
      )}
      <ErrorNote error={error ?? runs.error} />
      {active && (
        <div>
          <h3 className="text-sm font-semibold">Results</h3>
          {runs.data && runs.data.length === 0 && <p className="mt-1 text-sm text-slate-500">No runs yet.</p>}
          <ul className="mt-2 space-y-2" data-testid="runs">
            {runs.data?.map((run) => (
              <li key={run.id} className="rounded-md bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-200">
                <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span>{shortTime(run.started_at)}</span>
                  <span
                    className={
                      run.status === 'success'
                        ? 'text-emerald-700'
                        : run.status === 'error'
                          ? 'text-red-700'
                          : 'text-blue-700'
                    }
                  >
                    {run.status}
                  </span>
                </div>
                {run.summary && <p className="mt-1 whitespace-pre-wrap text-slate-800">{run.summary}</p>}
                {run.error && <p className="mt-1 text-red-700">{run.error}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
