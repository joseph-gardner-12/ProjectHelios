import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { once } from 'node:events'
import { resolve } from 'node:path'
import { writeFile, mkdir } from 'node:fs/promises'

const root = resolve(import.meta.dirname, '../../..')
const runtime = () => spawn(resolve(root, 'apps/localization/.venv/bin/helios-localization'), ['simulate'], {
  env: process.env, stdio: 'ignore',
})
async function stop(process: ChildProcess) {
  if (process.exitCode === null && process.signalCode === null) {
    process.kill('SIGTERM'); await once(process, 'exit')
  }
}
async function login(page: Page, name: string) {
  await page.goto('/control')
  await page.getByLabel('Clemson email').fill(`${name}-${process.env.HELIOS_E2E_RUN}@clemson.edu`)
  await page.getByLabel('Demo password').fill(process.env.HELIOS_E2E_PASSWORD!)
  await page.getByRole('button', { name: 'Join queue', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

test('two users, acknowledgment, live positions, queue handoff and idle reconnect', async ({ browser }) => {
  test.skip(!process.env.HELIOS_DEVICE_ID, 'Run scripts/control-e2e.py with disposable PostgreSQL/Redis')
  let client = runtime()
  let restartedBackend: ChildProcess | undefined
  const first = await browser.newContext()
  const second = await browser.newContext()
  const controller = await first.newPage()
  const observer = await second.newPage()
  const commands: unknown[] = []
  controller.on('response', async response => {
    if (response.url().endsWith('/targets/') && response.status() === 202) commands.push(await response.json())
  })
  try {
    await login(controller, 'first')
    await expect(controller.getByRole('button', { name: 'Send target', exact: true })).toBeEnabled()
    await login(observer, 'second')
    await expect(observer.getByText('Waiting · Queue position 1')).toBeVisible()
    await expect(observer.getByRole('button', { name: 'Send target', exact: true })).toBeDisabled()
    await controller.getByLabel('Target X in feet').fill('1')
    await controller.getByLabel('Target Y in feet').fill('1')
    await controller.getByLabel('Target Z in feet').fill('1')
    // Lose the HTTP response after the server has persisted and dispatched the command.
    await controller.route('**/targets/', async route => {
      const response = await route.fetch()
      commands.push(await response.json())
      await route.abort('failed')
    }, { times: 1 })
    await controller.getByRole('button', { name: 'Send target', exact: true }).click()
    await expect(controller.getByRole('button', { name: 'Resolve submission' })).toBeVisible()
    await controller.getByRole('button', { name: 'Resolve submission' }).click()
    await expect(controller.getByRole('status', { name: 'Command status' })).toContainText('Accepted')
    await expect(controller.getByRole('status', { name: 'Command status' })).toContainText('Arrived', { timeout: 15000 })
    await expect(observer.locator('.position-readout output')).toHaveText('1.0, 1.0, 1.0 ft')
    await controller.getByRole('button', { name: 'Reset', exact: true }).click()
    await expect(controller.getByLabel('Target X in feet')).toHaveValue('5')
    await expect(controller.locator('.position-readout output')).toHaveText('1.0, 1.0, 1.0 ft')
    // Keyboard target adjustment remains available to observers.
    await observer.getByRole('button', { name: /Target XY plane/ }).press('ArrowRight')
    await expect(observer.getByLabel('Target X in feet')).toHaveValue('5.5')
    await controller.getByRole('button', { name: 'Send target', exact: true }).click()
    await expect(controller.getByRole('status', { name: 'Command status' })).toContainText('Accepted')
    await stop(client)
    await expect(controller.getByRole('button', { name: 'Send target', exact: true })).toBeDisabled()
    await expect(controller.locator('.position-readout')).toContainText('Stale')
    await expect(controller.getByRole('status', { name: 'Command status' })).toContainText('Interrupted')
    client = runtime()
    await expect(controller.getByRole('button', { name: 'Send target', exact: true })).toBeEnabled({ timeout: 15000 })
    await expect(controller.locator('.position-readout output')).toHaveText('0.0, 0.0, 0.0 ft')
    await controller.getByRole('button', { name: 'Leave / release turn' }).click()
    await expect(observer.getByRole('button', { name: 'Send target', exact: true })).toBeEnabled()
    await expect(controller.getByRole('button', { name: 'Send target', exact: true })).toBeDisabled()
    // Restart the actual backend while the same localization process is moving.
    await observer.getByRole('button', { name: 'Send target', exact: true }).click()
    await expect(observer.getByRole('status', { name: 'Command status' })).toContainText('Accepted')
    process.kill(Number(process.env.HELIOS_E2E_BACKEND_PID), 'SIGTERM')
    await expect(observer.getByRole('button', { name: 'Send target', exact: true })).toBeDisabled()
    restartedBackend = spawn(resolve(root, 'apps/backend/.venv/bin/daphne'),
      ['-b', '127.0.0.1', '-p', '18000', 'config.asgi:application'],
      { cwd: resolve(root, 'apps/backend'), env: process.env, stdio: 'ignore' })
    await expect(observer.getByRole('button', { name: 'Send target', exact: true })).toBeEnabled({ timeout: 20000 })
    await expect(observer.getByRole('status', { name: 'Command status' })).toContainText('Interrupted')
    const heldPosition = await observer.locator('.position-readout output').textContent()
    // Wait for five fresh live frames before checking the position remains stationary.
    await observer.evaluate(device => new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(`ws://127.0.0.1:5173/ws/v1/devices/${device}/`)
      let frames = 0
      let sequence = -1
      const timeout = setTimeout(() => { socket.close(); reject(new Error('No fresh frames')) }, 5000)
      socket.onmessage = event => {
        const state = JSON.parse(event.data)
        if (state.health === 'fresh' && state.sequence > sequence) { sequence = state.sequence; frames++ }
        if (frames >= 5) { clearTimeout(timeout); socket.close(); resolve() }
      }
    }), process.env.HELIOS_DEVICE_ID!)
    await expect(observer.locator('.position-readout output')).toHaveText(heldPosition!)
    await mkdir(resolve(root, 'output'), { recursive: true })
    await controller.screenshot({ path: resolve(root, 'output/control-desktop.png'), fullPage: true })
    await observer.setViewportSize({ width: 390, height: 844 })
    await observer.screenshot({ path: resolve(root, 'output/control-mobile.png'), fullPage: true })
    await writeFile(resolve(root, 'output/control-command-evidence.json'), JSON.stringify(commands, null, 2))
  } finally {
    await stop(client)
    if (restartedBackend) await stop(restartedBackend)
    await first.close(); await second.close()
  }
})
