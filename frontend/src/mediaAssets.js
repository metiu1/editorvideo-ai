import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

// Stessa altezza per tutti quelli che la usano: la striscia la genera ffmpeg e
// chiederne due misure diverse significa fargliela rigenerare da capo.
export const STRIP_H = 44

/**
 * Strisce di fotogrammi e forme d'onda, chieste una volta sola per file.
 *
 * Timeline e pannello media mostrano gli stessi media: senza una cache comune
 * ogni pannello rifarebbe le stesse richieste, e dietro la forma d'onda c'e' la
 * decodifica dell'audio del file. La chiave e' il percorso, non l'id: gli id
 * sono validi dentro un progetto, il percorso identifica il file.
 */
const valori = new Map()    // chiave -> valore, null se non disponibile
const inCorso = new Set()   // chiavi gia' richieste
const ascolto = new Set()   // componenti da ridisegnare quando arriva qualcosa

function chiedi(chiave, carica) {
  if (valori.has(chiave) || inCorso.has(chiave)) return
  inCorso.add(chiave)
  carica()
    .then((r) => valori.set(chiave, r ?? null))
    .catch(() => valori.set(chiave, null))
    .finally(() => {
      inCorso.delete(chiave)
      for (const sveglia of ascolto) sveglia()
    })
}

export default function useMediaAssets(media) {
  const [arrivi, ridisegna] = useState(0)

  useEffect(() => {
    const sveglia = () => ridisegna((n) => n + 1)
    ascolto.add(sveglia)
    for (const m of media || []) {
      if (!m.path) continue
      if (m.kind !== 'audio') chiedi(`s:${m.path}`, () => api.strip(m.id, STRIP_H))
      if (m.audio) chiedi(`w:${m.path}`, () => api.waveform(m.id))
    }
    return () => ascolto.delete(sveglia)
  }, [media])

  // L'oggetto cambia identita' solo quando arriva qualcosa di nuovo: la
  // timeline lo tiene fra le dipendenze del memo che disegna le clip, e uno
  // nuovo a ogni render lo invaliderebbe sempre.
  return useMemo(() => ({
    strip: (m) => (m?.path ? valori.get(`s:${m.path}`) : null) || null,
    peaks: (m) => (m?.path ? valori.get(`w:${m.path}`)?.peaks : null) || null,
  }), [arrivi])
}
