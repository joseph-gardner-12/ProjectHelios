import type { Snapshot } from './api'

/** Surveyed positions have signed coordinates and no waypoint controls. */
export function ObservationPanel({ snapshot, fresh }: { snapshot: Snapshot; fresh: boolean }) {
  const observation = snapshot.observation
  const kind = observation?.kind ?? 'invalid'
  const position = observation?.position ?? snapshot.position
  const label = kind === 'predicted' ? 'Predicted' : kind === 'measured' ? 'Measured' : 'Invalid'
  return <section className="control-panel observation-panel" aria-labelledby="observation-title">
    <div className="panel-heading"><h2 id="observation-title">Localization observations</h2>
      <span className="panel-detail">Read only</span></div>
    <p role="status">{snapshot.source === 'synthetic' ? 'Synthetic · ' : 'UWB · '}{label}{fresh ? '' : ' · Stale'}</p>
    <div className="observation-coordinates">{(['x', 'y', 'z'] as const).map((axis, i) =>
      <div key={axis}><span>{axis.toUpperCase()} · {['East', 'North', 'Up'][i]}</span>
        <output>{position ? `${position[axis].toFixed(3)} m` : 'Unavailable'}</output>
        <small>{observation?.covariance ? `σ ${Math.sqrt(observation.covariance[i]?.[i] ?? 0).toFixed(3)} m` : 'Uncertainty unavailable'}</small>
      </div>)}</div>
    <dl><dt>Survey frame</dt><dd>{snapshot.frame_version}</dd>
      <dt>Last measurement</dt><dd>{observation?.measurement_time ?? 'Unavailable'}</dd>
      <dt>Prediction age</dt><dd>{observation?.prediction_age_s == null ? 'Unavailable' : `${(observation.prediction_age_s * 1000).toFixed(0)} ms`}</dd>
      <dt>Timing uncertainty</dt><dd>{observation ? `${(observation.timing_sigma_s * 1000).toFixed(0)} ms` : 'Unavailable'}</dd>
    </dl>
    {observation?.reason && <p className="control-error">{observation.reason.replaceAll('_', ' ')}</p>}
    {!fresh && position && <p className="control-detail">Coordinates are retained for reference and are not a current valid position.</p>}
  </section>
}
