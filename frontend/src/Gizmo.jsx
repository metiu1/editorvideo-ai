import React, { useEffect, useState } from 'react'
import { isKf, sampleKf, transformBox } from './util.js'

/**
 * Riquadro di trasformazione sull'anteprima: trascinare l'immagine la sposta,
 * trascinare un angolo la ridimensiona. Scrive negli stessi campi del pannello
 * proprieta' (transform.x, transform.y, transform.scale).
 *
 * Con i parametri animati il riquadro mostra il valore alla testina ma non si
 * trascina: modificarlo qui cancellerebbe l'animazione.
 */
export default function Gizmo({ project, clip, imgRef, playhead, run, setError }) {
  const [box, setBox] = useState(null)
  const [drag, setDrag] = useState(null)

  const tr = clip?.transform || {}
  const clipTime = clip ? Math.max(0, playhead - clip.start) : 0
  const animated = isKf(tr.x) || isKf(tr.y) || isKf(tr.scale)
  const visible = clip && clip.enabled !== false &&
    playhead >= clip.start - 1e-6 && playhead <= clip.end + 1e-6

  // il riquadro segue la dimensione a schermo dell'anteprima
  useEffect(() => {
    const update = () => {
      const img = imgRef.current
      const host = img?.parentElement
      if (!img || !host || !img.clientWidth) { setBox(null); return }
      const hr = host.getBoundingClientRect()
      const ir = img.getBoundingClientRect()
      setBox({ left: ir.left - hr.left, top: ir.top - hr.top, w: ir.width, h: ir.height })
    }
    update()
    const ro = new ResizeObserver(update)
    if (imgRef.current) ro.observe(imgRef.current)
    window.addEventListener('resize', update)
    const id = setInterval(update, 500)   // l'immagine cambia quando si sposta la testina
    return () => { ro.disconnect(); window.removeEventListener('resize', update); clearInterval(id) }
  }, [imgRef, clip?.id])

  if (!visible || !box || !project) return null

  const [cw, ch] = project.settings.resolution.split('x').map(Number)
  const canvas = { width: cw, height: ch }
  const media = (project.media || []).find((m) => m.id === clip.media)
  const [nw, nh] = clip.fit === 'none' && media?.resolution
    ? media.resolution.split('x').map(Number)
    : [cw, ch]
  const native = { width: nw, height: nh }

  const scale = sampleKf(tr.scale ?? 1, clipTime) || 1
  const x = sampleKf(tr.x ?? 0, clipTime)
  const y = sampleKf(tr.y ?? 0, clipTime)
  const k = box.w / cw

  const start = (e, mode) => {
    if (animated) return
    e.preventDefault()
    e.stopPropagation()
    setDrag({ mode, sx: e.clientX, sy: e.clientY, x, y, scale })
  }

  useEffect(() => {
    if (!drag) return
    const onMove = (e) => {
      const dx = (e.clientX - drag.sx) / k
      const dy = (e.clientY - drag.sy) / k
      if (drag.mode === 'move') {
        setDrag((d) => ({ ...d, nx: drag.x + dx, ny: drag.y + dy }))
      } else {
        const base = Math.max(native.width, 1) / 2
        const sign = drag.mode.includes('l') ? -1 : 1
        setDrag((d) => ({ ...d, ns: Math.max(0.02, drag.scale + (sign * dx) / base) }))
      }
    }
    const onUp = () => {
      setDrag((d) => {
        if (!d) return null
        const patch = d.mode === 'move'
          ? (d.nx === undefined ? null : { x: round(d.nx), y: round(d.ny) })
          : (d.ns === undefined ? null : { scale: round(d.ns) })
        if (patch) run('set_transform', { clip_id: clip.id, ...patch }).catch((e) => setError(e.message))
        return null
      })
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp, { once: true })
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [drag?.mode, k, clip?.id, run, setError])

  // durante il trascinamento il riquadro segue il mouse, senza attendere il server
  const liveS = drag?.ns ?? scale
  const rect = transformBox({
    box, canvas, native,
    x: drag?.nx ?? x, y: drag?.ny ?? y, scale: liveS,
  })

  return (
    <div
      className={`gizmo ${animated ? 'locked' : ''}`}
      style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
      onPointerDown={(e) => start(e, 'move')}
      title={animated ? 'parametro animato: modificalo dai keyframe' : 'trascina per spostare'}
    >
      {!animated && ['tl', 'tr', 'bl', 'br'].map((c) => (
        <div key={c} className={`gh ${c}`} onPointerDown={(e) => start(e, c)} />
      ))}
      <div className="gsize">{Math.round(liveS * 100)}%</div>
    </div>
  )
}

const round = (v) => Math.round(v * 100) / 100
