import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import useMediaAssets from './mediaAssets.js'
import { clamp, fmt } from './util.js'

// Larghezza della colonna con i nomi delle tracce. Deve restare uguale a
// --tl-head in styles.css: righello, testina e clip si posizionano da qui.
const HEAD = 150
const SNAP_PX = 8        // tolleranza di aggancio

export default function Timeline({
  project, playhead, seek, pxPerSec, selected, setSelected, run, setError,
  onPreset, onTransition, trackH = 72, ask,
}) {
  const scrollRef = useRef(null)
  const [drag, setDrag] = useState(null)   // modifica in corso, mostrata in anteprima
  // il rilascio legge qui: leggere lo stato dentro un aggiornatore significa
  // mettere un effetto collaterale dove React puo' rieseguirlo
  const dragRef = useRef(null)

  // strisce e forme d'onda arrivano dalla cache condivisa con il pannello media:
  // sono gli stessi file, e dietro la forma d'onda c'e' la decodifica dell'audio
  const assets = useMediaAssets(project?.media)
  const [renaming, setRenaming] = useState(null)   // id della traccia in rinomina
  const [giunzione, setGiunzione] = useState(null) // stacco sotto una transizione trascinata

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
  // useCallback non e' decorazione: queste finiscono fra le dipendenze del memo
  // che disegna le tracce. Ricreate a ogni render lo invaliderebbero sempre.
  const shiftTrack = useCallback((track, up) => {
    const same = project.tracks.filter((t) => t.kind === track.kind)
    const i = same.findIndex((t) => t.id === track.id)
    const next = track.kind === 'video' ? (up ? i + 1 : i - 1) : (up ? i - 1 : i + 1)
    if (next < 0 || next >= same.length) return
    run('move_track', { track_id: track.id, index: next }).catch((e) => setError(e.message))
  }, [project, run, setError])

  /**
   * Gli stacchi fra due clip attaccate.
   *
   * Sono il punto in cui si lascia una transizione, come negli altri montaggi:
   * prima bisognava selezionare la clip e poi applicarla, e non era ovvio che
   * la transizione fosse *della clip che finisce*.
   */
  const giunzioni = useCallback((track) => {
    const ordinate = [...track.clips].sort((a, b) => a.start - b.start)
    const out = []
    for (let i = 0; i < ordinate.length - 1; i++) {
      const a = ordinate[i]
      const b = ordinate[i + 1]
      if (Math.abs(b.start - a.end) > 0.001) continue   // c'e' un buco: niente stacco
      out.push({ id: `${a.id}|${b.id}`, t: a.end, clip: a.id })
    }
    return out
  }, [])

  const soloOn = useCallback(
    (kind) => project.tracks.some((t) => t.kind === kind && t.solo), [project])

  useEffect(() => { dragRef.current = drag }, [drag])

  const timeAt = useCallback((clientX) => {
    const el = scrollRef.current
    if (!el) return 0
    const rect = el.getBoundingClientRect()
    return Math.max(0, (clientX - rect.left + el.scrollLeft - HEAD) / pxPerSec)
  }, [pxPerSec])

  // ---- trascinamento di clip e maniglie di taglio -------------------------
  const startDrag = useCallback((e, clip, type) => {
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
  }, [setSelected, timeAt])

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

    /**
     * Aggancio ai bordi vicini.
     *
     * La tolleranza nasce in pixel, ma va usata in secondi: allontanando lo
     * zoom quegli otto pixel diventavano quasi un secondo, e su una timeline
     * fitta di stacchi ogni posizione finiva agganciata a qualcosa — la clip
     * non si riusciva piu' a mettere dove si voleva. Il tetto di 0.25 s tiene
     * l'aggancio utile da vicino e innocuo da lontano. Alt lo disattiva del
     * tutto, come negli altri montaggi.
     */
    const snap = (v, libero) => {
      if (libero) return v
      const tol = Math.min(0.25, SNAP_PX / pxPerSec)
      let best = v, bestD = tol
      for (const p of snapPoints) {
        const d = Math.abs(p - v)
        if (d < bestD) { best = p; bestD = d }
      }
      return best
    }

    const corsie = () => Array.from(document.querySelectorAll('[data-lane]')).map((el) => ({
      id: el.dataset.lane, kind: el.dataset.kind, rect: el.getBoundingClientRect(),
    }))

    const onMove = (e) => {
      const libero = e.altKey
      const dt = timeAt(e.clientX) - drag.t0
      setDrag((d) => {
        if (!d) return d
        const next = { ...d }
        if (d.type === 'move') {
          next.newStart = Math.max(0, snap(d.start + dt, libero))
          const lane = corsie().find(
            (l) => e.clientY >= l.rect.top && e.clientY <= l.rect.bottom && l.kind === d.kind)
          next.newTrack = lane ? lane.id : d.trackId
        } else if (d.type === 'trim-r') {
          next.newDuration = Math.max(0.05, snap(d.start + d.duration + dt, libero) - d.start)
        } else {
          // il bordo sinistro consuma sorgente: cambiano start, durata e attacco
          const limit = d.start + d.duration - 0.05
          const ns = clamp(snap(d.start + dt, libero), Math.max(0, d.start - d.in / d.speed), limit)
          const shift = ns - d.start
          next.newStart = ns
          next.newDuration = d.duration - shift
          next.newIn = Math.max(0, d.in + shift * d.speed)
        }
        return next
      })
    }

    const onUp = () => {
      const d = dragRef.current
      setDrag(null)
      if (!d) return
      const moved =
        Math.abs(d.newStart - d.start) > 1e-3 ||
        Math.abs(d.newDuration - d.duration) > 1e-3 ||
        d.newTrack !== d.trackId
      if (!moved) return
      const args = d.type === 'move'
        ? { clip_id: d.id, start: round(d.newStart), track_id: d.newTrack }
        : { clip_id: d.id, start: round(d.newStart), duration: round(d.newDuration), in_: round(d.newIn) }
      run(d.type === 'move' ? 'move_clip' : 'set_clip', args).catch((err) => setError(err.message))
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

  const mediaById = useMemo(
    () => Object.fromEntries((project?.media || []).map((m) => [m.id, m])),
    [project?.media])

  /**
   * Il corpo della timeline (tracce, clip, strisce di fotogrammi, forme d'onda)
   * non dipende dalla posizione della testina: quella muove solo una riga
   * verticale. Tenerlo in un memo a parte evita di ricostruire l'intero albero
   * a ogni `pointermove` — su questo progetto sono 59 clip con immagini e SVG
   * ridisegnate un centinaio di volte al secondo durante uno scrub, ed era il
   * motivo per cui la timeline si impastava.
   */
  const corpo = useMemo(() => {
    if (!project) return null
    return (
      <>
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
            // stessa altezza per video e audio: la testata ha gli stessi comandi
            // in entrambi i casi, quindi una traccia piu' bassa non li conterrebbe
            <div key={track.id}
              style={{ height: trackH }}
              className={`track ${track.kind} ${compact ? 'compact' : ''}`
                + `${off || silenced ? ' off' : ''}${track.locked ? ' locked' : ''}`}>
              <div className="track-head">
                <div className="trow">
                  {renaming === track.id ? (
                    <input
                      className="rename" autoFocus defaultValue={track.name || track.id}
                      onBlur={(e) => { set({ name: e.target.value.trim() }); setRenaming(null) }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.currentTarget.blur()
                        if (e.key === 'Escape') setRenaming(null)
                      }} />
                  ) : (
                    <span className="tname" title="Doppio clic per rinominare"
                      onDoubleClick={() => setRenaming(track.id)}>{track.name || track.id}</span>
                  )}
                  <button className="icon sm" title="Sposta in su"
                    disabled={lanes[0]?.id === track.id}
                    onClick={() => shiftTrack(track, true)}><Icon name="su" size={13} /></button>
                  <button className="icon sm" title="Sposta in giù"
                    disabled={lanes[lanes.length - 1]?.id === track.id}
                    onClick={() => shiftTrack(track, false)}><Icon name="giu" size={13} /></button>
                </div>
                <div className="trow">
                  <button className={`icon sm ${off ? '' : 'on'}`}
                    title={track.kind === 'video'
                      ? (track.hidden ? 'Traccia nascosta: clic per mostrarla' : 'Nascondi la traccia')
                      : (track.muted ? 'Traccia silenziata: clic per riattivarla' : 'Silenzia la traccia')}
                    onClick={() => set(track.kind === 'video'
                      ? { hidden: !track.hidden } : { muted: !track.muted })}>
                    <Icon size={14} name={track.kind === 'video'
                      ? (track.hidden ? 'occhioNo' : 'occhio')
                      : (track.muted ? 'altoparlanteNo' : 'altoparlante')} />
                  </button>
                  <button className={`icon sm ${track.solo ? 'solo' : ''}`}
                    title={track.solo ? 'Solo attivo: clic per togliere' : 'Solo: isola questa traccia'}
                    onClick={() => set({ solo: !track.solo })}
                    style={{ fontSize: 10, fontWeight: 700 }}>S</button>
                  <button className={`icon sm ${track.locked ? 'lock' : ''}`}
                    title={track.locked ? 'Traccia bloccata: clic per sbloccare'
                      : 'Blocca: protegge le clip dalle modifiche'}
                    onClick={() => set({ locked: !track.locked })}>
                    <Icon size={14} name={track.locked ? 'lucchetto' : 'lucchettoAperto'} />
                  </button>
                  <span className="spacer" />
                  <button className="icon sm danger" title="Elimina la traccia" disabled={track.locked}
                    onClick={() => {
                      if (!track.clips.length) {
                        run('remove_track', { track_id: track.id }).catch((e) => setError(e.message))
                        return
                      }
                      ask({
                        title: 'Eliminare la traccia?',
                        message: `${track.name || track.id} contiene ${track.clips.length} clip. `
                          + 'Verranno eliminate insieme alla traccia.',
                        ok: 'elimina', danger: true,
                        onOk: () => run('remove_track', { track_id: track.id })
                          .catch((e) => setError(e.message)),
                      })
                    }}><Icon name="cestino" size={13} /></button>
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
                        ...stripStyle(assets.strip(media), clip, inPoint, pxPerSec, track.kind),
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
                        <Wave peaks={assets.peaks(media)} media={media}
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
                {/* bersagli per le transizioni lasciate sullo stacco */}
                {track.kind === 'video' && giunzioni(track).map((g) => (
                  <div
                    key={g.id}
                    className={`giunzione ${giunzione === g.id ? 'on' : ''}`}
                    style={{ left: g.t * pxPerSec }}
                    title="lascia qui una transizione"
                    onDragOver={(e) => {
                      if (!e.dataTransfer.types.includes('text/transition')) return
                      e.preventDefault()
                      e.stopPropagation()
                      setGiunzione(g.id)
                    }}
                    onDragLeave={() => setGiunzione((x) => (x === g.id ? null : x))}
                    onDrop={(e) => {
                      const tipo = e.dataTransfer.getData('text/transition')
                      if (!tipo) return
                      e.preventDefault()
                      e.stopPropagation()
                      setGiunzione(null)
                      const d = parseFloat(e.dataTransfer.getData('text/duration')) || 1
                      onTransition?.(tipo, d, g.clip)
                    }}
                  />
                ))}

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
                .catch((e) => setError(e.message))} title="Aggiungi una traccia video">
                <Icon name="piu" size={13} />video</button>
              <button onClick={() => run('add_track', { kind: 'audio' })
                .catch((e) => setError(e.message))} title="Aggiungi una traccia audio">
                <Icon name="piu" size={13} />audio</button>
            </div>
            <div className="lane addhint hint">
              {project.tracks.filter((t) => t.kind === 'video').length} video ·{' '}
              {project.tracks.filter((t) => t.kind === 'audio').length} audio
            </div>
          </div>
      </>
    )
  }, [project, lanes, drag, assets, selected, setSelected, pxPerSec, trackH,
      renaming, mediaById, run, setError, onPreset, onTransition, ask, giunzione, giunzioni,
      shiftTrack, soloOn, startDrag])

  if (!project) return <div className="timeline" />

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

          {corpo}

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
