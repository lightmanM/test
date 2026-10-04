import { expect, type Page, test } from '@playwright/test'

async function signIn(page: Page, username: string) {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Passcode').fill('e2e-pass')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('username')).toHaveText(username)
}

test('sign in, connect, deploy, run, redeploy, delete', async ({ page }) => {
  await signIn(page, 'e2e-alice')
  await expect(page.locator('[data-testid^="card-"]')).toHaveCount(5)

  await page.getByTestId('card-uptime-monitor').click()
  await expect(page.getByRole('button', { name: 'Deploy', exact: true })).toBeDisabled()
  for (const connector of ['google', 'slack']) {
    await page.getByTestId(`connector-${connector}`).getByRole('button', { name: /Connect/ }).click()
    await expect(page.getByTestId(`connector-${connector}`)).toContainText('Connected')
  }

  // Slack is connected, so the channel is picked from a list.
  await page.locator('select[name="slack_channel"]').selectOption({ label: '#demo-alerts' })
  const sites = page.locator('textarea[name="sites"]')
  const defaultSites = await sites.inputValue()
  await sites.fill('not a url')
  await page.getByRole('button', { name: 'Deploy', exact: true }).click()
  await expect(page.getByText('every entry must be an http(s) URL')).toBeVisible()

  await sites.fill(defaultSites)
  await page.getByRole('button', { name: 'Deploy', exact: true }).click()
  await expect(page.getByTestId('status')).toHaveText('Active')

  await page.getByRole('button', { name: 'Run now' }).click()
  await expect(page.getByTestId('runs')).toContainText('DOWN')

  await page.getByRole('button', { name: 'Redeploy' }).click()
  await expect(page.getByTestId('timeline')).toContainText('Removed the previous deployment')
  await expect(page.getByTestId('status')).toHaveText('Active')

  await page.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByTestId('status')).toHaveText('Stopped')

  await page.getByRole('link', { name: '← All workflows' }).click()
  await expect(page.getByTestId('card-uptime-monitor')).toContainText('Stopped')
})

test('Make workflow deploys through the platform popup', async ({ page, context }) => {
  await signIn(page, 'e2e-bob')
  await page.getByTestId('card-github-merge-slack').click()
  await expect(page.getByTestId('connector-make_github')).toContainText("Make's popup")

  const popupOpened = context.waitForEvent('page')
  await page.getByRole('button', { name: 'Deploy', exact: true }).click()
  const popup = await popupOpened
  await popup.getByRole('link', { name: /finish/ }).click()
  await expect(popup.getByText('All set')).toBeVisible()
  await expect(page.getByTestId('status')).toHaveText('Active')
})

test('shared bot is activated per user', async ({ page }) => {
  await signIn(page, 'e2e-carol')
  await page.getByTestId('card-slack-meegle-bot').click()
  await page.getByTestId('connector-slack').getByRole('button', { name: /Connect/ }).click()
  const userKey = page.getByTestId('connector-meegle_user_key')
  await userKey.locator('input[name="meegle_user_key"]').fill('carol_key')
  await userKey.getByRole('button', { name: 'Save' }).click()
  await expect(userKey).toContainText('Connected')
  await expect(userKey).toContainText('carol_key')
  await page.getByRole('button', { name: 'Activate for me' }).click()
  await expect(page.getByTestId('status')).toHaveText('Active')
  await expect(page.getByRole('button', { name: 'Run now' })).toHaveCount(0)

  // The bot (on Modal) looks the tester up and reports the card it created.
  const connections: { connector: string; details: { slack_user_id?: string } }[] = await (
    await page.request.get('/api/connections')
  ).json()
  const slackUserId = connections.find((c) => c.connector === 'slack')?.details.slack_user_id
  const bot = { Authorization: 'Bearer e2e-bot-token' }
  const lookup = await page.request.get(`/api/bot/user-map/${slackUserId}`, { headers: bot })
  expect(await lookup.json()).toEqual({ user_key: 'carol_key' })
  const card = await page.request.post('/api/bot/cards', {
    headers: bot,
    data: { slack_user_id: slackUserId, title: 'Fix login page error', url: 'https://meegle.com/demo/story/1' },
  })
  expect(await card.json()).toEqual({ recorded: true })
  await page.reload()
  await expect(page.getByTestId('runs')).toContainText('Created card “Fix login page error”')
  await page.getByRole('button', { name: 'Deactivate' }).click()
  await expect(page.getByTestId('status')).toHaveText('Stopped')
})

test('Meegle token is saved encrypted and never shown again', async ({ page }) => {
  await signIn(page, 'e2e-erin')
  await page.getByTestId('card-meegle-daily-digest').click()
  const token = page.getByTestId('connector-meegle_mcp_token')
  const input = token.locator('input[name="meegle_mcp_token"]')
  await expect(input).toHaveAttribute('type', 'password')

  await input.fill('short')
  await token.getByRole('button', { name: 'Save' }).click()
  await expect(token).toContainText('Paste the whole token')

  await input.fill('mcp-token-abcdef-9876')
  await token.getByRole('button', { name: 'Save' }).click()
  await expect(token).toContainText('Connected')
  await expect(token).toContainText('saved · ends with 9876')
  await expect(input).toHaveCount(0)
  await expect(page.getByText('mcp-token-abcdef-9876')).toHaveCount(0)

  await token.getByRole('button', { name: 'Change' }).click()
  await expect(input).toHaveValue('')
  await token.getByRole('button', { name: 'Cancel' }).click()
  await token.getByRole('button', { name: 'Remove' }).click()
  await expect(input).toBeVisible()
  await expect(token).not.toContainText('Connected')
})

test('admin sees users and deployments', async ({ page }) => {
  await signIn(page, 'e2e-dave')
  await page.goto('/admin')
  await page.getByPlaceholder('Admin passcode').fill('e2e-admin')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('admin-users')).toContainText('e2e-dave')
})
