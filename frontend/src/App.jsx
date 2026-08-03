import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectEvents } from './api.js'
import Chat from './Chat.jsx'
import { FileBrowser, NewProject, RenderDialog } from './Dialogs.jsx'
import Inspector from './Inspector.jsx'
import Library from './Library.jsx'
import MediaBin from './MediaBin.jsx'
import Preview from './Preview.jsx'
import SourceMonitor from './SourceMonitor.jsx'
import Timeline from './Timeline.jsx'
import { clamp, findClip, fmt } from './util.js'

const MEDIA_EXT = /\.(mp4|mov|mkv|avi|webm|m4v|mpe?g|wmv|flv|ts|mp3|wav|aac|m4a|flac|ogg|opus|png|jpe?g|webp|bmp|tiff?)$/i

// le misure dei pannelli restano tra una sessione e l'altra
const loadSizes = () => {
  try { return JSON.parse(localStorage.getItem('vedit.layout')) || {} } catch { return {} }
}

export default function App() {
  const [sys, setSys] = useState(null)
  const [project, setProject] = useState(null)
  const [path, setPath] = useState(null)
  const [revision, setRevision] = useState('0')
  const [selected, setSelected] = useState(null)
  const [playhead, setPlayhead] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [pxPerSec, setPxPerSec] = useState(70)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [dialog, setDialog] = useState(null)     // 'new' | 'open' | 'import' | 'render'
  const [job, setJob] = useState(null)
  const [source, setSource] = useState(null)     // media aperto nel monitor
  const [tab, setTab] = useState('program')      // program | source
  const [leftTab, setLeftTab] = useState('media')      // media | libreria
  const [rightTab, setRightTab] = useState('props')    // props | chat
  const [uploading, setUploading] = useState(null)
  const [dropping, setDropping] = useState(false)
  const [sizes, setSizes] = useState(() => ({
    bin: 250, inspector: 320, timeline: 300, trackH: 72, ...loadSizes(),
  }))
  const playheadRef = useRef(0)

  useEffect(() => {
    localStorage.setItem('vedit.layout', JSON.stringify(sizes))
  }, [sizes])

  // ---- stato iniziale ed eventi dal server --------------------------------
  useEffect(() => {
    api.state().then((s) => {
      setSys(s)
      setProject(s.project)
      setPath(s.path)
      setRevision(s.revision)
    }).catch((e) => setError(e.message))

    return connectEvents((ev) => {
      if (ev.type === 'render') setJob(ev.job)
      if (ev.type === 'proxies') {
        // anche in caso di errore: altrimenti l'avviso "genero i proxy" resta li' per sempre
        setBusy(null)
        if (ev.state === 'error') setError(`proxy non riusciti: ${ev.error}`)
      }
    })
  }, [])

  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 6000)
    return () => clearTimeout(t)
  }, [error])

  // avviso che sparisce da solo (le operazioni lunghe usano setBusy direttamente)
  const flash = useCallback((msg, ms = 2500) => {
    setBusy(msg)
    setTimeout(() => setBusy((b) => (b === msg ? null : b)), ms)
  }, [])

  // ---- operazioni ----------------------------------------------------------
  const run = useCallback(async (op, args) => {
    const res = await api.op(op, args)
    setProject(res.project)
    setRevision(res.revision)
    return res.result
  }, [])

  const seek = useCallback((t, fromPlayer = false) => {
    const dur = project?.duration || 0
    const v = clamp(t, 0, Math.max(0, dur))
    playheadRef.current = v
    setPlayhead(v)
    if (!fromPlayer && playing) setPlaying(false)
  }, [project?.duration, playing])

  const selectedClip = project && selected ? findClip(project, selected) : null

  // ---- libreria -------------------------------------------------------------
  const applyState = (r) => { setProject(r.project); setRevision(r.revision) }

  const applyPreset = useCallback((presetId, clipId) =>
    api.applyPreset(presetId, clipId).then(applyState).catch((e) => setError(e.message)), [])

  /**
   * Una transizione ha bisogno di sovrapposizione: se la clip dopo e' attaccata
   * la si accosta (crossfade), altrimenti si scopre lo sfondo (set_transition).
   */
  const applyTransition = useCallback((type, duration, clipId) => {
    const id = clipId ?? selected
    if (!project || !id) { setError('seleziona prima una clip'); return }
    const clip = findClip(project, id)
    if (!clip) return
    const track = project.tracks.find((t) => t.clips.some((c) => c.id === id))
    const next = track?.clips
      .filter((c) => c.start >= clip.end - 1e-6 && c.id !== id)
      .sort((a, b) => a.start - b.start)[0]
    const dur = Math.min(duration, clip.duration)
    if (next && Math.abs(next.start - clip.end) < 1e-3) {
      run('crossfade', { clip_a: id, clip_b: next.id, duration: dur, type })
        .catch((e) => setError(e.message))
    } else {
      run('set_transition', { clip_id: id, type, duration: dur }).catch((e) => setError(e.message))
    }
  }, [project, selected, run])

  // ---- import ---------------------------------------------------------------
  const importPaths = (paths) =>
    run('import_media', { paths }).catch((e) => setError(e.message))

  const importFiles = async (fileList, folder = '') => {
    if (!fileList) { setDialog('import'); return }
    const files = [...fileList].filter((f) => MEDIA_EXT.test(f.name))
    if (!files.length) { setError('nessun file multimediale riconosciuto'); return }
    const mb = files.reduce((s, f) => s + f.size, 0) / 1e6
    setUploading(`${files.length} file, ${mb.toFixed(0)} MB`)
    try {
      const res = await api.upload(files, folder)
      setProject(res.project)
      setRevision(res.revision)
    } catch (e) { setError(e.message) } finally { setUploading(null) }
  }

  // ---- scorciatoie da tastiera --------------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const step = 1 / (project?.settings?.fps || 30)
      const act = {
        ' ': () => setPlaying((p) => !p),
        ArrowLeft: () => seek(playheadRef.current - (e.shiftKey ? 1 : step)),
        ArrowRight: () => seek(playheadRef.current + (e.shiftKey ? 1 : step)),
        Home: () => seek(0),
        End: () => seek(project?.duration || 0),
        s: () => selected && run('split_clip', { clip_id: selected, at: playheadRef.current })
          .catch((err) => setError(err.message)),
        Delete: () => selected && run('remove_clip', { clip_id: selected, ripple: e.shiftKey })
          .then(() => setSelected(null)).catch((err) => setError(err.message)),
        '+': () => setPxPerSec((p) => clamp(p * 1.25, 8, 600)),
        '-': () => setPxPerSec((p) => clamp(p / 1.25, 8, 600)),
      }
      if (e.ctrlKey && e.key.toLowerCase() === 'z') {
        e.preventDefault(); run('undo').catch((err) => setError(err.message)); return
      }
      if (e.ctrlKey && e.key.toLowerCase() === 'y') {
        e.preventDefault(); run('redo').catch((err) => setError(err.message)); return
      }
      const fn = act[e.key]
      if (fn) { e.preventDefault(); fn() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [project, selected, run, seek])

  const startRender = (body) =>
    api.render(body).then(setJob).catch((e) => setError(e.message))

  return (
    <div
      className={`app ${dropping ? 'dropping' : ''}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDropping(true) }
      }}
      onDragLeave={(e) => {
        // relatedTarget nullo = il puntatore ha lasciato la finestra: senza questo
        // controllo il riquadro blu resta acceso quando il trascinamento finisce fuori
        if (!e.relatedTarget || (e.clientX === 0 && e.clientY === 0)) setDropping(false)
      }}
      onDragEnd={() => setDropping(false)}
      onDrop={(e) => {
        if (!e.dataTransfer.files?.length) return
        e.preventDefault()
        setDropping(false)
        importFiles(e.dataTransfer.files)
      }}
    >
      <div className="topbar">
        <span className="name">vedit</span>
        <button onClick={() => setDialog('new')}>nuovo</button>
        <button onClick={() => setDialog('open')}>apri</button>
        <button disabled={!project} onClick={() => run('save', {})
          .then(() => flash('progetto salvato')).catch((e) => setError(e.message))}>salva</button>
        <span style={{ width: 10 }} />
        <button disabled={!project} title="Ctrl+Z"
          onClick={() => run('undo').catch((e) => setError(e.message))}>↶</button>
        <button disabled={!project} title="Ctrl+Y"
          onClick={() => run('redo').catch((e) => setError(e.message))}>↷</button>
        <span style={{ width: 10 }} />
        <button disabled={!project} onClick={() => run('add_track', { kind: 'video' })}>+ video</button>
        <button disabled={!project} onClick={() => run('add_track', { kind: 'audio' })}>+ audio</button>
        <button disabled={!project} onClick={() =>
          run('add_text', { text: 'Testo', start: playhead, duration: 3 })
            .then((c) => setSelected(c.id)).catch((e) => setError(e.message))}>+ testo</button>
        <span className="spacer" />
        <span className="path">{path || 'nessun progetto'}</span>
        <button disabled={!project} onClick={() => { setBusy('genero i proxy…'); api.buildProxies() }}>
          proxy
        </button>
        <button className="primary" disabled={!project || !project.duration}
          onClick={() => setDialog('render')}>esporta</button>
      </div>

      <div className="middle">
        <div style={{ width: sizes.bin, flex: 'none', display: 'flex', minWidth: 0 }}>
          <div className="panel">
            <div className="tabs">
              <button className={leftTab === 'media' ? 'on' : ''}
                onClick={() => setLeftTab('media')}>media</button>
              <button className={leftTab === 'libreria' ? 'on' : ''}
                onClick={() => setLeftTab('libreria')}>libreria</button>
            </div>
            {leftTab === 'media' ? (
              <MediaBin project={project} run={run} setError={setError} uploading={uploading}
                onImport={importFiles}
                onOpenSource={(m) => { setSource(m); setTab('source') }} />
            ) : (
              <Library library={sys?.library} clip={selectedClip} setError={setError}
                onPreset={applyPreset}
                onTransition={(type, dur) => applyTransition(type, dur)} />
            )}
          </div>
        </div>
        <Divider onDrag={(dx) => setSizes((s) => ({ ...s, bin: clamp(s.bin + dx, 170, 520) }))} />

        <div className="center">
          <div className="tabs">
            <button className={tab === 'program' ? 'on' : ''} onClick={() => setTab('program')}>
              programma
            </button>
            <button className={tab === 'source' ? 'on' : ''} disabled={!source}
              onClick={() => setTab('source')}>
              sorgente{source ? `: ${source.name}` : ''}
            </button>
            <span className="spacer" />
            {selectedClip && !playing && tab === 'program' && (
              <span className="hint">trascina l'immagine per spostare la clip selezionata</span>
            )}
          </div>

          {tab === 'source' && source ? (
            <SourceMonitor media={source} tracks={project?.tracks || []} run={run}
              setError={setError} playhead={playhead}
              onClose={() => { setSource(null); setTab('program') }} />
          ) : (
            <Preview project={project} revision={revision} playhead={playhead} seek={seek}
              playing={playing} setPlaying={setPlaying} clip={selectedClip}
              run={run} setError={setError} />
          )}

          <div className="transport">
            <button onClick={() => setPlaying((p) => !p)} disabled={!project?.duration}>
              {playing ? '⏸' : '▶'}
            </button>
            <button onClick={() => seek(0)} disabled={!project}>⏮</button>
            <span className="time">
              <b>{fmt(playhead)}</b> / {fmt(project?.duration || 0)}
            </span>
            <span className="spacer" />
            {selectedClip && (
              <>
                <button onClick={() => run('split_clip', { clip_id: selected, at: playhead })
                  .catch((e) => setError(e.message))} title="taglia alla testina (S)">✂ taglia</button>
                <button onClick={() => run('remove_clip', { clip_id: selected })
                  .then(() => setSelected(null)).catch((e) => setError(e.message))}>elimina</button>
              </>
            )}
            <span className="hint">zoom</span>
            <input type="range" min="8" max="400" value={pxPerSec} style={{ width: 130 }}
              onChange={(e) => setPxPerSec(+e.target.value)} />
            <span className="hint">tracce</span>
            <input type="range" min="34" max="140" step="2" value={sizes.trackH}
              style={{ width: 90 }} title="altezza delle tracce: abbassala per vederne di piu'"
              onChange={(e) => setSizes((s) => ({ ...s, trackH: +e.target.value }))} />
          </div>

          <Divider horizontal
            onDrag={(dy) => setSizes((s) => ({ ...s, timeline: clamp(s.timeline - dy, 120, 1400) }))} />
          <div style={{ height: sizes.timeline, flex: 'none', display: 'flex', minHeight: 0 }}>
            <Timeline project={project} playhead={playhead} seek={seek} pxPerSec={pxPerSec}
              selected={selected} setSelected={setSelected} run={run} setError={setError}
              onPreset={applyPreset} onTransition={applyTransition} trackH={sizes.trackH} />
          </div>
        </div>

        <Divider onDrag={(dx) => setSizes((s) => ({ ...s, inspector: clamp(s.inspector - dx, 240, 600) }))} />
        <div style={{ width: sizes.inspector, flex: 'none', display: 'flex', minWidth: 0 }}>
          <div className="panel">
            <div className="tabs">
              <button className={rightTab === 'props' ? 'on' : ''}
                onClick={() => setRightTab('props')}>proprieta'</button>
              <button className={rightTab === 'chat' ? 'on' : ''}
                onClick={() => setRightTab('chat')}>assistente</button>
            </div>
            {rightTab === 'props' ? (
              <Inspector project={project} effects={sys?.effects || []}
                transitions={sys?.transitions || []} clip={selectedClip}
                playhead={playhead} run={run} setError={setError} setBusy={setBusy} />
            ) : (
              <Chat available={sys?.chat} setError={setError}
                onProject={(p, r) => { setProject(p); setRevision(r) }} />
            )}
          </div>
        </div>
      </div>

      {dialog === 'new' && (
        <NewProject presets={sys?.presets || ['1080p']} onClose={() => setDialog(null)}
          onCreate={(p, name, preset) => api.createProject(p, name, preset)
            .then((r) => { setProject(r.project); setPath(r.path); setSelected(null) })
            .catch((e) => setError(e.message))} />
      )}
      {dialog === 'open' && (
        <FileBrowser title="Apri progetto" multiple={false} onClose={() => setDialog(null)}
          filter={(n) => n.toLowerCase().endsWith('.json')}
          onPick={([p]) => api.openProject(p)
            .then((r) => { setProject(r.project); setPath(r.path); setSelected(null); setPlayhead(0) })
            .catch((e) => setError(e.message))} />
      )}
      {dialog === 'import' && (
        <FileBrowser title="Importa file" onClose={() => setDialog(null)}
          filter={(n) => MEDIA_EXT.test(n)} onPick={importPaths} />
      )}
      {dialog === 'render' && (
        <RenderDialog project={project} job={job} onStart={startRender}
          onClose={() => setDialog(null)} />
      )}

      {dropping && <div className="dropzone">rilascia qui i file da importare</div>}
      {busy && <div className="toast ok">{busy}</div>}
      {error && <div className="toast" onClick={() => setError(null)}>{error}</div>}
    </div>
  )
}

/** Divisore trascinabile tra due pannelli. */
function Divider({ onDrag, horizontal }) {
  const down = (e) => {
    e.preventDefault()
    let last = horizontal ? e.clientY : e.clientX
    const move = (ev) => {
      const now = horizontal ? ev.clientY : ev.clientX
      onDrag(now - last)
      last = now
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', () => window.removeEventListener('pointermove', move), { once: true })
  }
  return <div className={`divider ${horizontal ? 'h' : 'v'}`} onPointerDown={down} />
}
