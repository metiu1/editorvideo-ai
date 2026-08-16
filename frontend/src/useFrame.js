import { useEffect, useRef, useState } from 'react'

/**
 * Tiene a video l'ultimo fotogramma valido mentre ne carica uno nuovo.
 *
 * Risolve due problemi che rendono l'anteprima inservibile su progetti veri:
 *
 * 1. Una richiesta per evento del puntatore. Trascinare la testina genera un
 *    centinaio di `pointermove` al secondo; ognuno chiedeva un fotogramma, e il
 *    server li renderizza *uno alla volta* (il render prende un lock globale).
 *    Cento richieste da mezzo secondo sono quasi un minuto di coda per arrivare
 *    a un fotogramma che nel frattempo non interessa piu'. Qui ne resta in volo
 *    una sola: quando finisce si salta direttamente all'ultima posizione
 *    chiesta, saltando tutte quelle attraversate nel frattempo.
 *
 * 2. Cambiare `src` a un `<img>` lo svuota subito, e resta vuoto finche' la
 *    nuova immagine non e' decodificata. Con mezzo secondo di render, ogni
 *    click sulla timeline faceva diventare nero il monitor. Qui l'immagine si
 *    scarica fuori dal DOM e il `src` cambia solo quando e' gia' pronta.
 *
 * Ritorna l'url da mostrare (quello vecchio finche' il nuovo non e' pronto),
 * se il caricamento e' fallito, e se c'e' un aggiornamento in corso.
 */
export default function useFrame(url) {
  const [shown, setShown] = useState(null)
  const [failed, setFailed] = useState(false)
  const [pending, setPending] = useState(false)

  const shownRef = useRef(null)
  const wantedRef = useRef(url)
  const busyRef = useRef(false)
  const aliveRef = useRef(true)

  useEffect(() => () => { aliveRef.current = false }, [])

  useEffect(() => {
    wantedRef.current = url
    // se una richiesta e' gia' in volo prendera' lei il valore aggiornato:
    // partirne un'altra ora vorrebbe dire metterla in coda per niente
    if (busyRef.current) { if (url !== shownRef.current) setPending(true); return }

    const pump = () => {
      const next = wantedRef.current
      if (!aliveRef.current || !next || next === shownRef.current) {
        busyRef.current = false
        if (aliveRef.current) setPending(false)
        return
      }
      busyRef.current = true
      setPending(true)

      // createElement invece di `new Image()`: il costruttore globale non c'e'
      // in tutti gli ambienti in cui gira l'interfaccia (jsdom nei test), e qui
      // l'elemento serve solo a scaricare, non entra nel DOM
      const img = document.createElement('img')
      img.onload = () => {
        shownRef.current = next
        if (aliveRef.current) { setShown(next); setFailed(false) }
        pump()   // nel frattempo la testina puo' essersi spostata ancora
      }
      img.onerror = () => {
        busyRef.current = false
        if (aliveRef.current) { setFailed(true); setPending(false) }
      }
      img.src = next
    }

    pump()
  }, [url])

  return { url: shown, failed, pending }
}
