import { defineConfig } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// Runs the real backend in fake-platform mode, serving the built frontend (npm run build first).
const port = 8765
const database = join(tmpdir(), `workflow-demo-e2e-${Date.now()}.db`)

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  fullyParallel: false,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    // Local sandboxes may provide a preinstalled Chromium; CI runs `playwright install chromium`.
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `${process.env.PYTHON ?? 'python'} -m workflow_demo`,
    cwd: '../backend',
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      PORT: String(port),
      DEMO_PASSCODE: 'e2e-pass',
      ADMIN_PASSCODE: 'e2e-admin',
      SESSION_SECRET: 'e2e-secret',
      DEMO_FAKE_PLATFORMS: '1',
      COOKIE_SECURE: 'false',
      DATABASE_URL: `sqlite:///${database}`,
      PUBLIC_BASE_URL: `http://127.0.0.1:${port}`,
    },
  },
})
