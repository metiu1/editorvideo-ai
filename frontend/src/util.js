export const fmt = (s) => {
  if (!isFinite(s)) return '0:00.0'
  const neg = s < 0
  s = Math.abs(s)
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${neg ? '-' : ''}${m}:${sec.toFixed(1).padStart(4, '0')}`
}

export const isKf = (v) => v && typeof v === 'object' && Array.isArray(v.kf)

// Valore del parametro al tempo t (stessa interpolazione del backend, per la UI).
export function sampleKf(value, t) {
  if (!isKf(value)) return Number(value) || 0
  const keys = [...value.kf].sort((a, b) => a.t - b.t)
  if (t <= keys[0].t) return keys[0].v
  if (t >= keys[keys.length - 1].t) return keys[keys.length - 1].v
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1]
    if (t >= a.t && t <= b.t) {
      const span = b.t - a.t
      const p = span <= 0 ? 0 : (t - a.t) / span
      return a.v + (b.v - a.v) * ease(a.ease || 'linear', p)
    }
  }
  return keys[keys.length - 1].v
}

function ease(name, p) {
  switch (name) {
    case 'hold': return 0
    case 'ease_in': return p * p
    case 'ease_out': return 1 - (1 - p) ** 2
    case 'ease_in_out': return p * p * (3 - 2 * p)
    case 'ease_in_cubic': return p ** 3
    case 'ease_out_cubic': return 1 - (1 - p) ** 3
    case 'ease_in_out_cubic': return p < 0.5 ? 4 * p ** 3 : 1 - 4 * (1 - p) ** 3
    default: return p
  }
}

export const EASINGS = ['linear', 'hold', 'ease_in', 'ease_out', 'ease_in_out',
  'ease_in_cubic', 'ease_out_cubic', 'ease_in_out_cubic']

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

/**
 * Geometria del riquadro di trasformazione: dai valori del progetto (pixel del
 * canvas, origine al centro) ai pixel dell'immagine mostrata a schermo.
 *
 * E' una funzione pura per poterla verificare senza browser: e' il punto in cui
 * un errore di conversione sposterebbe il riquadro rispetto all'immagine.
 */
export function transformBox({ box, canvas, native, x = 0, y = 0, scale = 1 }) {
  const k = box.w / canvas.width          // pixel a schermo per pixel di progetto
  const w = native.width * scale * k
  const h = native.height * scale * k
  const cx = box.left + box.w / 2 + x * k
  const cy = box.top + box.h / 2 + y * k
  return { k, left: cx - w / 2, top: cy - h / 2, width: w, height: h }
}

export const allClips = (project) =>
  project ? project.tracks.flatMap((t) => t.clips.map((c) => ({ ...c, trackId: t.id, kind: t.kind }))) : []

export const findClip = (project, id) => allClips(project).find((c) => c.id === id)
