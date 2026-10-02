import { afterEach, expect, it, vi } from 'vitest'
import { subscribeDevice } from './live'

class Socket {
  static instances: Socket[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor() { Socket.instances.push(this) }
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); Socket.instances = [] })

it('closes the current connection and cancels reconnect on cleanup', () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('location', { origin: 'http://localhost' })
  const callbacks = { snapshot: vi.fn(), disconnected: vi.fn(), denied: vi.fn(), error: vi.fn() }
  const unsubscribe = subscribeDevice('device', callbacks)
  const socket = Socket.instances[0]!
  socket.onclose?.({ code: 1006 })
  unsubscribe()
  vi.runAllTimers()
  expect(Socket.instances).toHaveLength(1)
  expect(socket.close).toHaveBeenCalledOnce()
  expect(callbacks.disconnected).toHaveBeenCalledOnce()
})

it('does not reconnect an unauthorized browser session', () => {
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('location', { origin: 'http://localhost' })
  const callbacks = { snapshot: vi.fn(), disconnected: vi.fn(), denied: vi.fn(), error: vi.fn() }
  const unsubscribe = subscribeDevice('device', callbacks)
  Socket.instances[0]!.onclose?.({ code: 4401 })
  vi.runAllTimers()
  expect(callbacks.denied).toHaveBeenCalledOnce()
  expect(Socket.instances).toHaveLength(1)
  unsubscribe()
})
