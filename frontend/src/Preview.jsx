import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Gizmo from './Gizmo.jsx'
import LivePlayer from './LivePlayer.jsx'
import useFrame from './useFrame.js'
import { fmt } from './util.js'

const SEGMENT = 12   // secondi renderizzati per volta durante la riproduzione
// Il primo pezzo si aspetta da fermi, con il dito ancora sul tasto play: va
// tenuto corto. Quelli dopo si preparano mentre il precedente e' in onda, e li'
// conviene il contrario — meno stacchi, meno occasioni di restare a secco.
const PRIMO = 4

/**
 * Anteprima fedele al render finale: da fermi si mostra il fotogramma
 * renderizzato da ffmpeg, in riproduzione si scarica un segmento in bozza.
 * Il segmento successivo viene preparato mentre il corrente e' in onda, cosi'
 * il passaggio non si sente.
 */
export default function Preview({
  project, revision, playhead, seek, playing, setPlaying, clip, run, setError, prova,
  diretta = true,
}) {
  const videoRef = useRef(null)
  const imgRef = useRef(null)
  const [segment, setSegment] = useState(null)   // {start, duration, url}
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(null)
  const [approssimato, setApprossimato] = useState(false)
  const duration = project?.duration || 0

  // il progetto e' cambiato mentre si riproduce: ci si ferma e si riparte a mano
  // (il segmento in onda e' stato renderizzato dalla versione precedente)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (playing) setPlaying(false) }, [revision])

  // avvio riproduzione: prepara il segmento a partire dalla testina
  useEffect(() => {
    if (diretta) { setSegment(null); return }
    if (!playing || duration <= 0) { setSegment(null); return }
    const start = playhead >= duration - 0.05 ? 0 : playhead
    const len = Math.min(PRIMO, duration - start)
    if (len <= 0.05) { setPlaying(false); return }
    setLoading(true)
    setFailed(null)
    setSegment({ start, duration: len, url: api.previewUrl(start, len, revision) })
    // dipende solo dall'avvio: durante la riproduzione i segmenti si concatenano da soli
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing])

  // cache predittiva: il pezzo dopo quello in onda
  useEffect(() => {
    if (diretta || !segment || loading) return
    const next = segment.start + segment.duration
    if (next < duration - 0.05) api.prefetch(next, Math.min(SEGMENT, duration - next))
  }, [segment?.start, loading, duration])

  // da fermi: prepara il segmento sotto la testina, cosi' play parte subito
  useEffect(() => {
    if (diretta || playing || duration <= 0) return
    const id = setTimeout(() => {
      // esattamente il pezzo che chiederebbe play: preparane uno da dodici
      // secondi voleva dire tre volte il lavoro, e comunque non quello giusto
      if (playhead < duration - 0.05) api.prefetch(playhead, Math.min(PRIMO, duration - playhead))
    }, 900)
    return () => clearTimeout(id)
    // diretta fra le dipendenze: passando di modo il lavoro gia' in coda va
    // annullato, altrimenti parte un render che nessuno guardera'
  }, [playhead, playing, revision, duration, diretta])

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

  // In diretta non si renderizza niente: il fotogramma da ffmpeg serve solo in
  // modalita' fedele, o quando si sta guardando la prova di un effetto.
  const usaFrame = !empty && (!diretta || prova) && !playing
  const frame = useFrame(
    usaFrame
      ? api.frameUrl(Math.min(playhead, Math.max(0, duration - 0.02)), revision, 960, prova)
      : null,
  )

  return (
    <div className="preview">
      {empty ? (
        <div className="empty">
          Timeline vuota.<br />Importa dei file e trascinali qui sotto.
        </div>
      ) : diretta && !prova ? (
        <>
          <LivePlayer project={project} playhead={playhead} seek={seek}
            playing={playing} setPlaying={setPlaying} onApprossimato={setApprossimato} />
          {approssimato && (
            <div className="badge sottile" title={
              'Qui la composizione la fa il browser: LUT, chroma key, glow, curve,'
              + ' stabilizzazione, tendine e scorrimenti non si vedono.'
              + '\nPassa a "fedele" per il risultato esatto.'}>
              anteprima approssimata
            </div>
          )}
        </>
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
          {frame.url && <img ref={imgRef} src={frame.url} alt="" />}
          <Gizmo project={project} clip={clip} imgRef={imgRef} playhead={playhead}
            run={run} setError={setError} />
          {prova
            ? <div className="badge prova">{prova.label} — anteprima, non applicato</div>
            : frame.pending && <div className="badge sottile">aggiorno…</div>}
        </>
      )}
      {(failed || (frame.failed && !playing)) && (
        <div className="badge">{failed || 'fotogramma non disponibile'}</div>
      )}
      {!empty && (!playing || diretta) && (
        <div className="badge" style={{ left: 'auto', right: 12 }}>
          {fmt(playhead)} / {fmt(duration)}
        </div>
      )}
    </div>
  )
}
