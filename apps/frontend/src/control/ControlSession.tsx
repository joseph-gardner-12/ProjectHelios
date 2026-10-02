import { useState } from 'react'
import type { useControl } from './useControl'

type Control = ReturnType<typeof useControl>
const statuses: Record<string, string> = {
  pending_ack: 'Waiting for Pi acknowledgment', accepted: 'Accepted · Moving', arrived: 'Arrived',
  rejected: 'Rejected', unconfirmed: 'Delivery unconfirmed', interrupted: 'Interrupted',
}

function SignInForm({ control }: { control: Control }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  return <form className="control-access" onSubmit={event => {
    event.preventDefault(); void control.login(email, password); setPassword('')
  }}>
    <h2>Join the control queue</h2>
    <p>Use your Clemson email and the shared demo password. Email ownership is not verified.</p>
    <label>Clemson email<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label>
    <label>Demo password<input type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></label>
    <button disabled={control.busy} type="submit">{control.busy ? 'Joining…' : 'Join queue'}</button>
  </form>
}

function QueueStatus({ control }: { control: Control }) {
  const queue = control.snapshot?.queue
  const seconds = queue?.expires_at ? Math.max(0, Math.ceil((Date.parse(queue.expires_at) - control.wallClock) / 1000)) : 0
  let turn = 'Watching · Not queued'
  if (queue?.controller) {
    turn = `Your turn · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} remaining`
    if (queue.releasing) turn += ' · Releasing after current target'
  } else if (queue?.joined) turn = `Waiting · Queue position ${queue.position ?? '…'}`
  return <section className="control-status" aria-label="Connection and control status">
    <p>{control.session?.email} <span>· Dummy telemetry · {control.fresh ? 'Live' : control.connected ? 'Stale / device offline' : 'Disconnected'}</span></p>
    <p>{turn}</p>
    <div><button disabled={control.busy} onClick={() => void control.queue(!queue?.joined)}>{queue?.joined ? 'Leave / release turn' : 'Rejoin queue'}</button><button disabled={control.busy} onClick={() => void control.logout()}>Sign out</button></div>
  </section>
}

export function ControlSession({ control }: { control: Control }) {
  const command = control.command
  return <>
    {control.session?.authenticated ? <QueueStatus control={control} /> : <SignInForm control={control} />}
    <p className="control-detail" role="status" aria-label="Command status">{command
      ? `Command: ${statuses[command.status] ?? command.status}${command.reason ? ` — ${command.reason}` : ''}`
      : 'No target submitted'}</p>
    {control.error && <p className="control-error" role="alert">{control.error}</p>}
  </>
}
