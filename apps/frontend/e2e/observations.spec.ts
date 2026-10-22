import { expect, test } from '@playwright/test'

// Isolated display test: no aircraft, cloud account, Redis, or database required.
test.use({ baseURL: process.env.HELIOS_UI_TEST_URL ?? 'http://127.0.0.1:5173' })

test('signed measured/predicted/invalid observations stay read only on desktop and mobile', async ({ page }) => {
  await page.route('**/api/v1/session/', route => route.fulfill({ json: {
    authenticated: true, email: 'observer@clemson.edu', csrf_token: 'test',
  } }))
  await page.route('**/api/v1/devices/', route => route.fulfill({ json: {
    devices: [{ id: 'measured', name: 'Surveyed room' }],
  } }))
  const at = new Date().toISOString()
  const observation = {
    kind: 'measured', session: 'test:fc:1', estimated_time: at, measurement_time: at,
    prediction_age_s: 0, position: { x: -1.25, y: 2, z: .75 },
    covariance: [[.01, 0, 0], [0, .01, 0], [0, 0, .02]], timing_sigma_s: .001, reason: null,
  }
  const snapshot = {
    version: 1, type: 'snapshot', device_id: 'measured', connection_id: 'test', name: 'Surveyed room',
    frame_version: 'room-enu-v1', timestamp: at, revision: 1, sequence: 1, health: 'fresh',
    position: observation.position, position_at: Date.parse(at) / 1000,
    source: 'uwb', capability: 'measurement', observation, command: null, can_send: false,
    queue: { position: null, joined: false, controller: false, lease_id: null, expires_at: null, releasing: false },
  }
  let send: ((value: object) => void) | undefined
  await page.routeWebSocket('**/ws/v1/devices/measured/', socket => {
    send = value => socket.send(JSON.stringify(value))
    send(snapshot)
  })
  await page.goto('/control')
  await expect(page.getByRole('heading', { name: 'Localization observations' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Flight space', exact: true })).toBeVisible()
  await expect(page.locator('.drone-marker')).toBeVisible()
  await expect(page.locator('.target-marker')).toBeVisible()
  await expect(page.locator('.observation-coordinates')).toContainText('-1.250 m')
  await expect(page.getByRole('button', { name: 'Rejoin queue' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Send target' })).toBeDisabled()
  send!({ ...snapshot, sequence: 2, observation: { ...observation, kind: 'predicted',
    estimated_time: new Date(Date.parse(at) + 50).toISOString(), prediction_age_s: .05 } })
  await expect(page.locator('.observation-panel [role=status]')).toContainText('Predicted')
  await expect(page.locator('.observation-panel [role=status]')).toContainText('Stale')
  send!({ ...snapshot, sequence: 3, health: 'stale', observation: { ...observation,
    kind: 'invalid', position: null, covariance: null, reason: 'altitude_stale' } })
  await expect(page.locator('.observation-panel [role=status]')).toContainText('Invalid')
  await expect(page.locator('.observation-panel')).toContainText('altitude stale')
  await page.screenshot({ path: '/tmp/helios-observations-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.observation-coordinates')).toContainText('-1.250 m')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '/tmp/helios-observations-mobile.png', fullPage: true })
})
