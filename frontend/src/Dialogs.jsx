import React, { useEffect, useState } from 'react'
import { api } from './api.js'

function Modal({ title, children, onClose, actions }) {
  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  return (
    <div className="overlay" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog">
        <h3>{title}</h3>
        <div className="body">{children}</div>
        <div className="foot">{actions}</div>
      </div>
    </div>
  )
}

/** Sfoglia il disco: usato sia per importare media sia per aprire progetti. */
export function FileBrowser({ title, filter, multiple = true, onPick, onClose, startPath }) {
  const [cwd, setCwd] = useState(null)
  const [picked, setPicked] = useState([])
  const [err, setErr] = useState(null)

  const load = (path) => api.browse(path).then(setCwd).catch((e) => setErr(e.message))
  useEffect(() => { load(startPath) }, [])

  const files = (cwd?.files || []).filter((f) => (filter ? filter(f.name) : true))
  const toggle = (path) => setPicked((p) =>
    p.includes(path) ? p.filter((x) => x !== path) : (multiple ? [...p, path] : [path]))

  return (
    <Modal
      title={title} onClose={onClose}
      actions={<>
        <span className="hint">{picked.length ? `${picked.length} selezionati` : ''}</span>
        <button onClick={onClose}>annulla</button>
        <button className="primary" disabled={!picked.length}
          onClick={() => { onPick(picked); onClose() }}>conferma</button>
      </>}
    >
      {err && <div className="hint" style={{ color: 'var(--danger)' }}>{err}</div>}
      <div className="crumb">{cwd?.path}</div>
      <div className="browser">
        {cwd?.parent && (
          <div className="item" onClick={() => { setPicked([]); load(cwd.parent) }}>📁 ..</div>
        )}
        {(cwd?.dirs || []).map((d) => (
          <div className="item" key={d.path} onClick={() => { setPicked([]); load(d.path) }}>
            📁 {d.name}
          </div>
        ))}
        {files.map((f) => (
          <div className={`item ${picked.includes(f.path) ? 'picked' : ''}`} key={f.path}
            onClick={() => toggle(f.path)}
            onDoubleClick={() => { onPick([f.path]); onClose() }}>
            🎬 {f.name}
            <span className="spacer" style={{ flex: 1 }} />
            <span className="hint">{(f.size / 1e6).toFixed(1)} MB</span>
          </div>
        ))}
        {!cwd && <div className="item">caricamento…</div>}
      </div>
    </Modal>
  )
}

export function NewProject({ presets, onCreate, onClose }) {
  const [path, setPath] = useState('')
  const [name, setName] = useState('nuovo progetto')
  const [preset, setPreset] = useState('1080p')

  const create = () => {
    let p = path.trim()
    if (!p) return
    if (!p.toLowerCase().endsWith('.json')) p += '.json'
    onCreate(p, name, preset)
    onClose()
  }

  return (
    <Modal title="Nuovo progetto" onClose={onClose}
      actions={<>
        <button onClick={onClose}>annulla</button>
        <button className="primary" disabled={!path.trim()} onClick={create}>crea</button>
      </>}>
      <div className="row"><label>nome</label>
        <input value={name} onChange={(e) => setName(e.target.value)} /><span /></div>
      <div className="row"><label>file</label>
        <input value={path} placeholder="C:\video\progetto.json"
          onChange={(e) => setPath(e.target.value)} /><span /></div>
      <div className="row"><label>formato</label>
        <select value={preset} onChange={(e) => setPreset(e.target.value)}>
          {presets.map((p) => <option key={p} value={p}>{p}</option>)}
        </select><span /></div>
      <div className="hint">
        vertical = 9:16 per reel e short · square = 1:1. Il file .json e' il progetto:
        i video restano dove sono.
      </div>
    </Modal>
  )
}

export function RenderDialog({ project, job, onStart, onClose }) {
  const [output, setOutput] = useState('')
  const [quality, setQuality] = useState('high')
  const [codec, setCodec] = useState('h264')
  const [range, setRange] = useState(false)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(project?.duration || 0)

  const running = job && job.state === 'running'

  return (
    <Modal title="Esporta" onClose={onClose}
      actions={<>
        <button onClick={onClose}>chiudi</button>
        <button className="primary" disabled={!output.trim() || running}
          onClick={() => onStart({
            output: output.trim(), quality, codec,
            start: range ? start : null, end: range ? end : null,
          })}>
          {running ? 'in corso…' : 'esporta'}
        </button>
      </>}>
      <div className="row"><label>file</label>
        <input value={output} placeholder="C:\video\finale.mp4"
          onChange={(e) => setOutput(e.target.value)} /><span /></div>
      <div className="row"><label>qualita'</label>
        <select value={quality} onChange={(e) => setQuality(e.target.value)}>
          <option value="draft">bozza (velocissima)</option>
          <option value="medium">media</option>
          <option value="high">alta</option>
          <option value="max">massima</option>
        </select><span /></div>
      <div className="row"><label>codec</label>
        <select value={codec} onChange={(e) => setCodec(e.target.value)}>
          <option value="h264">H.264 (compatibile ovunque)</option>
          <option value="hevc">HEVC / H.265</option>
          <option value="av1">AV1</option>
          <option value="vp9">VP9 (webm)</option>
        </select><span /></div>
      <div className="row"><label>solo parte</label>
        <input type="checkbox" checked={range} onChange={(e) => setRange(e.target.checked)} /><span /></div>
      {range && (
        <div className="row"><label>da / a</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <input type="number" step="0.1" value={start} onChange={(e) => setStart(+e.target.value)} />
            <input type="number" step="0.1" value={end} onChange={(e) => setEnd(+e.target.value)} />
          </div><span /></div>
      )}
      <div className="hint">l'estensione decide il contenitore: .mp4 .mov .mkv .webm .gif .mp3 .wav</div>

      {job && (
        <div style={{ marginTop: 14 }}>
          <div className="progress"><div style={{ width: `${job.percent || 0}%` }} /></div>
          <div className="hint" style={{ marginTop: 6 }}>
            {job.state === 'done' && `fatto: ${job.output} (${job.mb} MB, ${job.encoder}, ${job.seconds_total}s)`}
            {job.state === 'error' && <span style={{ color: 'var(--danger)' }}>errore: {job.error}</span>}
            {job.state === 'running' && `${(job.percent || 0).toFixed(1)}% · ${(job.seconds || 0).toFixed(1)}/${(job.duration || 0).toFixed(1)}s`}
          </div>
        </div>
      )}
    </Modal>
  )
}
