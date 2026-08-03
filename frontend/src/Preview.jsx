import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Gizmo from './Gizmo.jsx'
import { fmt } from './util.js'

const SEGMENT = 12   // secondi renderizzati per volta durante la riproduzione

/**
 * Anteprima fedele al render finale: da fermi si mostra il fotogramma
 * renderizzato da ffmpeg, in riproduzione si scarica un segmento in bozza.
 * Il segmento successivo viene preparato mentre il corrente e' in onda, cosi'
 * il passaggio non si sente.
 */
export default function Preview({
  project, revision, playhead, seek, playing, setPlaying, clip, run, setError,
}) {
  const videoRef = useRef(null)
  const imgRef = useRef(null)
  const [segment, setSegment] = useState(null)   // {start, duration, url}
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(null)
  const duration = project?.duration || 0

  // il progetto e' cambiato mentre si riproduce: ci si ferma e si riparte a mano
  // (il segmento in onda e' stato renderizzato dalla versione precedente)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (playing) setPlaying(false) }, [revision])

  // avvio riproduzione: prepara il segmento a partire dalla testina
  useEffect(() => {
    if (!playing || duration <= 0) { setSegment(null); return }
    const start = playhead >= duration - 0.05 ? 0 : playhead
    const len = Math.min(SEGMENT, duration - start)
    if (len <= 0.05) { setPlaying(false); return }
    setLoading(true)
    setFailed(null)
    setSegment({ start, duration: len, url: api.previewUrl(start, len, revision) })
    // dipende solo dall'avvio: durante la riproduzione i segmenti si concatenano da soli
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing])

  // cache predittiva: il pezzo dopo quello in onda
  useEffect(() => {
    if (!segment || loading) return
    const next = segment.start + segment.duration
    if (next < duration - 0.05) api.prefetch(next, Math.min(SEGMENT, duration - next))
  }, [segment?.start, loading, duration])

  // da fermi: prepara il segmento sotto la testina, cosi' play parte subito
  useEffect(() => {
    if (playing || duration <= 0) return
    const id = setTimeout(() => {
      if (playhead < duration - 0.05) api.prefetch(playhead, Math.min(SEGMENT, duration - playhead))
    }, 900)
    return () => clearTimeout(id)
  }, [playhead, playing, revision, duration])

  const onEnded = () => {
    const next = segment.start + segment.duration
    if (next >= duration - 0.05) { setPlaying(false); seek(duration); return }
    const len = Math.min(SEGMENT, duration - next)
    setLoading(true)
    setSegment({ start: next, duration: len, url: api.previewUrl(next, len, revision) })
  }

  useEffect(() => {
    const v = videoRef.current
    if (v && segment && !loading) {
      // il browser puo' rifiutare l'avvio automatico: senza avviso sembra che il
      // pulsante play non faccia niente
      v.play().catch(() => { setFailed('il browser ha bloccato la riproduzione'); setPlaying(false) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segment, loading])

  /** Il player non dice perche' ha fallito: il motivo lo sa il server. */
  const onVideoError = () => {
    setPlaying(false)
    setFailed('anteprima non disponibile')
    if (!segment) return
    fetch(segment.url)
      .then((r) => (r.ok ? null : r.json().catch(() => null)))
      .then((body) => { if (body?.detail) setFailed(body.detail) })
      .catch(() => {})
  }

  const empty = !project || duration <= 0

  return (
    <div className="preview">
      {empty ? (
        <div className="empty">
          Timeline vuota.<br />Importa dei file e trascinali qui sotto.
        </div>
      ) : playing && segment ? (
        <>
          {/* il fotogramma resta a video finche' il segmento non e' pronto:
              altrimenti premendo play lo schermo diventa nero e sembra rotto */}
          {loading && (
            <img src={api.frameUrl(Math.min(segment.start, Math.max(0, duration - 0.02)), revision)}
              alt="" />
          )}
          <video
            ref={videoRef}
            src={segment.url}
            onLoadedData={() => setLoading(false)}
            onTimeUpdate={(e) => seek(segment.start + e.target.currentTime, true)}
            onEnded={onEnded}
            onError={onVideoError}
            style={{ visibility: loading ? 'hidden' : 'visible' }}
          />
          {loading && <div className="badge">preparo l'anteprima…</div>}
        </>
      ) : (
        <>
          <img
            ref={imgRef}
            src={api.frameUrl(Math.min(playhead, Math.max(0, duration - 0.02)), revision)}
            alt=""
            onError={() => setFailed('fotogramma non disponibile')}
            onLoad={() => setFailed(null)}
          />
          <Gizmo project={project} clip={clip} imgRef={imgRef} playhead={playhead}
            run={run} setError={setError} />
        </>
      )}
      {failed && <div className="badge">{failed}</div>}
      {!empty && !playing && (
        <div className="badge" style={{ left: 'auto', right: 12 }}>
          {fmt(playhead)} / {fmt(duration)}
        </div>
      )}
    </div>
  )
}
