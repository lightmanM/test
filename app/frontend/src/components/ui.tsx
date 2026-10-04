import type { ReactNode } from 'react'
import type { DeploymentStatus, Platform } from '../api'
import { inlineMarkdown } from '../format'

export function Button({
  children,
  onClick,
  disabled,
  variant = 'primary',
  type = 'button',
  title,
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'secondary' | 'danger'
  type?: 'button' | 'submit'
  title?: string
}) {
  const styles = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-300',
    secondary: 'bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:text-slate-400',
    danger: 'bg-white text-red-700 ring-1 ring-red-300 hover:bg-red-50 disabled:text-red-300',
  }[variant]
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium shadow-sm transition disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  )
}

const STATUS: Record<DeploymentStatus | 'not_deployed', { label: string; style: string }> = {
  not_deployed: { label: 'Not deployed', style: 'bg-slate-100 text-slate-600' },
  deploying: { label: 'Deploying…', style: 'bg-blue-100 text-blue-800 animate-pulse' },
  redeploying: { label: 'Redeploying…', style: 'bg-blue-100 text-blue-800 animate-pulse' },
  stopping: { label: 'Stopping…', style: 'bg-blue-100 text-blue-800 animate-pulse' },
  awaiting_user: { label: 'Waiting for you', style: 'bg-amber-100 text-amber-800' },
  active: { label: 'Active', style: 'bg-emerald-100 text-emerald-800' },
  failed: { label: 'Failed', style: 'bg-red-100 text-red-800' },
  stopped: { label: 'Stopped', style: 'bg-slate-100 text-slate-600' },
}

export function StatusBadge({ status }: { status: DeploymentStatus | null | undefined }) {
  const s = STATUS[status ?? 'not_deployed']
  return (
    <span data-testid="status" className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${s.style}`}>
      {s.label}
    </span>
  )
}

const PLATFORM: Record<Platform, { label: string; style: string }> = {
  n8n: { label: 'n8n', style: 'bg-rose-50 text-rose-700 ring-rose-200' },
  make: { label: 'Make', style: 'bg-violet-50 text-violet-700 ring-violet-200' },
  modal: { label: 'Modal', style: 'bg-lime-50 text-lime-800 ring-lime-200' },
}

export function PlatformBadge({ platform }: { platform: Platform }) {
  const p = PLATFORM[platform]
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ring-1 ${p.style}`}>{p.label}</span>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 ${className}`}>{children}</div>
}

export function Section({ step, title, children }: { step: number; title: string; children: ReactNode }) {
  return (
    <Card>
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600 text-xs text-white">
          {step}
        </span>
        {title}
      </h2>
      {children}
    </Card>
  )
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-sm leading-6 text-slate-700">
      {text
        .trim()
        .split(/\n\s*\n/)
        .map((paragraph, i) => (
          <p key={i}>
            {inlineMarkdown(paragraph.replace(/\s*\n\s*/g, ' ')).map((seg, j) =>
              seg.bold ? (
                <strong key={j}>{seg.text}</strong>
              ) : seg.code ? (
                <code key={j} className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]">
                  {seg.text}
                </code>
              ) : (
                <span key={j}>{seg.text}</span>
              ),
            )}
          </p>
        ))}
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : String(error)
  return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">{message}</p>
}
