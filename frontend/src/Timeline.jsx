import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { clamp, fmt } from './util.js'

// Larghezza della colonna con i nomi delle tracce. Deve restare uguale a
// --tl-head in styles.css: righello, testina e clip si posizionano da qui.
const HEAD = 150
const SNAP_PX = 8        // tolleranza di aggancio

export default function Timeline({
  project, playhead, seek, pxPerSec, selected, setSelected, run, setError,
  onPreset, onTransition, trackH = 72,
}) {
  const scrollRef = useRef(null)
  const [drag, setDrag] = useState(null)   // modifica in corso, mostrata in anteprima
  const [strips, setStrips] = useState({}) // media id -> striscia di fotogrammi
  const [waves, setWaves] = useState({})   // media id -> picchi audio

  const duration = project?.duration || 0
  const width = Math.max(duration, 20) * pxPerSec + HEAD + 240

  // le tracce video si mostrano dall'alto verso il basso in ordine inverso:
  // l'ultima della lista e' quella disegnata sopra tutte
  const lanes = useMemo(() => {
    if (!project) return []
    const video = project.tracks.filter((t) => t.kind === 'video').reverse()
    const audio = project.tracks.filter((t) => t.kind === 'audio')
    return [...video, ...audio]
  }, [project])

  /**
   * Sposta una traccia di una posizione in su o in giu' *a schermo*.
   * Per il video le due cose sono invertite: in lista l'ultima e' quella
   * disegnata sopra, quindi salire di una riga significa alzare l'indice.
   */
  const shiftTrack = (track, up) => {
    const same = project.tracks.filter((t) => t.kind === track.kind)
    const i = same.findIndex((t) => t.id === track.id)
    const next = track.kind === 'video' ? (up ? i + 1 : i - 1) : (up ? i - 1 : i + 1)
    if (next < 0 || next >= same.length) return
    run('move_track', { track_id: track.id, index: next }).catch((e) => setError(e.message))
  }

  const soloOn = (kind) => project.tracks.some((t) => t.kind === kind && t.solo)

  // strisce e forme d'onda: una richiesta per media, poi solo CSS
  useEffect(() => {
    for (const m of project?.media || []) {
      if (m.kind !== 'audio' && strips[m.id] === undefined) {
        setStrips((s) => ({ ...s, [m.id]: null }))
        api.strip(m.id, 44).then((info) => setStrips((s) => ({ ...s, [m.id]: info?.url ? info : null })))
          .catch(() => {})
      }
      if (m.audio && waves[m.id] === undefined) {
        setWaves((w) => ({ ...w, [m.id]: null }))
        api.waveform(m.id).then((d) => setWaves((w) => ({ ...w, [m.id]: d })))
          .catch(() => {})
      }
    }
  }, [project?.media])

  const timeAt = useCallback((clientX) => {
    const el = scrollRef.current
    if (!el) return 0
    const rect = el.getBoundingClientRect()
    return Math.max(0, (clientX - rect.left + el.scrollLeft - HEAD) / pxPerSec)
  }, [pxPerSec])

  // ---- trascinamento di clip e maniglie di taglio -------------------------
  const startDrag = (e, clip, type) => {
    e.stopPropagation()
    e.preventDefault()
    setSelected(clip.id)
    const laneRects = Array.from(document.querySelectorAll('[data-lane]')).map((el) => ({
      id: el.dataset.lane, kind: el.dataset.kind, rect: el.getBoundingClientRect(),
    }))
    setDrag({
      type, id: clip.id, trackId: clip.trackId, kind: clip.kind,
      t0: timeAt(e.clientX),
      start: clip.start, duration: clip.duration, in: clip.in || 0,
      speed: clip.speed || 1,
      newStart: clip.start, newDuration: clip.duration, newIn: clip.in || 0,
      newTrack: clip.trackId, laneRects,
    })
  }

  useEffect(() => {
    if (!drag) return
    const snapPoints = []
    for (const t of project.tracks) {
      for (const c of t.clips) {
        if (c.id === drag.id) continue
        snapPoints.push(c.start, c.end)
      }
    }
    snapPoints.push(0, playhead)
    const snap = (v) => {
      const tol = SNAP_PX / pxPerSec
      let best = v, bestD = tol
      for (const p of snapPoints) {
        const d = Math.abs(p - v)
        if (d < bestD) { best = p; bestD = d }
      }
      return best
    }

    const onMove = (e) => {
      const dt = timeAt(e.clientX) - drag.t0
      setDrag((d) => {
        if (!d) return d
        const next = { ...d }
        if (d.type === 'move') {
          next.newStart = Math.max(0, snap(d.start + dt))
          const lane = d.laneRects.find(
            (l) => e.clientY >= l.rect.top && e.clientY <= l.rect.bottom && l.kind === d.kind)
          next.newTrack = lane ? lane.id : d.trackId
        } else if (d.type === 'trim-r') {
          next.newDuration = Math.max(0.05, snap(d.start + d.duration + dt) - d.start)
        } else {
          // il bordo sinistro consuma sorgente: cambiano start, durata e attacco
          const limit = d.start + d.duration - 0.05
          const ns = clamp(snap(d.start + dt), Math.max(0, d.start - d.in / d.speed), limit)
          const shift = ns - d.start
          next.newStart = ns
          next.newDuration = d.duration - shift
          next.newIn = Math.max(0, d.in + shift * d.speed)
        }
        return next
      })
    }

    const onUp = () => {
      setDrag((d) => {
        if (!d) return null
        const moved =
          Math.abs(d.newStart - d.start) > 1e-3 ||
          Math.abs(d.newDuration - d.duration) > 1e-3 ||
          d.newTrack !== d.trackId
        if (moved) {
          const args = d.type === 'move'
            ? { clip_id: d.id, start: round(d.newStart), track_id: d.newTrack }
            : { clip_id: d.id, start: round(d.newStart), duration: round(d.newDuration), in_: round(d.newIn) }
          const opName = d.type === 'move' ? 'move_clip' : 'set_clip'
          run(opName, args).catch((err) => setError(err.message))
        }
        return null
      })
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp, { once: true })
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [drag?.id, drag?.type, pxPerSec, project, playhead, run, setError, timeAt])

  // ---- righello ------------------------------------------------------------
  const scrub = (e) => {
    seek(timeAt(e.clientX))
    const onMove = (ev) => seek(timeAt(ev.clientX))
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', () => window.removeEventListener('pointermove', onMove), { once: true })
  }

  const ticks = useMemo(() => {
    const target = 90 / pxPerSec   // circa una tacca ogni 90px
    const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
    const step = steps.find((s) => s >= target) || 600
    const out = []
    for (let t = 0; t <= Math.max(duration, 20) + step; t += step) out.push(t)
    return out
  }, [pxPerSec, duration])

  if (!project) return <div className="timeline" />

  const mediaById = Object.fromEntries((project.media || []).map((m) => [m.id, m]))

  return (
    <div className="timeline">
      <div className="tl-scroll" ref={scrollRef}>
        <div className="tl-inner" style={{ width }}>
          <div className="ruler" style={{ width }} onPointerDown={scrub}>
            {/* copre le tacche che scorrerebbero sotto la colonna dei nomi */}
            <div className="corner" />
            {ticks.map((t) => (
              <div key={t} className="tick" style={{ left: HEAD + t * pxPerSec }}>
                <span>{fmt(t)}</span>
              </div>
            ))}
          </div>

          {lanes.map((track) => {
            const off = track.kind === 'video' ? track.hidden : track.muted
            // con un solo attivo altrove la traccia non finisce nel render
            const silenced = !track.solo && soloOn(track.kind)
            const set = (patch) => run('set_track', { track_id: track.id, ...patch })
              .catch((e) => setError(e.message))
            // sotto una certa altezza i controlli non ci starebbero: si tiene
            // il nome e i pulsanti essenziali, cosi' 20 tracce restano leggibili
            const compact = trackH < 62
            return (
            <div key={track.id}
              style={{ height: track.kind === 'audio' ? Math.round(trackH * 0.85) : trackH }}
              className={`track ${track.kind} ${compact ? 'compact' : ''}`
                + `${off || silenced ? ' off' : ''}${track.locked ? ' locked' : ''}`}>
              <div className="track-head">
                <div className="trow">
                  <span className="tname" title="doppio clic per rinominare"
                    onDoubleClick={() => {
                      const name = prompt('Nome della traccia', track.name || track.id)
                      if (name !== null) set({ name: name.trim() })
                    }}>{track.name || track.id}</span>
                  <span className="spacer" />
                  <button title="sposta in su" disabled={lanes[0]?.id === track.id}
                    onClick={() => shiftTrack(track, true)}>▲</button>
                  <button title="sposta in giu'"
                    disabled={lanes[lanes.length - 1]?.id === track.id}
                    onClick={() => shiftTrack(track, false)}>▼</button>
                </div>
                <div className="trow">
                  <button className={off ? '' : 'on'}
                    title={track.kind === 'video' ? 'mostra/nascondi' : 'attiva/silenzia'}
                    onClick={() => set(track.kind === 'video'
                      ? { hidden: !track.hidden } : { muted: !track.muted })}
                  >{track.kind === 'video' ? '👁' : '🔊'}</button>
                  <button className={track.solo ? 'solo' : ''}
                    title="solo: isola questa traccia"
                    onClick={() => set({ solo: !track.solo })}>S</button>
                  <button className={track.locked ? 'lock' : ''}
                    title={track.locked ? 'traccia bloccata: clic per sbloccare'
                      : 'blocca: protegge le clip dalle modifiche'}
                    onClick={() => set({ locked: !track.locked })}>{track.locked ? '🔒' : '🔓'}</button>
                  <span className="spacer" />
                  <button title="elimina traccia" disabled={track.locked}
                    onClick={() => {
                      if (track.clips.length && !confirm(
                        `${track.name || track.id} ha ${track.clips.length} clip. Eliminare la traccia?`)) return
                      run('remove_track', { track_id: track.id }).catch((e) => setError(e.message))
                    }}>✕</button>
                </div>
                <input
                  className="tvol" type="range" min="0" max="2" step="0.05"
                  value={typeof track.volume === 'number' ? track.volume : 1}
                  title={`volume traccia ${Math.round((track.volume ?? 1) * 100)}%`}
                  onChange={(e) => set({ volume: +e.target.value })}
                />
              </div>

              <div
                className="lane"
                data-lane={track.id}
                data-kind={track.kind}
                onPointerDown={(e) => { if (e.target.classList.contains('lane')) setSelected(null) }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault()
                  const mediaId = e.dataTransfer.getData('text/media')
                  if (!mediaId) return
                  const inPoint = parseFloat(e.dataTransfer.getData('text/inpoint'))
                  const length = parseFloat(e.dataTransfer.getData('text/length'))
                  const args = { media_id: mediaId, track_id: track.id, start: round(timeAt(e.clientX)) }
                  if (!Number.isNaN(inPoint)) args.in_ = round(inPoint)
                  if (!Number.isNaN(length)) args.duration = round(length)
                  run('add_clip', args).catch((err) => setError(err.message))
                }}
              >
                {track.clips.map((clip) => {
                  const live = drag && drag.id === clip.id
                  const start = live ? drag.newStart : clip.start
                  const dur = live ? drag.newDuration : clip.duration
                  const inPoint = live ? drag.newIn : (clip.in || 0)
                  if (live && drag.type === 'move' && drag.newTrack !== track.id) return null
                  const w = Math.max(6, dur * pxPerSec)
                  const media = mediaById[clip.media]
                  return (
                    <div
                      key={clip.id}
                      className={[
                        'clip', track.kind === 'audio' ? 'audio' : '',
                        clip.type === 'text' ? 'text' : '', clip.type === 'color' ? 'color' : '',
                        clip.enabled === false ? 'disabled' : '',
                        selected === clip.id ? 'sel' : '',
                      ].join(' ')}
                      style={{
                        left: start * pxPerSec, width: w,
                        ...stripStyle(strips[clip.media], clip, inPoint, pxPerSec, track.kind),
                      }}
                      onPointerDown={(e) => startDrag(e, { ...clip, trackId: track.id, kind: track.kind }, 'move')}
                      onDragOver={(e) => {
                        // preset e transizioni dalla libreria si lasciano sulla clip
                        const t = e.dataTransfer.types
                        if (t.includes('text/preset') || t.includes('text/transition')) {
                          e.preventDefault(); e.stopPropagation()
                        }
                      }}
                      onDrop={(e) => {
                        const preset = e.dataTransfer.getData('text/preset')
                        const trans = e.dataTransfer.getData('text/transition')
                        if (!preset && !trans) return
                        e.preventDefault(); e.stopPropagation()
                        setSelected(clip.id)
                        if (preset) onPreset?.(preset, clip.id)
                        else onTransition?.(trans, parseFloat(e.dataTransfer.getData('text/duration')) || 1, clip.id)
                      }}
                    >
                      <div className="handle l" onPointerDown={(e) =>
                        startDrag(e, { ...clip, trackId: track.id, kind: track.kind }, 'trim-l')} />

                      {track.kind === 'audio' && media?.audio && (
                        <Wave peaks={waves[clip.media]?.peaks} media={media}
                          inPoint={inPoint} span={dur * (clip.speed || 1)} />
                      )}

                      <div className="label">{clip.name || clip.type}</div>
                      <div className="tags">
                        {clip.speed && Math.abs(clip.speed - 1) > 1e-6 ? `${clip.speed}x ` : ''}
                        {clip.effects?.length ? `fx${clip.effects.length} ` : ''}
                        {dur.toFixed(2)}s
                      </div>

                      {clip.fade_in > 0 && (
                        <div className="fade" style={{ left: 0, width: clip.fade_in * pxPerSec }} />
                      )}
                      {clip.fade_out > 0 && (
                        <div className="fade out" style={{ right: 0, width: clip.fade_out * pxPerSec }} />
                      )}
                      {clip.transition?.duration > 0 && (
                        <div className="trans" style={{ width: clip.transition.duration * pxPerSec }}
                          title={`transizione ${clip.transition.type}`}>
                          {clip.transition.duration * pxPerSec > 46 ? TR_LABEL[clip.transition.type] || '⤫' : '⤫'}
                        </div>
                      )}

                      <div className="handle r" onPointerDown={(e) =>
                        startDrag(e, { ...clip, trackId: track.id, kind: track.kind }, 'trim-r')} />
                    </div>
                  )
                })}

                {/* anteprima della clip trascinata su un'altra traccia */}
                {drag && drag.type === 'move' && drag.newTrack === track.id &&
                  drag.trackId !== track.id && (
                    <div className="clip sel" style={{
                      left: drag.newStart * pxPerSec,
                      width: Math.max(6, drag.newDuration * pxPerSec), opacity: .7,
                    }} />
                  )}
              </div>
            </div>
            )
          })}

          {/* le tracce non hanno un numero fisso: si aggiungono da qui, dove si
              guarda quando ne serve una in piu' */}
          <div className="track addtrack">
            <div className="track-head">
              <button onClick={() => run('add_track', { kind: 'video' })
                .catch((e) => setError(e.message))} title="nuova traccia video">+ video</button>
              <button onClick={() => run('add_track', { kind: 'audio' })
                .catch((e) => setError(e.message))} title="nuova traccia audio">+ audio</button>
            </div>
            <div className="lane addhint hint">
              {project.tracks.filter((t) => t.kind === 'video').length} video ·{' '}
              {project.tracks.filter((t) => t.kind === 'audio').length} audio
            </div>
          </div>

          <div className="playhead" style={{ left: HEAD + playhead * pxPerSec }} />
        </div>
      </div>
    </div>
  )
}

const TR_LABEL = {
  dissolve: 'dissolvenza', iris: 'iris',
  wipe_right: 'tendina ▸', wipe_left: '◂ tendina',
  wipe_down: 'tendina ▾', wipe_up: 'tendina ▴',
  slide_left: 'scorri ◂', slide_right: 'scorri ▸',
  slide_up: 'scorri ▴', slide_down: 'scorri ▾',
}

/**
 * La striscia di fotogrammi e' un'unica immagine per media: qui si calcola
 * quale finestra mostrarne, in base al punto di attacco, alla velocita' e allo
 * zoom. Nessuna richiesta in piu' quando si sposta o si zooma.
 */
function stripStyle(strip, clip, inPoint, pxPerSec, kind) {
  if (!strip || kind === 'audio' || clip.type !== 'media') return {}
  const speed = Math.abs(clip.speed || 1)
  const mediaDur = strip.tiles * strip.interval
  return {
    backgroundImage: `url(${strip.url})`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${(mediaDur * pxPerSec) / speed}px 100%`,
    backgroundPosition: `${(-inPoint * pxPerSec) / speed}px center`,
  }
}

/** Forma d'onda in SVG: si adatta alla larghezza senza essere ridisegnata. */
function Wave({ peaks, media, inPoint, span }) {
  if (!peaks?.length || !media?.duration) return null
  const from = Math.max(0, Math.floor((inPoint / media.duration) * peaks.length))
  const to = Math.min(peaks.length, Math.ceil(((inPoint + span) / media.duration) * peaks.length))
  const slice = peaks.slice(from, Math.max(from + 2, to))
  const step = Math.max(1, Math.floor(slice.length / 600))   // al massimo ~600 punti
  const pts = []
  for (let i = 0; i < slice.length; i += step) pts.push(slice[i])
  const d = pts.map((v, i) => `${i},${50 - v * 46}`).join(' ') +
    ' ' + pts.map((v, i) => `${pts.length - 1 - i},${50 + pts[pts.length - 1 - i] * 46}`).join(' ')
  return (
    <svg className="wave" viewBox={`0 0 ${Math.max(1, pts.length - 1)} 100`} preserveAspectRatio="none">
      <polygon points={d} />
    </svg>
  )
}

const round = (v) => Math.round(v * 1000) / 1000
