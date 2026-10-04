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
  disconnect: (connector: string) => request<void>('DELETE', `/api/connections/${connector}`),
  deploy: (id: string, settings: Record<string, unknown>) =>
    request<Deployment>('POST', `/api/deployments/${id}`, { settings }),
  undeploy: (id: string) => request<Deployment>('DELETE', `/api/deployments/${id}`),
  runNow: (id: string) => request<{ run_id: string | null; message: string }>('POST', `/api/deployments/${id}/run`),
  runs: (id: string) => request<Run[]>('GET', `/api/deployments/${id}/runs`),
  adminLogin: (passcode: string) => request<void>('POST', '/api/admin/login', { passcode }),
  adminLogout: () => request<void>('POST', '/api/admin/logout'),
  adminOverview: () => request<AdminOverview>('GET', '/api/admin/overview'),
}

export const BUSY: DeploymentStatus[] = ['deploying', 'redeploying', 'stopping']
