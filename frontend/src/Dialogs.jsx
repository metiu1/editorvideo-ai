import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'

/**
 * Finestra modale.
 *
 * Il fuoco entra nella finestra all'apertura e non ne esce con Tab: senza,
 * si tabula dentro l'editor sotto senza vederlo, e Esc non chiude niente.
 */
function Modal({ title, children, onClose, actions, narrow }) {
  const box = useRef(null)

  useEffect(() => {
    const prev = document.activeElement
    const focusables = () => box.current?.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select, textarea, [tabindex]:not([tabindex="-1"])'
    ) || []
    // primo campo di testo se c'e', altrimenti il primo comando
    const first = box.current?.querySelector('input:not([type=checkbox]), textarea')
      || focusables()[0]
    first?.focus()

    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return }
      if (e.key !== 'Tab') return
      const f = [...focusables()]
      if (!f.length) return
      const i = f.indexOf(document.activeElement)
      if (e.shiftKey && (i <= 0)) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => { window.removeEventListener('keydown', onKey, true); prev?.focus?.() }
  }, [onClose])

  return (
    <div className="overlay" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog ${narrow ? 'narrow' : ''}`} ref={box}
        role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        <div className="body">{children}</div>
        <div className="foot">{actions}</div>
      </div>
    </div>
  )
}

/** Conferma per le azioni che distruggono lavoro. */
export function Confirm({ title, message, ok = 'conferma', danger, onOk, onClose }) {
  return (
    <Modal narrow title={title} onClose={onClose}
      actions={<>
        <button onClick={onClose}>annulla</button>
        <button className="primary" onClick={() => { onOk(); onClose() }}>
          {danger && <Icon name="cestino" />}{ok}
        </button>
      </>}>
      <div style={{ lineHeight: 1.6 }}>{message}</div>
    </Modal>
  )
}

/** Sfoglia il disco: usato sia per importare media sia per aprire progetti. */
export function FileBrowser({ title, filter, multiple = true, onPick, onClose, startPath }) {
  const [cwd, setCwd] = useState(null)
  const [picked, setPicked] = useState([])
  const [err, setErr] = useState(null)

  const load = (path) => api.browse(path).then((d) => { setCwd(d); setErr(null) })
    .catch((e) => setErr(e.message))
  useEffect(() => { load(startPath) }, [])

  const files = (cwd?.files || []).filter((f) => (filter ? filter(f.name) : true))
  const toggle = (path) => setPicked((p) =>
    p.includes(path) ? p.filter((x) => x !== path) : (multiple ? [...p, path] : [path]))

  return (
    <Modal
      title={title} onClose={onClose}
      actions={<>
        <span className="hint">{picked.length ? `${picked.length} selezionati` : ''}</span>
        <span className="spacer" />
        <button onClick={onClose}>annulla</button>
        <button className="primary" disabled={!picked.length}
          onClick={() => { onPick(picked); onClose() }}>conferma</button>
      </>}
    >
      {err && <div className="hint" style={{ color: 'var(--danger)', marginBottom: 8 }}>{err}</div>}
      <div className="crumb">{cwd?.path || '…'}</div>
      <div className="browser">
        {cwd?.parent && (
          <div className="item" onClick={() => { setPicked([]); load(cwd.parent) }}>
            <Icon name="cartella" /> ..
          </div>
        )}
        {(cwd?.dirs || []).map((d) => (
          <div className="item" key={d.path} onClick={() => { setPicked([]); load(d.path) }}>
            <Icon name="cartella" /> {d.name}
          </div>
        ))}
        {files.map((f) => (
          <div className={`item ${picked.includes(f.path) ? 'picked' : ''}`} key={f.path}
            onClick={() => toggle(f.path)}
            onDoubleClick={() => { onPick([f.path]); onClose() }}>
            <Icon name="video" /> {f.name}
            <span className="spacer" style={{ flex: 1 }} />
            <span className="hint">{(f.size / 1e6).toFixed(1)} MB</span>
          </div>
        ))}
        {!cwd && <div className="item hint">caricamento…</div>}
        {cwd && !files.length && !cwd.dirs?.length && (
          <div className="item hint">cartella vuota</div>
        )}
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
    <Modal title="Nuovo progetto" narrow onClose={onClose}
      actions={<>
        <button onClick={onClose}>annulla</button>
        <button className="primary" disabled={!path.trim()} onClick={create}>crea</button>
      </>}>
      <div className="row"><label>nome</label>
        <input value={name} onChange={(e) => setName(e.target.value)} /><span /></div>
      <div className="row"><label>file</label>
        <input value={path} placeholder="C:\video\progetto.json"
          onKeyDown={(e) => e.key === 'Enter' && create()}
          onChange={(e) => setPath(e.target.value)} /><span /></div>
      <div className="row"><label>formato</label>
        <select value={preset} onChange={(e) => setPreset(e.target.value)}>
          {presets.map((p) => <option key={p} value={p}>{p}</option>)}
        </select><span /></div>
      <div className="hint" style={{ marginTop: 10 }}>
        vertical = 9:16 per reel e short · square = 1:1.<br />
        Il file .json è il progetto: i video restano dove sono.
      </div>
    </Modal>
  )
}

/**
 * Formati di uscita. La timeline resta quella: cambia il fotogramma in cui
 * viene composta, e le clip ci si adattano secondo il proprio "inquadra"
 * (cover riempie tagliando ai lati, contain lascia le bande).
 */
const FORMATI = [
  { id: 'progetto', nome: 'come il progetto', w: null, h: null },
  { id: '16:9 1080p', nome: '16:9 · 1920x1080', w: 1920, h: 1080 },
  { id: '16:9 720p', nome: '16:9 · 1280x720', w: 1280, h: 720 },
  { id: '16:9 4k', nome: '16:9 · 3840x2160', w: 3840, h: 2160 },
  { id: '1:1', nome: 'quadrato · 1080x1080', w: 1080, h: 1080 },
  { id: '9:16', nome: 'verticale · 1080x1920', w: 1080, h: 1920 },
  { id: '9:16 720', nome: 'verticale · 720x1280', w: 720, h: 1280 },
]

export function RenderDialog({ project, job, onStart, onClose }) {
  const [output, setOutput] = useState('')
  const [quality, setQuality] = useState('high')
  const [codec, setCodec] = useState('h264')
  const [formato, setFormato] = useState('progetto')
  const [range, setRange] = useState(false)
  const [start, setStart] = useState(0)
  const [end, setEnd] = useState(project?.duration || 0)

  const running = job && job.state === 'running'

  return (
    <Modal title="Esporta" onClose={onClose}
      actions={<>
        <button onClick={onClose}>chiudi</button>
        <button className="primary" disabled={!output.trim() || running}
          onClick={() => {
            const f = FORMATI.find((x) => x.id === formato) || FORMATI[0]
            onStart({
              output: output.trim(), quality, codec,
              width: f.w, height: f.h,
              start: range ? start : null, end: range ? end : null,
            })
          }}>
          {running ? <><Icon name="attesa" className="spin" />in corso…</> : <><Icon name="esporta" />esporta</>}
        </button>
      </>}>
      <div className="row"><label>file</label>
        <input value={output} placeholder="C:\video\finale.mp4"
          onChange={(e) => setOutput(e.target.value)} /><span /></div>
      <div className="row"><label>qualità</label>
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
      <div className="row"><label>formato</label>
        <select value={formato} onChange={(e) => setFormato(e.target.value)}>
          {FORMATI.map((f) => <option key={f.id} value={f.id}>{f.nome}</option>)}
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
      <div className="hint" style={{ marginTop: 10 }}>
        L'estensione decide il contenitore: .mp4 .mov .mkv .webm .gif .mp3 .wav<br />
        Esportando in un formato diverso da quello del progetto ({project?.settings?.resolution}),
        le clip con <b>inquadra: cover</b> riempiono tagliando ai lati; con <b>contain</b> restano le bande.
      </div>

      {job && (
        <div style={{ marginTop: 16 }}>
          <div className="progress"><div style={{ width: `${job.percent || 0}%` }} /></div>
          <div className="hint" style={{ marginTop: 7 }}>
            {job.state === 'done' && (
              <span style={{ color: 'var(--ok)' }}>
                fatto: {job.output} ({job.mb} MB, {job.encoder}, {job.seconds_total}s)
              </span>
            )}
            {job.state === 'error' && <span style={{ color: 'var(--danger)' }}>errore: {job.error}</span>}
            {job.state === 'running' &&
              `${(job.percent || 0).toFixed(1)}% · ${(job.seconds || 0).toFixed(1)}/${(job.duration || 0).toFixed(1)}s`}
          </div>
        </div>
      )}
    </Modal>
  )
}
