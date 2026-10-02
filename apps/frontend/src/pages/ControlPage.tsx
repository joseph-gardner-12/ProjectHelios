import { useState } from 'react'
import { ControlSession } from '../control/ControlSession'
import { useControl } from '../control/useControl'
import { toFeet } from '../control/api'
import type { PointerEvent } from 'react'
import './control.css'

type Position = { x: number; y: number; z: number }
const INITIAL: Position = { x: 0, y: 0, z: 0 }
const TARGET: Position = { x: 5, y: 5, z: 5 }
const TICKS = [0, 2.5, 5, 7.5, 10]
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))
const coordinates = (p: Position) => `${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)} ft`

function SpaceView({ drone, target, stale }: { drone: Position | null; target: Position; stale: boolean }) {
  const [angle, setAngle] = useState(0)
  // Orbit zero matches the dock-left view; the slider measures rotation from it.
  const radians = (315 + angle) * Math.PI / 180
  const project = ({ x, y, z }: Position) => ({
    x: 300 + ((y - 5) * Math.cos(radians) - (x - 5) * Math.sin(radians)) * 26,
    y: 345 + ((y - 5) * Math.sin(radians) + (x - 5) * Math.cos(radians)) * 13 - z * 22,
  })
  const line = (a: Position, b: Position, className: string, key?: string) => {
    const start = project(a)
    const end = project(b)
    return <line key={key} x1={start.x} y1={start.y} x2={end.x} y2={end.y} className={className} />
  }
  const dock = project(INITIAL)
  const current = drone ? project(drone) : null
  const destination = project(target)
  return (
    <section className="control-panel space-panel" aria-labelledby="space-title">
      <div className="panel-heading"><div><h2 id="space-title">Flight space</h2></div><span className="panel-detail">3D view</span></div>
      <div className="space-viewport">
        <div className="position-readout"><span>Reported position · Dummy{stale ? " · Stale" : ""}</span><output aria-live="off">{drone ? coordinates(drone) : "Unavailable"}</output></div>
      <svg className="space-graph" viewBox="0 0 600 480" role="img" aria-label={`3D flight space. All axes range from 0 to 10 feet. Dock at 0, 0, 0. Reported position ${drone ? coordinates(drone) : "unavailable"}. Target at ${coordinates(target)}.`}>
        <polygon points={[{ x: 0, y: 0, z: 0 }, { x: 10, y: 0, z: 0 }, { x: 10, y: 10, z: 0 }, { x: 0, y: 10, z: 0 }].map(p => { const point = project(p); return `${point.x},${point.y}` }).join(' ')} fill="#17131d" />
        {TICKS.map(t => <g key={t}>{line({ x: t, y: 0, z: 0 }, { x: t, y: 10, z: 0 }, 'space-grid')}{line({ x: 0, y: t, z: 0 }, { x: 10, y: t, z: 0 }, 'space-grid')}</g>)}
        {line({ x: 0, y: 0, z: 0 }, { x: 10, y: 0, z: 0 }, 'space-axis')}
        {line({ x: 0, y: 0, z: 0 }, { x: 0, y: 10, z: 0 }, 'space-axis')}
        {line({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 10 }, 'space-axis')}
        {[{ label: 'X · 10 ft', x: 11, y: 0, z: 0 }, { label: 'Y · 10 ft', x: 0, y: 11, z: 0 }, { label: 'Z · 10 ft', x: 0, y: 0, z: 11 }].map(p => <text key={p.label} {...project(p)} className="axis-label" textAnchor="middle">{p.label}</text>)}
        <g transform={`translate(${dock.x} ${dock.y})`} className="dock-marker">
          <path d="M0-10L20 0L0 10L-20 0Z" />
          <text x="0" y="30" textAnchor="middle">DOCK · 0, 0, 0</text>
        </g>
        {line({ ...target, z: 0 }, target, 'target-guide')}
        {drone && line({ ...drone, z: 0 }, drone, 'drone-guide')}
        {drone && line(drone, target, 'flight-path')}
        {drone && <ellipse {...{ cx: project({ ...drone, z: 0 }).x, cy: project({ ...drone, z: 0 }).y }} rx="14" ry="6" fill="#b9a1de" opacity="0.25" />}
        <g transform={`translate(${destination.x} ${destination.y})`} className="target-marker"><circle r="12" /><circle r="4" fill="currentColor" /><path d="M-18 0h8 M10 0h8 M0-18v8 M0 10v8" /><text x="20" y="-14">TARGET</text></g>
        {current && <g transform={`translate(${current.x} ${current.y})`} className="drone-marker"><path d="M-12-7L12 7M-12 7L12-7" />{[[-12, -7], [12, 7], [-12, 7], [12, -7]].map(([x, y]) => <ellipse key={`${x},${y}`} cx={x} cy={y} rx="7" ry="4" />)}<circle r="4" fill="currentColor" /><text x="22" y="5">DRONE</text></g>}
      </svg>
      </div>
      <div className="view-controls"><div className="graph-legend"><span><i className="drone-dot" />Drone</span><span><i className="target-dot" />Target</span></div><label className="orbit-control">Orbit <input aria-label="Rotate 3D view" type="range" min="0" max="360" aria-valuetext={`${angle} degrees`} value={angle} onChange={e => setAngle(Number(e.target.value))} /></label></div>
    </section>
  )
}

export default function ControlPage() {
  const control = useControl()
  const [target, setTarget] = useState(TARGET)
  const drone = control.snapshot?.position ? toFeet(control.snapshot.position) : null
  const updateTarget = (patch: Partial<Position>) => {
    setTarget(previous => ({ ...previous, ...patch }))
  }
  const placeTarget = (event: PointerEvent<HTMLButtonElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    updateTarget({ x: Math.round(clamp((event.clientX - bounds.left) / bounds.width * 10, 0, 10) * 10) / 10, y: Math.round(clamp(10 - (event.clientY - bounds.top) / bounds.height * 10, 0, 10) * 10) / 10 })
  }
  const reset = () => setTarget(TARGET)

  return (
    <div className="control-page">
      <title>Control · Project Helios</title>
      <div className="control-intro"><h1>Helios Control</h1></div>
      <ControlSession control={control} />
      <div className="control-workspace">
        <SpaceView drone={drone} target={target} stale={!control.fresh} />
        <section className="control-panel target-panel" aria-labelledby="target-title">
          <div className="panel-heading"><div><h2 id="target-title">Set your target</h2></div><span className="panel-detail">Top view</span></div>
          <div className="target-controls">
            <div className="xy-control"><div className="control-label"><span>XY plane</span></div>
              <button className="xy-plane" type="button" aria-label={`Target XY plane. X ${target.x}, Y ${target.y} feet. Use arrow keys to move by 0.5 feet.`}
                onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); placeTarget(event) }}
                onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) placeTarget(event) }}
                onPointerCancel={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId) }}
                onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId) }}
                onKeyDown={event => { const keys: Record<string, Partial<Position>> = { ArrowLeft: { x: clamp(target.x - 0.5, 0, 10) }, ArrowRight: { x: clamp(target.x + 0.5, 0, 10) }, ArrowUp: { y: clamp(target.y + 0.5, 0, 10) }, ArrowDown: { y: clamp(target.y - 0.5, 0, 10) } }; const patch = keys[event.key]; if (patch) { event.preventDefault(); updateTarget(patch) } }}>
                <svg viewBox="0 0 300 300" aria-hidden="true"><path className="xy-grid" d="M0 0H300V300H0Z M75 0V300 M150 0V300 M225 0V300 M0 75H300 M0 150H300 M0 225H300" /><path className="xy-axis" d="M0 0V300H300" /><text x="8" y="18">Y · 10 ft</text><text x="292" y="289" textAnchor="end">X · 10 ft</text><rect className="xy-dock" x="-6" y="294" width="12" height="12" /><text x="12" y="280">DOCK · 0, 0</text>{drone && <><line className="flight-path" x1={drone.x * 30} y1={(10 - drone.y) * 30} x2={target.x * 30} y2={(10 - target.y) * 30} /><circle className="xy-drone" cx={drone.x * 30} cy={(10 - drone.y) * 30} r="5" /></>}</svg>
                <span className="xy-target" style={{ left: `${target.x * 10}%`, top: `${(10 - target.y) * 10}%` }} />
              </button>
            </div>
            <div className="height-control"><label htmlFor="height">Z height</label><span className="height-max">10 ft</span><input id="height" type="range" min="0" max="10" step="0.1" value={target.z} aria-valuetext={`${target.z} feet`} onChange={event => updateTarget({ z: Number(event.target.value) })} /><span>0 ft</span><output htmlFor="height">{target.z.toFixed(1)} ft</output></div>
          </div>
          <div className="coordinate-inputs">{(['x', 'y', 'z'] as const).map(axis => <label key={axis}><span>{axis.toUpperCase()}</span><input aria-label={`Target ${axis.toUpperCase()} in feet`} type="number" min="0" max="10" step="0.1" key={target[axis]} defaultValue={target[axis]} onBlur={event => { const value = event.target.valueAsNumber; if (Number.isFinite(value)) { const bounded = Math.round(clamp(value, 0, 10) * 10) / 10; event.target.value = String(bounded); updateTarget({ [axis]: bounded }) } else event.target.value = String(target[axis]) }} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} /><span>ft</span></label>)}</div>
          <div className="flight-actions"><button className="fly-button" disabled={control.unresolved ? control.busy || !control.connected : !control.canSend} onClick={() => void control.send(target)}>{control.busy ? 'Sending…' : control.unresolved ? 'Resolve submission' : 'Send target'}<span aria-hidden="true">↗</span></button><button className="reset-button" onClick={reset}>Reset</button></div>
          <p className="control-detail">Selected target: {coordinates(target)}</p>
          {control.command && <p className="control-detail">Submitted target: {coordinates(toFeet(control.command.target))}</p>}

        </section>
      </div>
    </div>
  )
}
