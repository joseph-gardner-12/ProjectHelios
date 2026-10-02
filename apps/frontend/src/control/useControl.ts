import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, request, toMetres } from './api'
import { subscribeDevice } from './live'
import type { Command, Position, Session, Snapshot, Submission } from './api'

export function useControl() {
  const [session, setSession] = useState<Session | null>(null)
  const [device, setDevice] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [unresolved, setUnresolved] = useState(false)
  const [submitted, setSubmitted] = useState<Command | null>(null)
  const [clock, setClock] = useState(() => performance.now())
  const [wallClock, setWallClock] = useState(() => Date.now())
  const [received, setReceived] = useState({ at: 0, age: Infinity })
  const pending = useRef<Submission | null>(null)
  const inFlight = useRef(false)

  const loadDevice = useCallback(async (signal?: AbortSignal) => {
    const result = await request<{ devices: { id: string }[] }>('devices/', undefined, signal)
    setDevice(result.devices[0]?.id ?? null)
  }, [])
  useEffect(() => {
    const abort = new AbortController()
    request<Session>('session/', undefined, abort.signal).then(async value => {
      setSession(value)
      if (value.authenticated) await loadDevice(abort.signal)
    }).catch(e => { if (!abort.signal.aborted) setError(String(e.message)) })
    return () => abort.abort()
  }, [loadDevice])

  useEffect(() => {
    const timer = window.setInterval(() => { setClock(performance.now()); setWallClock(Date.now()) }, 250)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!device || !session?.authenticated) return
    const unsubscribe = subscribeDevice(device, {
      snapshot(next) {
        setReceived({ at: performance.now(), age: next.position_at === null ? Infinity
          : Math.max(0, Date.parse(next.timestamp) - next.position_at * 1000) })
        setSnapshot(previous => next.position ? next : { ...next, position: previous?.position ?? null })
        setConnected(true)
      },
      disconnected() { setConnected(false) },
      denied() { setError('Session or device access expired. Sign in again.'); setSession(null) },
      error(message) { setError(message) },
    })
    return () => { unsubscribe(); setConnected(false) }
  }, [device, session?.authenticated])

  const runAction = (operation: () => Promise<void>) =>
    performControlAction(inFlight, setBusy, setError, operation)
  const login = (email: string, password: string) => runAction(async () => {
    // Refresh CSRF even when the initial bootstrap failed or a prior session expired.
    await request<Session>('session/')
    const result = await request<Session & { device_id: string }>('login/', { email, password })
    setSnapshot(null); setSubmitted(null); pending.current = null; setUnresolved(false)
    setSession(result); setDevice(result.device_id)
  })
  const logout = () => runAction(async () => {
    const result = await request<Session>('logout/', {})
    setSession(result); setDevice(null); setSnapshot(null); setSubmitted(null)
    pending.current = null; setUnresolved(false)
  })
  const queue = (join: boolean) => runAction(async () => {
    await request(`devices/${device}/queue/${join ? 'join' : 'leave'}/`, {})
  })
  const send = (target: Position) => runAction(async () => {
    if (!device) return
    if (!pending.current) {
      if (!snapshot?.queue.lease_id) return
      pending.current = { request_id: crypto.randomUUID(), lease_id: snapshot.queue.lease_id,
        frame_version: snapshot.frame_version, target: toMetres(target) }
    }
    const submission = pending.current
    try {
      let result: { command: Command }
      if (unresolved) {
        try {
          result = await request(`devices/${device}/commands/?request_id=${submission.request_id}`)
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 404) throw e
          result = await request(`devices/${device}/targets/`, submission)
        }
      } else result = await request(`devices/${device}/targets/`, submission)
      setSubmitted(result.command); pending.current = null; setUnresolved(false)
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
        pending.current = null; setUnresolved(false)
      } else setUnresolved(true)
      throw e
    }
  })
  const fresh = connected && snapshot?.health === 'fresh'
    && received.age + clock - received.at < 2000
  const command = snapshot?.command && snapshot.command.id === submitted?.id ? snapshot.command : submitted ?? snapshot?.command
  return { session, snapshot, connected, fresh, error, busy, unresolved, command, wallClock,
    canSend: !!(fresh && snapshot?.can_send && !busy && !unresolved
      && !['pending_ack', 'accepted'].includes(command?.status ?? '')),
    login, logout, queue, send }
}

async function performControlAction(
  inFlight: { current: boolean }, onBusy: (busy: boolean) => void,
  onError: (message: string) => void, operation: () => Promise<void>,
) {
  if (inFlight.current) return
  inFlight.current = true; onBusy(true); onError('')
  try { await operation() } catch (e) { onError(e instanceof Error ? e.message : 'Request failed') }
  finally { inFlight.current = false; onBusy(false) }
}
