// Typed client for the demo backend (app/backend/workflow_demo/api).

export type Platform = 'n8n' | 'make' | 'modal'
export type DeploymentStatus =
  | 'deploying'
  | 'awaiting_user'
  | 'active'
  | 'failed'
  | 'redeploying'
  | 'stopping'
  | 'stopped'

export interface Me {
  username: string
}

export interface ConnectorStatus {
  id: string
  name: string
  kind: 'nango' | 'manual' | 'platform_popup'
  description: string
  purpose: string
  help: string | null
  connected: boolean
  /** What's connected, e.g. a Slack workspace, Google email or "saved · ends with 1234" (never a secret). */
  label: string | null
  secret: boolean
  managed_by_platform: boolean
}

export interface Setting {
  key: string
  label: string
  type: 'string' | 'number' | 'select' | 'url_list' | 'slack_channel'
  required: boolean
  default: unknown
  help: string | null
  options: unknown[] | null
}

export interface DeploymentEvent {
  at: string
  type: string
  message: string
}

export interface Deployment {
  workflow_id: string
  status: DeploymentStatus
  settings: Record<string, unknown>
  error: string | null
  deployed_at: string | null
  expires_at: string | null
  popup_url: string | null
  links: { label: string; url: string }[]
  updated_at: string
  events: DeploymentEvent[]
}

export interface WorkflowSummary {
  id: string
  name: string
  summary: string
  platform: Platform
  available: boolean
  unavailable_reason: string | null
  ready: boolean
  connectors: ConnectorStatus[]
  deployment: Deployment | null
}

export interface WorkflowDetail extends WorkflowSummary {
  description: string
  settings: Setting[]
  try_it: string
  run_now: boolean
  shared_deployment: boolean
}

export interface Run {
  id: string
  status: string
  started_at: string | null
  finished_at: string | null
  summary: string | null
  error: string | null
}

export interface Health {
  status: string
  fake_platforms: boolean
  nango_enabled: boolean
}

export interface ConnectSession {
  token: string
  expires_at: string
  integration: string
  api_url: string
  connect_url: string
}

export interface SlackChannel {
  id: string
  name: string
}

export interface AdminOverview {
  max_users: number
  fake_platforms: boolean
  users: {
    username: string
    created_at: string
    last_login_at: string
    connections: string[]
    deployments: { workflow_id: string; status: DeploymentStatus; expires_at: string | null; error: string | null }[]
  }[]
}

export interface SetupCheck {
  checks: { name: string; state: 'ok' | 'missing' | 'error' | 'info'; detail: string }[]
  workflows: { id: string; name: string; platform: Platform; available: boolean; reason: string | null }[]
}

export interface SweepReport {
  stopped: string[]
  recovered_jobs: number
  orphans_removed: string[]
  errors: string[]
  orphan_sweep: boolean
}

/** Refetch everything after a change that affects several views (connections, deployments). */
export function refreshAll(queryClient: { invalidateQueries: () => Promise<unknown> }) {
  return queryClient.invalidateQueries()
}

export class ApiError extends Error {
  status: number
  fields: Record<string, string>

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail
          ? String((detail as { message: unknown }).message)
          : `Request failed (${status})`
    super(message)
    this.status = status
    this.fields =
      detail && typeof detail === 'object' && 'fields' in detail
        ? ((detail as { fields: Record<string, string> }).fields ?? {})
        : {}
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText)
  return data as T
}

export const api = {
  health: () => request<Health>('GET', '/api/health'),
  me: () => request<Me>('GET', '/api/me'),
  login: (username: string, passcode: string) => request<Me>('POST', '/api/auth/login', { username, passcode }),
  logout: () => request<void>('POST', '/api/auth/logout'),
  workflows: () => request<WorkflowSummary[]>('GET', '/api/workflows'),
  workflow: (id: string) => request<WorkflowDetail>('GET', `/api/workflows/${id}`),
  fakeConnect: (connector: string) => request<unknown>('POST', `/api/connections/${connector}/fake`),
  startSession: (connector: string) => request<ConnectSession>('POST', `/api/connections/${connector}/session`),
  completeSession: (connector: string, connectionId: string) =>
    request<unknown>('POST', `/api/connections/${connector}/complete`, { connection_id: connectionId }),
  saveSecret: (connector: string, value: string) =>
    request<unknown>('PUT', `/api/connections/${connector}/secret`, { value }),
  slackChannels: () => request<SlackChannel[]>('GET', '/api/slack/channels'),
  disconnect: (connector: string) => request<void>('DELETE', `/api/connections/${connector}`),
  deploy: (id: string, settings: Record<string, unknown>) =>
    request<Deployment>('POST', `/api/deployments/${id}`, { settings }),
  undeploy: (id: string) => request<Deployment>('DELETE', `/api/deployments/${id}`),
  runNow: (id: string) => request<{ run_id: string | null; message: string }>('POST', `/api/deployments/${id}/run`),
  runs: (id: string) => request<Run[]>('GET', `/api/deployments/${id}/runs`),
  adminLogin: (passcode: string) => request<void>('POST', '/api/admin/login', { passcode }),
  adminLogout: () => request<void>('POST', '/api/admin/logout'),
  adminOverview: () => request<AdminOverview>('GET', '/api/admin/overview'),
  adminSetup: () => request<SetupCheck>('GET', '/api/admin/setup'),
  adminSweep: () => request<SweepReport>('POST', '/api/admin/sweep'),
  adminStop: (username: string, workflowId: string) =>
    request<{ status: DeploymentStatus }>(
      'POST',
      `/api/admin/users/${encodeURIComponent(username)}/deployments/${encodeURIComponent(workflowId)}/stop`,
    ),
}

export const BUSY: DeploymentStatus[] = ['deploying', 'redeploying', 'stopping']

/** Statuses that change on their own (a job is running or the user is in a platform popup): poll. */
export function isTransitional(status: DeploymentStatus | null | undefined): boolean {
  return !!status && (BUSY.includes(status) || status === 'awaiting_user')
}
