import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { sampleKf } from './util.js'

/**
 * Riproduzione in tempo reale, senza passare da ffmpeg.
 *
 * L'anteprima fedele renderizza il filmato e poi lo riproduce: e' esatta ma si
 * aspetta. Qui invece il browser riproduce direttamente i proxy dei file e la
 * composizione la fa il motore grafico della pagina — posizione, scala,
 * opacita', dissolvenze e i pochi effetti che il CSS sa rifare. Niente da
 * preparare: si parte subito e lo scrub non renderizza nulla.
 *
 * Il prezzo e' la fedelta': quello che il CSS non sa fare (LUT, chroma key,
 * glow, curve, stabilizzazione, tendine e scorrimenti) qui non si vede. Quando
 * capita, il componente lo dichiara con `onApprossimato` invece di mostrare
 * qualcosa di diverso dal render facendo finta di niente.
 */

// Effetti che il CSS riproduce fedelmente. Gli altri fanno scattare l'avviso.
const CSS_FILTRI = new Set(['color', 'blur', 'mirror', 'vignette'])

const dbToVol = (db) => Math.min(1, Math.max(0, 10 ** ((Number(db) || 0) / 20)))

/** Quanto della clip si vede al tempo t: dissolvenze in entrata e uscita. */
function opacitaClip(clip, tLocale) {
  let a = 1
  if (clip.fade_in > 0) a *= Math.min(1, tLocale / clip.fade_in)
  if (clip.fade_out > 0) {
    a *= Math.min(1, Math.max(0, (clip.duration - tLocale) / clip.fade_out))
  }
  return Math.max(0, Math.min(1, a))
}

/** Filtro CSS equivalente agli effetti della clip, per quelli che si possono. */
function filtroCss(clip, k) {
  const parti = []
  for (const e of clip.effects || []) {
    if (e.enabled === false) continue
    const p = e.params || {}
    if (e.type === 'color') {
      if (p.brightness) parti.push(`brightness(${1 + Number(p.brightness)})`)
      if (p.contrast != null && p.contrast !== 1) parti.push(`contrast(${p.contrast})`)
      if (p.saturation != null && p.saturation !== 1) parti.push(`saturate(${p.saturation})`)
    } else if (e.type === 'blur' && p.sigma) {
      parti.push(`blur(${Number(p.sigma) * k}px)`)
    }
  }
  return parti.join(' ')
}

/** Vero se tutto quello che c'e' sulla clip si sa rifare in CSS. */
function fedele(clip) {
  const fx = (clip.effects || []).filter((e) => e.enabled !== false)
  if (!fx.every((e) => CSS_FILTRI.has(e.type))) return false
  const tr = clip.transition_out
  if (tr && tr.type && tr.type !== 'dissolve' && tr.duration > 0) return false
  return true
}

export default function LivePlayer({
  project, playhead, seek, playing, setPlaying, onApprossimato,
}) {
  const hostRef = useRef(null)
  const elementi = useRef(new Map())     // clip id -> elemento multimediale
  const [attivi, setAttivi] = useState([])   // clip da tenere nel DOM
  const [box, setBox] = useState(null)       // dimensione a schermo del canvas
  const orologio = useRef({ da: 0, a: 0 })   // riferimento tempo reale -> timeline
  const attiviRef = useRef('')
  // la testina si legge da un riferimento: se entrasse fra le dipendenze del
  // ciclo, ogni suo aggiornamento lo ricostruirebbe azzerando l'orologio
  const testina = useRef(playhead)
  testina.current = playhead

  const duration = project?.duration || 0
  const [pw, ph] = (project?.settings?.resolution || '1920x1080').split('x').map(Number)

  // dimensione del riquadro: serve a convertire i pixel di progetto in pixel a
  // schermo, esattamente come fa il riquadro di trasformazione
  useEffect(() => {
    const misura = () => {
      const el = hostRef.current
      if (!el || !el.clientWidth) return
      const w = el.clientWidth
      const h = el.clientHeight
      const scala = Math.min(w / pw, h / ph)
      setBox({ w: pw * scala, h: ph * scala, k: scala })
    }
    misura()
    const ro = new ResizeObserver(misura)
    if (hostRef.current) ro.observe(hostRef.current)
    return () => ro.disconnect()
  }, [pw, ph])

  // Il solo vince su tutto il resto, esattamente come in Project.live_tracks:
  // se una traccia video e' in solo le altre non si disegnano, se una traccia
  // audio e' in solo le altre non suonano — comprese le clip appoggiate sulle
  // tracce video, che il mix del render esclude allo stesso modo. Senza questo
  // l'anteprima in diretta mostra e fa sentire roba che nel file non c'e'.
  const soloVideo = (project?.tracks || []).some((t) => t.kind === 'video' && t.solo)
  const soloAudio = (project?.tracks || []).some((t) => t.kind === 'audio' && t.solo)

  /** Vero se dalla traccia non deve uscire alcun suono. */
  const zittita = (track) =>
    track.muted || (soloAudio && !(track.kind === 'audio' && track.solo))

  /** Vero se la traccia non finisce nell'immagine composta. */
  const invisibile = (track) =>
    track.kind === 'video' && (track.hidden || (soloVideo && !track.solo))

  /**
   * Clip attive al tempo t, dal fondo verso l'alto come nel render.
   *
   * Nascosta e non-suona sono condizioni separate: una traccia video nascosta
   * porta comunque il suo audio nel mix, quindi la clip resta viva e si spegne
   * solo l'immagine. Toglierla del tutto farebbe sparire un suono che nel file
   * finale c'e'.
   */
  const visibili = (t) => {
    const out = []
    for (const track of project?.tracks || []) {
      for (const c of track.clips) {
        if (c.enabled === false) continue
        if (t < c.start - 1e-6 || t > c.end + 1e-6) continue
        out.push({ clip: c, track, disegna: !invisibile(track) })
      }
    }
    // le clip che iniziano dopo stanno sotto, testi e colori sempre sopra:
    // stesso ordine del compilatore, altrimenti l'anteprima mente
    return out.sort((a, b) => {
      const grafica = (x) => (x.clip.type === 'text' || x.clip.type === 'color' ? 1 : 0)
      if (grafica(a) !== grafica(b)) return grafica(a) - grafica(b)
      return b.clip.start - a.clip.start
    })
  }

  // ---- ciclo di aggiornamento ----------------------------------------------
  useEffect(() => {
    let vivo = true
    let ultimoAvviso = null
    let ultimoSeek = 0
    // l'orologio si fissa solo quando parte la riproduzione: da li' in avanti
    // il tempo lo detta l'orologio della macchina, non i nostri aggiornamenti
    orologio.current = { da: performance.now(), a: testina.current }

    const passo = () => {
      if (!vivo) return
      const o = orologio.current
      const t = playing
        ? Math.min(duration, o.a + (performance.now() - o.da) / 1000)
        : testina.current

      if (playing && t >= duration - 1e-3) { setPlaying(false); seek(duration) }

      const ora = visibili(t)
      const ids = ora.map((v) => v.clip.id).join('|')
      if (ids !== attiviRef.current) {
        attiviRef.current = ids
        setAttivi(ora)
      }

      let approssimato = false
      for (const { clip, track, disegna } of ora) {
        const el = elementi.current.get(clip.id)
        if (!el) continue
        if (disegna && !fedele(clip)) approssimato = true

        const tLocale = t - clip.start
        const speed = Math.abs(clip.speed || 1)

        if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') {
          const dentro = (clip.in || 0) + tLocale * speed
          // il riallineamento costa un seek: si fa solo quando la deriva si
          // vede, altrimenti la riproduzione singhiozza a ogni fotogramma
          if (Math.abs(el.currentTime - dentro) > 0.15) el.currentTime = dentro
          const r = Math.min(16, Math.max(0.0625, speed))
          if (el.playbackRate !== r) el.playbackRate = r
          if (playing && el.paused) el.play().catch(() => {})
          if (!playing && !el.paused) el.pause()

          const gain = sampleKf(clip.audio?.gain_db ?? 0, tLocale)
          el.muted = zittita(track) || (clip.audio?.mute ?? false)
          // il volume della traccia e' animabile e il cursore arriva a 2x:
          // HTMLMediaElement accetta solo 0..1 e su un valore fuori scala lancia,
          // fermando il ciclo di aggiornamento e con esso tutta l'anteprima
          const vol = dbToVol(gain) * sampleKf(track.volume ?? 1, tLocale)
            * opacitaAudio(clip, tLocale)
          el.volume = Math.min(1, Math.max(0, vol)) || 0
        }

        if (el.style && box) {
          const tr = clip.transform || {}
          const x = sampleKf(tr.x ?? 0, tLocale) * box.k
          const y = sampleKf(tr.y ?? 0, tLocale) * box.k
          const s = sampleKf(tr.scale ?? 1, tLocale)
          const rot = sampleKf(tr.rotation ?? 0, tLocale)
          // traccia nascosta o esclusa da un solo: resta viva per l'audio ma
          // non deve comparire nell'immagine
          const op = disegna
            ? sampleKf(tr.opacity ?? 1, tLocale) * opacitaClip(clip, tLocale)
            : 0
          const specchio = (clip.effects || []).find((e) => e.type === 'mirror' && e.enabled !== false)
          const sx = specchio?.params?.horizontal ? -s : s
          const sy = specchio?.params?.vertical ? -s : s
          el.style.transform = `translate(${x}px, ${y}px) scale(${sx}, ${sy}) rotate(${rot}deg)`
          el.style.opacity = String(op)
          const f = filtroCss(clip, box.k)
          if (el.style.filter !== f) el.style.filter = f
        }
      }

      if (approssimato !== ultimoAvviso) {
        ultimoAvviso = approssimato
        onApprossimato?.(approssimato)
      }

      // la testina si aggiorna a ~10 Hz: a ogni fotogramma vorrebbe dire
      // ridisegnare mezza interfaccia sessanta volte al secondo
      if (playing && performance.now() - ultimoSeek > 100) {
        ultimoSeek = performance.now()
        seek(t, true)
      }
      requestAnimationFrame(passo)
    }

    const id = requestAnimationFrame(passo)
    return () => { vivo = false; cancelAnimationFrame(id) }
    // playhead di proposito fuori: si legge da testina.current
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, playing, duration, box, seek, setPlaying])

  // le clip sparite dal DOM non devono restare in memoria
  useEffect(() => {
    const vivi = new Set(attivi.map((a) => a.clip.id))
    for (const id of [...elementi.current.keys()]) {
      if (!vivi.has(id)) elementi.current.delete(id)
    }
  }, [attivi])

  const media = Object.fromEntries((project?.media || []).map((m) => [m.id, m]))
  const registra = (id) => (el) => { if (el) elementi.current.set(id, el); else elementi.current.delete(id) }

  return (
    <div className="live" ref={hostRef}>
      {box && (
        <div className="livecanvas" style={{ width: box.w, height: box.h }}>
          {attivi.map(({ clip, track }) => {
            const m = clip.media ? media[clip.media] : null
            const chiave = clip.id
            if (track.kind === 'audio') {
              return <audio key={chiave} ref={registra(chiave)} src={api.streamUrl(clip.media)}
                preload="auto" />
            }
            if (clip.type === 'text') return <Testo key={chiave} clip={clip} k={box.k} ref2={registra(chiave)} />
            if (clip.type === 'color') {
              return <div key={chiave} ref={registra(chiave)} className="livelayer"
                style={{ background: clip.color || 'black' }} />
            }
            if (m?.kind === 'image') {
              return <img key={chiave} ref={registra(chiave)} className="livelayer"
                src={api.streamUrl(clip.media)} alt="" style={{ objectFit: fitCss(clip.fit) }} />
            }
            return (
              <video key={chiave} ref={registra(chiave)} className="livelayer"
                src={api.streamUrl(clip.media)} preload="auto" playsInline
                style={{ objectFit: fitCss(clip.fit) }} />
            )
          })}
        </div>
      )}
    </div>
  )
}

/** fit del progetto -> object-fit del CSS: stessi nomi, stesso significato. */
const fitCss = (fit) => (fit === 'cover' ? 'cover' : fit === 'stretch' ? 'fill'
  : fit === 'none' ? 'none' : 'contain')

/** Le dissolvenze valgono anche sull'audio, come nel render. */
function opacitaAudio(clip, tLocale) {
  const a = clip.audio || {}
  let v = 1
  if (a.fade_in > 0) v *= Math.min(1, tLocale / a.fade_in)
  if (a.fade_out > 0) v *= Math.min(1, Math.max(0, (clip.duration - tLocale) / a.fade_out))
  return Math.max(0, Math.min(1, v))
}

const Testo = ({ clip, k, ref2 }) => {
  const t = clip.text || {}
  return (
    <div ref={ref2} className="livelayer livetext">
      <span style={{
        fontSize: (t.font_size || 64) * k,
        color: t.color || 'white',
        textAlign: t.align || 'center',
        WebkitTextStroke: t.border_width ? `${t.border_width * k}px ${t.border_color || 'black'}` : undefined,
        background: t.box ? `rgba(0,0,0,${t.box_opacity ?? 0.5})` : undefined,
        padding: t.box ? (t.box_padding ?? 20) * k : undefined,
      }}>{t.text}</span>
    </div>
  )
}
