import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'
import { fmt } from './util.js'

/**
 * Monitor sorgente: guarda un file senza metterlo in timeline, segna
 * attacco e stacco, poi inserisce (o trascina) solo quel pezzo.
 */
export default function SourceMonitor({ media, tracks, run, setError, playhead, onClose }) {
  const ref = useRef(null)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(media?.duration || 0)
  const [mark, setMark] = useState({ in: 0, out: media?.duration || 0 })
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    setMark({ in: 0, out: media?.duration || 0 })
    setDur(media?.duration || 0)
    setT(0)
  }, [media?.id])

  if (!media) return null

  const seek = (v) => {
    const x = Math.max(0, Math.min(v, dur))
    setT(x)
    if (ref.current) ref.current.currentTime = x
  }

  const len = Math.max(0.05, mark.out - mark.in)
  const insert = (start) =>
    run('add_clip', {
      media_id: media.id, start, in_: mark.in, duration: len,
      track_id: tracks.find((tr) => tr.kind === (media.kind === 'audio' ? 'audio' : 'video'))?.id,
    }).catch((e) => setError(e.message))

  return (
    <div className="source">
      <div className="preview">
        <video
          ref={ref} src={api.streamUrl(media.id)} controls={false}
          onLoadedMetadata={(e) => setDur(e.target.duration || media.duration || 0)}
          onTimeUpdate={(e) => setT(e.target.currentTime)}
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        />
        <div className="badge">sorgente · {media.name}</div>
        <div className="badge tc" style={{ left: 'auto', right: 12 }}>{fmt(t)} / {fmt(dur)}</div>
      </div>

      <div className="srcbar">
        <button className="icon" title="Riproduci / pausa" onClick={() => {
          const v = ref.current
          if (!v) return
          v.paused ? v.play() : v.pause()
        }}><Icon name={playing ? 'pausa' : 'play'} size={17} /></button>
        <input
          type="range" min="0" max={Math.max(0.1, dur)} step="0.01" value={t}
          onChange={(e) => seek(+e.target.value)} style={{ flex: 1 }}
        />
        <button onClick={() => setMark((m) => ({ ...m, in: Math.min(t, m.out - 0.05) }))}
          title="Segna il punto di attacco">attacco</button>
        <button onClick={() => setMark((m) => ({ ...m, out: Math.max(t, m.in + 0.05) }))}
          title="Segna il punto di stacco">stacco</button>
        <span className="hint" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {fmt(mark.in)}–{fmt(mark.out)} · {len.toFixed(2)}s
        </span>
        <button
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData('text/media', media.id)
            e.dataTransfer.setData('text/inpoint', String(mark.in))
            e.dataTransfer.setData('text/length', String(len))
          }}
          onClick={() => insert(playhead)}
          className="primary"
          title="Clic: inserisci alla testina · trascina: scegli il punto sulla timeline"
        >inserisci</button>
        <button className="icon" onClick={onClose} title="Chiudi il monitor sorgente">
          <Icon name="chiudi" />
        </button>
      </div>
    </div>
  )
}
