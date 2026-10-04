import { api } from './api'

/**
 * Open Nango's Connect UI for one connector and save the resulting connection.
 * Resolves true once the connection is stored, false if the user closed the dialog first.
 */
export async function connectWithNango(connector: string): Promise<boolean> {
  // Loaded on demand: most visits never open the dialog.
  const [{ default: Nango }, session] = await Promise.all([
    import('@nangohq/frontend'),
    api.startSession(connector),
  ])
  return new Promise((resolve, reject) => {
    let settled = false
    let saving = false
    const finish = (fn: () => void) => {
      if (!settled) {
        settled = true
        fn()
      }
    }
    const ui = new Nango().openConnectUI({
      // The server says where Nango lives (NANGO_HOST), so a self-hosted Nango works too.
      apiURL: session.api_url,
      baseURL: session.connect_url,
      sessionToken: session.token,
      onEvent: async (event) => {
        if (event.type === 'connect') {
          saving = true
          try {
            await api.completeSession(connector, event.payload.connectionId)
            finish(() => resolve(true))
          } catch (err) {
            ui.close()
            finish(() => reject(err))
          }
        } else if (event.type === 'close' && !saving) {
          finish(() => resolve(false))
        }
      },
    })
  })
}
