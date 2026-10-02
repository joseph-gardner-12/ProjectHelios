import { parseSnapshot, socketUrl } from './api'
import type { Snapshot } from './api'

type Callbacks = {
  snapshot: (value: Snapshot) => void
  disconnected: () => void
  denied: () => void
  error: (message: string) => void
}

/** Owns every reconnect timer and socket until the returned cleanup is called. */
export function subscribeDevice(device: string, callbacks: Callbacks) {
  let disposed = false
  let socket: WebSocket | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempt = 0
  let latest: Snapshot | null = null
  const open = () => {
    if (disposed) return
    const current = new WebSocket(socketUrl(device))
    socket = current
    current.onmessage = event => {
      if (disposed || current !== socket) return
      try {
        const next = parseSnapshot(event.data)
        if (next.device_id !== device) throw new Error('Unexpected device')
        if (latest && (next.revision < latest.revision || (next.revision === latest.revision
          && next.connection_id === latest.connection_id && (next.sequence < latest.sequence
            || Date.parse(next.timestamp) < Date.parse(latest.timestamp))))) return
        latest = next
        callbacks.snapshot(next)
        attempt = 0
      } catch (e) {
        callbacks.error(e instanceof Error ? e.message : 'Invalid telemetry')
        current.close()
      }
    }
    current.onclose = event => {
      if (disposed || current !== socket) return
      callbacks.disconnected()
      if (event.code === 4401 || event.code === 4403) { callbacks.denied(); return }
      timer = setTimeout(open, Math.min(30000, 1000 * 2 ** attempt++) * (0.5 + Math.random() / 2))
    }
    current.onerror = () => current.close()
  }
  open()
  return () => {
    disposed = true
    clearTimeout(timer)
    if (socket) {
      socket.onmessage = null
      socket.onclose = null
      socket.onerror = null
      socket.close()
    }
  }
}
