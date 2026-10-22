export type Position = { x: number; y: number; z: number }
export type Command = { id: string; request_id: string; target: Position; status: string; reason: string }
export type Observation = {
  kind: 'measured' | 'predicted' | 'invalid'; session: string
  estimated_time: string; measurement_time: string | null; prediction_age_s: number | null
  position: Position | null; covariance: number[][] | null; timing_sigma_s: number; reason: string | null
}
export type SimulatedLocalization = { frame: string; observation: Observation }
export type Snapshot = {
  simulated_localization?: SimulatedLocalization | null
  version: 1; type: 'snapshot'; device_id: string; connection_id: string | null
  frame_version: string; timestamp: string; revision: number; sequence: number
  health: 'fresh' | 'stale' | 'offline'; position: Position | null; position_at: number | null
  source: 'dummy' | 'uwb' | 'synthetic'; capability?: 'dummy' | 'measurement'; observation?: Observation | null; command: Command | null; can_send: boolean
  queue: { position: number | null; joined: boolean; controller: boolean; lease_id: string | null
    expires_at: string | null; releasing: boolean }
}
export type Session = { authenticated: boolean; email: string | null; csrf_token: string }
export type Submission = { request_id: string; lease_id: string; frame_version: string; target: Position }
export const toMetres = (p: Position): Position => ({ x: p.x * 0.3048, y: p.y * 0.3048, z: p.z * 0.3048 })
export const toFeet = (p: Position): Position => ({ x: p.x / 0.3048, y: p.y / 0.3048, z: p.z / 0.3048 })
export const API_ORIGIN = import.meta.env.VITE_API_ORIGIN ?? (import.meta.env.PROD ? 'https://api.projecthelios.dev' : '')
export const socketUrl = (device: string) => `${API_ORIGIN || location.origin}`.replace(/^http/, 'ws') + `/ws/v1/devices/${device}/`
let csrfToken = ''
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}
export async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_ORIGIN}/api/v1/${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'include',
    signal: signal ?? AbortSignal.timeout(10000),
    headers: { 'Content-Type': 'application/json', ...(body === undefined ? {} : { 'X-CSRFToken': csrfToken }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    const failure = await response.json().catch(() => null)
    throw new ApiError(failure?.error ?? `Request failed (${response.status})`, response.status)
  }
  const result = await response.json().catch(() => null)
  if (!result) throw new Error('Backend returned an invalid response')
  if (typeof result.csrf_token === 'string') csrfToken = result.csrf_token
  return result as T
}
const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
export function isPosition(v: unknown): v is Position {
  return record(v) && Object.keys(v).length === 3 && ['x', 'y', 'z'].every(k =>
    typeof v[k] === 'number' && Number.isFinite(v[k]) && v[k] >= 0 && v[k] <= 3.048)
}
export function isSignedPosition(v: unknown): v is Position {
  return record(v) && Object.keys(v).length === 3 && ['x', 'y', 'z'].every(k =>
    typeof v[k] === 'number' && Number.isFinite(v[k]))
}
export function isObservation(v: unknown): v is Observation {
  if (!record(v) || !['measured', 'predicted', 'invalid'].includes(String(v.kind))
    || typeof v.session !== 'string' || !v.session || v.session.length > 100
    || typeof v.estimated_time !== 'string' || !Number.isFinite(Date.parse(v.estimated_time))
    || typeof v.timing_sigma_s !== 'number' || !Number.isFinite(v.timing_sigma_s) || v.timing_sigma_s < 0) return false
  if (v.measurement_time === null) {
    if (v.prediction_age_s !== null) return false
  } else {
    if (typeof v.measurement_time !== 'string' || !Number.isFinite(Date.parse(v.measurement_time))
      || typeof v.prediction_age_s !== 'number' || !Number.isFinite(v.prediction_age_s) || v.prediction_age_s < 0
      || Math.abs((Date.parse(v.estimated_time) - Date.parse(v.measurement_time)) / 1000 - v.prediction_age_s) > 0.002) return false
  }
  if (v.kind === 'invalid') return v.position === null && v.covariance === null && typeof v.reason === 'string'
  if (v.measurement_time === null || Number(v.prediction_age_s) > 0.100001
    || (v.kind === 'measured' && v.prediction_age_s !== 0)
    || !isSignedPosition(v.position) || v.reason !== null) return false
  return Array.isArray(v.covariance) && v.covariance.length === 3 && v.covariance.every((row, i) =>
    Array.isArray(row) && row.length === 3 && row.every((n: unknown) => typeof n === 'number' && Number.isFinite(n)) && row[i] > 0)
}
export function parseSnapshot(raw: string): Snapshot {
  const v: unknown = JSON.parse(raw)
  if (!record(v) || v.version !== 1 || v.type !== 'snapshot' || !['dummy', 'uwb', 'synthetic'].includes(String(v.source))
    || typeof v.device_id !== 'string' || typeof v.frame_version !== 'string' || !v.frame_version
    || (v.connection_id !== null && typeof v.connection_id !== 'string')
    || typeof v.timestamp !== 'string' || !Number.isFinite(Date.parse(v.timestamp))
    || !Number.isInteger(v.revision) || !Number.isInteger(v.sequence)
    || !['fresh', 'stale', 'offline'].includes(String(v.health))
    || (v.position !== null && !(v.capability === 'measurement' ? isSignedPosition(v.position) : isPosition(v.position)))
    || (v.capability !== undefined && !['dummy', 'measurement'].includes(String(v.capability)))
    || (v.capability === 'measurement' ? v.frame_version === 'dummy-enu-v1' || v.can_send !== false
      || (v.observation !== null && !isObservation(v.observation))
      : v.frame_version !== 'dummy-enu-v1' || v.source !== 'dummy')
    || (v.simulated_localization != null && (v.capability === 'measurement'
      || !record(v.simulated_localization) || typeof v.simulated_localization.frame !== 'string'
      || !v.simulated_localization.frame || !isObservation(v.simulated_localization.observation)))
    || (v.position_at !== null && (typeof v.position_at !== 'number' || !Number.isFinite(v.position_at)))
    || typeof v.can_send !== 'boolean' || !record(v.queue)
    || typeof v.queue.controller !== 'boolean' || typeof v.queue.joined !== 'boolean'
    || typeof v.queue.releasing !== 'boolean'
    || (v.queue.position !== null && (!Number.isInteger(v.queue.position) || Number(v.queue.position) < 1))
    || (v.queue.lease_id !== null && typeof v.queue.lease_id !== 'string')
    || (v.queue.expires_at !== null && (typeof v.queue.expires_at !== 'string' || !Number.isFinite(Date.parse(v.queue.expires_at))))
    || (v.command !== null && (!record(v.command) || !isPosition(v.command.target)
      || typeof v.command.id !== 'string' || typeof v.command.request_id !== 'string'
      || typeof v.command.reason !== 'string' || !['pending_ack', 'accepted', 'arrived', 'rejected', 'unconfirmed', 'interrupted'].includes(String(v.command.status))))) {
    throw new Error('Invalid live telemetry')
  }
  return v as Snapshot
}
