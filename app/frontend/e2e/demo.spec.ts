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

  await page.locator('input[name="slack_channel"]').fill('general')
  await page.getByRole('button', { name: 'Deploy', exact: true }).click()
  await expect(page.getByText('must be a Slack channel ID')).toBeVisible()

  await page.locator('input[name="slack_channel"]').fill('C0123ABCD')
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
  for (const connector of ['slack', 'meegle_user_key']) {
    await page.getByTestId(`connector-${connector}`).getByRole('button', { name: /Connect/ }).click()
  }
  await page.getByRole('button', { name: 'Activate for me' }).click()
  await expect(page.getByTestId('status')).toHaveText('Active')
  await expect(page.getByRole('button', { name: 'Run now' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Deactivate' }).click()
  await expect(page.getByTestId('status')).toHaveText('Stopped')
})

test('admin sees users and deployments', async ({ page }) => {
  await signIn(page, 'e2e-dave')
  await page.goto('/admin')
  await page.getByPlaceholder('Admin passcode').fill('e2e-admin')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('admin-users')).toContainText('e2e-dave')
})
