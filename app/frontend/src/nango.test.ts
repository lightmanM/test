import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'
import { connectWithNango } from './nango'

type OnEvent = (event: { type: string; payload?: unknown }) => Promise<void> | void

const ui = vi.hoisted(() => ({
  onEvent: null as OnEvent | null,
  props: null as Record<string, unknown> | null,
  close: vi.fn(),
}))

vi.mock('@nangohq/frontend', () => ({
  default: class {
    openConnectUI({ onEvent, ...props }: { onEvent: OnEvent }) {
      ui.onEvent = onEvent
      ui.props = props
      return { close: ui.close }
    }
  },
}))

const opened = () => vi.waitFor(() => expect(ui.onEvent).not.toBeNull())

beforeEach(() => {
  vi.restoreAllMocks()
  ui.onEvent = null
  ui.props = null
  ui.close.mockReset()
  vi.spyOn(api, 'startSession').mockResolvedValue({
    token: 'tok',
    expires_at: '',
    integration: 'slack',
    api_url: 'https://nango.example',
    connect_url: 'https://connect.nango.example',
  })
})

describe('connectWithNango', () => {
  it('saves the connection Nango reports', async () => {
    const complete = vi.spyOn(api, 'completeSession').mockResolvedValue({})
    const result = connectWithNango('slack')
    await opened()
    expect(ui.props).toEqual({
      sessionToken: 'tok',
      apiURL: 'https://nango.example',
      baseURL: 'https://connect.nango.example',
    })
    await ui.onEvent!({ type: 'connect', payload: { providerConfigKey: 'slack', connectionId: 'conn-1' } })
    await ui.onEvent!({ type: 'close' })
    await expect(result).resolves.toBe(true)
    expect(complete).toHaveBeenCalledWith('slack', 'conn-1')
  })

  it('resolves false when the dialog is closed', async () => {
    const result = connectWithNango('slack')
    await opened()
    await ui.onEvent!({ type: 'close' })
    await expect(result).resolves.toBe(false)
  })

  it('ignores a close while the connection is being saved', async () => {
    let finishSave: (v: unknown) => void = () => {}
    vi.spyOn(api, 'completeSession').mockReturnValue(new Promise((r) => (finishSave = r)))
    const result = connectWithNango('slack')
    await opened()
    const saving = ui.onEvent!({ type: 'connect', payload: { connectionId: 'conn-2' } })
    await ui.onEvent!({ type: 'close' })
    finishSave({})
    await saving
    await expect(result).resolves.toBe(true)
  })

  it('rejects without opening the dialog when the session cannot start', async () => {
    vi.spyOn(api, 'startSession').mockRejectedValue(new Error('Nango is down'))
    await expect(connectWithNango('slack')).rejects.toThrow('Nango is down')
    expect(ui.onEvent).toBeNull()
  })

  it('rejects when saving fails', async () => {
    vi.spyOn(api, 'completeSession').mockRejectedValue(new Error('belongs to someone else'))
    const result = connectWithNango('slack')
    await opened()
    await ui.onEvent!({ type: 'connect', payload: { connectionId: 'conn-3' } })
    await expect(result).rejects.toThrow('belongs to someone else')
    expect(ui.close).toHaveBeenCalled()
  })
})
