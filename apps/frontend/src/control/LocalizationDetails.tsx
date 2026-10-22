import type { useControl } from './useControl'
import { ObservationPanel } from './ObservationPanel'

/** Additional sensor diagnostics below the unchanged waypoint workspace. */
export function LocalizationDetails({ control }: { control: ReturnType<typeof useControl> }) {
  const snapshot = control.snapshot
  if (!snapshot) return null
  if (snapshot.capability === 'measurement') {
    return <div>
      <p className="control-detail">Real UWB tracking · Waypoint entry is available for reference;
        sending aircraft commands is disabled in this measurement-only session.</p>
      <ObservationPanel snapshot={snapshot} fresh={!!control.fresh} />
    </div>
  }
  const simulated = snapshot.simulated_localization
  if (!simulated) return null
  const observation = simulated.observation
  const measuredAt = observation.measurement_time ? Date.parse(observation.measurement_time) : 0
  const fresh = control.connected && observation.kind !== 'invalid'
    && control.wallClock - measuredAt + observation.timing_sigma_s * 1000 < 100
  return <div>
    <p className="control-detail">UWB simulation · The controls above move the simulated drone.
      No aircraft is connected. Synthetic ranges feed the nonlinear solver below.</p>
    <ObservationPanel snapshot={{ ...snapshot, source: 'synthetic', frame_version: simulated.frame,
      observation, position: observation.position }} fresh={fresh} />
  </div>
}
