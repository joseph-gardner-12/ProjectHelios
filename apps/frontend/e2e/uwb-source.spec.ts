import { expect, test } from '@playwright/test'

test('source toggle changes runtime request and clears coordinates from the previous source', async ({ page }) => {
  await page.route('**/api/v1/session/', route => route.fulfill({ json: {
    authenticated: true, email: 'test@clemson.edu', csrf_token: 'test',
  } }))
  await page.route('**/api/v1/devices/', route => route.fulfill({ json: {
    devices: [{ id: 'sim', name: 'Simulator' }, { id: 'real', name: 'Collector' }],
  } }))
  let mode = 'simulated'
  await page.route('**/api/v1/local/uwb-source/', route => {
    if (route.request().method() === 'POST') mode = route.request().postDataJSON().mode
    return route.fulfill({ json: { enabled: true, mode, devices: { real: 'real', simulated: 'sim' } } })
  })
  const base = {
    version: 1, type: 'snapshot', connection_id: 'test', timestamp: new Date().toISOString(),
    revision: 1, sequence: 1, command: null, can_send: false,
    queue: { position: null, joined: false, controller: false, lease_id: null, expires_at: null, releasing: false },
  }
  await page.routeWebSocket('**/ws/v1/devices/sim/', socket => socket.send(JSON.stringify({
    ...base, device_id: 'sim', frame_version: 'dummy-enu-v1', source: 'dummy', capability: 'dummy',
    health: 'fresh', position: { x: 1.524, y: 1.524, z: 1.524 }, position_at: Date.now() / 1000,
  })))
  await page.routeWebSocket('**/ws/v1/devices/real/', socket => socket.send(JSON.stringify({
    ...base, device_id: 'real', frame_version: 'table-bench-enu-v1', source: 'uwb', capability: 'measurement',
    health: 'offline', position: null, position_at: null, observation: null,
  })))
  await page.goto('/control')
  await expect(page.locator('.position-readout')).toContainText('5.0, 5.0, 5.0 ft')
  await page.getByRole('button', { name: 'Real UWB · COM5' }).click()
  await expect(page.getByRole('button', { name: 'Real UWB · COM5' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.position-readout')).toContainText('Unavailable')
  await expect(page.getByRole('button', { name: 'Send target' })).toBeDisabled()
  expect(mode).toBe('real')
  await page.getByRole('button', { name: 'Simulated UWB', exact: true }).click()
  await expect(page.locator('.position-readout')).toContainText('5.0, 5.0, 5.0 ft')
  expect(mode).toBe('simulated')
})
