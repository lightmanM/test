import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, BUSY, isTransitional, type WorkflowDetail } from '../api'
import { ConnectStep } from '../components/ConnectStep'
import { DeployPanel } from '../components/DeployPanel'
import { RunsPanel } from '../components/RunsPanel'
import { SettingsForm } from '../components/SettingsForm'
import { ErrorNote, PlatformBadge, Section } from '../components/ui'
import { formValue, settingsFromForm } from '../format'

export function WorkflowPage() {
  const { id = '' } = useParams()
  const workflow = useQuery({
    queryKey: ['workflow', id],
    queryFn: () => api.workflow(id),
    refetchInterval: (q) => (isTransitional(q.state.data?.deployment?.status) ? 1500 : false),
  })
  if (workflow.error) return <ErrorNote error={workflow.error} />
  if (!workflow.data) return <p className="text-sm text-slate-500">Loading…</p>
  return <WorkflowView workflow={workflow.data} />
}

function WorkflowView({ workflow }: { workflow: WorkflowDetail }) {
  const initial = () =>
    Object.fromEntries(
      workflow.settings.map((s) => [s.key, formValue(workflow.deployment?.settings?.[s.key] ?? s.default, s.type)]),
    )
  const [values, setValues] = useState<Record<string, string>>(initial)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  // Reset the form when the saved settings change (e.g. after a redeploy elsewhere).
  const savedKey = JSON.stringify(workflow.deployment?.settings ?? null)
  useEffect(() => setValues(initial()), [savedKey])

  const status = workflow.deployment?.status
  const busy = !!status && BUSY.includes(status)

  return (
    <div className="space-y-5">
      <div>
        <Link to="/" className="text-sm text-indigo-600 hover:underline">
          ← All workflows
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">{workflow.name}</h1>
          <PlatformBadge platform={workflow.platform} />
        </div>
        <p className="mt-2 max-w-3xl whitespace-pre-line text-sm text-slate-600">{workflow.description}</p>
      </div>
      <Section step={1} title="Connect accounts">
        <ConnectStep workflow={workflow} />
      </Section>
      <Section step={2} title="Settings">
        <SettingsForm
          settings={workflow.settings}
          values={values}
          errors={fieldErrors}
          disabled={busy}
          slackConnected={workflow.connectors.some((c) => c.id === 'slack' && c.connected)}
          onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))}
        />
      </Section>
      <Section step={3} title={workflow.shared_deployment ? 'Activate' : 'Deploy'}>
        <DeployPanel
          workflow={workflow}
          settings={() => settingsFromForm(values, workflow.settings)}
          onFieldErrors={setFieldErrors}
        />
      </Section>
      <Section step={4} title="Try it">
        <RunsPanel workflow={workflow} />
      </Section>
    </div>
  )
}
