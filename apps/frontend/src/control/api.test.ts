import messages from '../../../../contracts/control-v1/messages.fixtures.json'
import { describe, expect, it } from 'vitest'
import fixtures from '../../../../contracts/control-v1/coordinates.fixtures.json'
import { isPosition, parseSnapshot, toFeet, toMetres } from './api'

describe('wire coordinates', () => {
  for (const fixture of fixtures) it(fixture.name, () => {
    expect(isPosition(fixture.position)).toBe(fixture.valid)
  })
  it('rejects non-finite numbers', () => {
    expect(isPosition({ x: NaN, y: 0, z: 0 })).toBe(false)
    expect(isPosition({ x: Infinity, y: 0, z: 0 })).toBe(false)
  })
  it('converts only at the boundary without display rounding', () => {
    expect(toMetres({ x: 10, y: 5, z: 0 })).toEqual({ x: 3.048, y: 1.524, z: 0 })
    expect(toFeet(toMetres({ x: 2.5, y: 5, z: 7.5 }))).toEqual({ x: 2.5, y: 5, z: 7.5 })
  })
  it('rejects incomplete live state', () => {
    expect(() => parseSnapshot('{"type":"snapshot","version":1}')).toThrow('Invalid live telemetry')
  })
})

describe('shared browser message fixtures', () => {
  for (const fixture of messages.filter(value => value.direction === 'browser')) {
    it(fixture.name, () => {
      const parse = () => parseSnapshot(JSON.stringify(fixture.message))
      if (fixture.valid) expect(parse).not.toThrow()
      else expect(parse).toThrow()
    })
  }
})

describe('measurement observations', () => {
  const measured = {
    kind: 'measured', session: 'capture:fc:1', estimated_time: '2026-10-21T12:00:00Z',
    measurement_time: '2026-10-21T12:00:00Z', prediction_age_s: 0,
    position: { x: -1, y: 2, z: .5 }, covariance: [[.01, 0, 0], [0, .01, 0], [0, 0, .02]],
    timing_sigma_s: .01, reason: null,
  }
  const snapshot = {
    version: 1, type: 'snapshot', device_id: 'test', connection_id: 'connection',
    frame_version: 'survey-enu-v1', timestamp: '2026-10-21T12:00:00Z', revision: 1, sequence: 1,
    health: 'fresh', position: measured.position, position_at: 1792584000,
    source: 'uwb', capability: 'measurement', observation: measured, command: null, can_send: false,
    queue: { position: null, joined: false, controller: false, lease_id: null, expires_at: null, releasing: false },
  }
  it('accepts signed coordinates with measured source identity', () => {
    expect(parseSnapshot(JSON.stringify(snapshot)).position?.x).toBe(-1)
  })
  it('accepts flagged short predictions', () => {
    expect(parseSnapshot(JSON.stringify({ ...snapshot, observation: { ...measured,
      kind: 'predicted', estimated_time: '2026-10-21T12:00:00.050Z', prediction_age_s: .05 } })).observation?.kind).toBe('predicted')
  })
  it('rejects movement authority and predictions beyond the bound', () => {
    expect(() => parseSnapshot(JSON.stringify({ ...snapshot, can_send: true }))).toThrow()
    expect(() => parseSnapshot(JSON.stringify({ ...snapshot, observation: { ...measured,
      kind: 'predicted', estimated_time: '2026-10-21T12:00:00.200Z', prediction_age_s: .2 } }))).toThrow()
  })
  it('accepts an invalid result without presenting it as a measurement', () => {
    const invalid = parseSnapshot(JSON.stringify({ ...snapshot, health: 'stale', observation: {
      ...measured, kind: 'invalid', position: null, covariance: null, reason: 'altitude_stale',
    } }))
    expect(invalid.observation?.position).toBeNull()
  })
})
