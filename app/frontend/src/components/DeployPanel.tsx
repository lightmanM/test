import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError, BUSY, type WorkflowDetail } from '../api'
import { shortTime, timeLeft } from '../format'
import { Button, ErrorNote, StatusBadge } from './ui'

const POPUP_NAME = 'wd-platform-popup'
const POPUP_FEATURES = 'width=640,height=760'

export function DeployPanel({
  workflow,
  settings,
  onFieldErrors,
}: {
  workflow: WorkflowDetail
  settings: () => Record<string, unknown>
  onFieldErrors: (errors: Record<string, string>) => void
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const popup = useRef<Window | null>(null)
  const popupNavigated = useRef(false)
  const dep = workflow.deployment
  const status = dep?.status
  const busy = !!status && BUSY.includes(status)
  const deployed = !!status && status !== 'stopped'
  const shared = workflow.shared_deployment
  const refresh = () => queryClient.invalidateQueries()

  // Make's popup: opened on click (so browsers allow it), pointed at the URL once the deploy job has it.
  useEffect(() => {
    const win = popup.current
    if (status === 'awaiting_user' && dep?.popup_url && win && !win.closed && !popupNavigated.current) {
      popupNavigated.current = true
      win.location.href = dep.popup_url
    }
  }, [status, dep?.popup_url])

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin === window.location.origin && event.data?.type === 'wd:user-step') refresh()
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  })

  const deploy = async () => {
    setError(null)
    onFieldErrors({})
    if (workflow.platform === 'make') {
      popupNavigated.current = false
      popup.current = window.open('about:blank', POPUP_NAME, POPUP_FEATURES)
      popup.current?.document.write('<p style="font-family:system-ui;margin:3rem">Preparing Make…</p>')
    }
    setSubmitting(true)
    try {
      await api.deploy(workflow.id, settings())
    } catch (err) {
      popup.current?.close()
      if (err instanceof ApiError) onFieldErrors(err.fields)
      setError(err)
    } finally {
      setSubmitting(false)
      refresh()
    }
  }

  const remove = async () => {
    setError(null)
    try {
      await api.undeploy(workflow.id)
    } catch (err) {
      setError(err)
    } finally {
      refresh()
    }
  }

  const deployLabel = shared ? (deployed ? 'Update activation' : 'Activate for me') : deployed ? 'Redeploy' : 'Deploy'
  const blockedReason = !workflow.available
    ? workflow.unavailable_reason ?? 'Deploy unavailable'
    : !workflow.ready
      ? 'Connect the accounts above first'
      : null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={status} />
        {status === 'active' && <span className="text-xs text-slate-500">{timeLeft(dep?.expires_at ?? null)}</span>}
      </div>
      {dep?.error && <ErrorNote error={dep.error} />}
      {status === 'awaiting_user' && dep?.popup_url && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
          Finish connecting your accounts in Make's popup.{' '}
          <button
            className="font-medium underline"
            onClick={() => {
              popupNavigated.current = true
              popup.current = window.open(dep.popup_url!, POPUP_NAME, POPUP_FEATURES)
            }}
          >
            Open it again
          </button>
        </p>
      )}
      {blockedReason && <p className="text-sm text-slate-600">{blockedReason}</p>}
      <ErrorNote error={error} />
      <div className="flex flex-wrap gap-2">
        <Button onClick={deploy} disabled={!!blockedReason || busy || submitting}>
          {submitting ? 'Starting…' : deployLabel}
        </Button>
        {deployed && (
          <Button variant="danger" onClick={remove} disabled={busy || submitting}>
            {shared ? 'Deactivate' : 'Delete'}
          </Button>
        )}
      </div>
      {dep && dep.events.length > 0 && (
        <details className="text-sm" open={busy || status === 'failed'}>
          <summary className="cursor-pointer text-slate-600">Timeline</summary>
          <ol className="mt-2 space-y-1 border-l border-slate-200 pl-4" data-testid="timeline">
            {dep.events
              .slice()
              .reverse()
              .map((e, i) => (
                <li key={i} className="text-slate-700">
                  <span className="text-xs text-slate-500">{shortTime(e.at)}</span> · {e.message}
                </li>
              ))}
          </ol>
        </details>
      )}
    </div>
  )
}
