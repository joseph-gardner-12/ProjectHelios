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
