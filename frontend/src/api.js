// Unico punto di contatto con il backend.

/**
 * Altezza dei segmenti di anteprima riprodotti dal player.
 *
 * Deve stare sotto la soglia in cui il render va piu' lento della
 * riproduzione, altrimenti il pezzo successivo non e' pronto in tempo e il
 * filmato si ferma a ogni giunzione. Su un progetto pesante 540p rendeva a
 * 0,6x il tempo reale e si impuntava; 432p sta sopra il tempo reale. Il
 * fotogramma fermo resta a piena qualita' — questo vale solo per la
 * riproduzione. Prefetch e richiesta devono usare lo stesso valore, altrimenti
 * la chiave di cache cambia e il lavoro preparato si butta via.
 */
const PREVIEW_H = 432

async function req(url, options) {
  const res = await fetch(url, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch { /* risposta non JSON */ }
    throw new Error(detail)
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  state: () => req('/api/state'),

  createProject: (path, name, preset) =>
    req('/api/project/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, name, preset }),
    }),

  openProject: (path) =>
    req('/api/project/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }),

  // Ogni modifica passa di qui: stesso metodo che usa l'agente via MCP.
  op: (name, args = {}) =>
    req(`/api/op/${name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
    }),

  browse: (path) => req(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  waveform: (id) => req(`/api/media/${id}/waveform`),
  strip: (id, height = 44) => req(`/api/media/${id}/strip?height=${height}`),
  streamUrl: (id) => `/api/media/${id}/stream`,

  upload: (files, folder = '') => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    form.append('folder', folder)
    return req('/api/upload', { method: 'POST', body: form })
  },

  prefetch: (start, duration, height = PREVIEW_H) =>
    req(`/api/preview/prefetch?start=${start.toFixed(3)}&duration=${duration.toFixed(3)}&height=${height}`,
      { method: 'POST' }).catch(() => null),

  // prova = {effect, clip}: il fotogramma esce come se quell'effetto fosse
  // applicato, ma il progetto non viene toccato
  frameUrl: (t, revision, width = 960, prova = null) =>
    `/api/frame?t=${t.toFixed(3)}&width=${width}&r=${revision}`
    + (prova?.effect ? `&effect=${encodeURIComponent(prova.effect)}` : '')
    + (prova?.preset ? `&preset=${encodeURIComponent(prova.preset)}` : '')
    + ((prova?.effect || prova?.preset) && prova.clip ? `&clip=${prova.clip}` : ''),
  previewUrl: (start, duration, revision, height = PREVIEW_H) =>
    `/api/preview?start=${start.toFixed(3)}&duration=${duration.toFixed(3)}&height=${height}&r=${revision}`,

  render: (body) =>
    req('/api/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  renderStatus: (id) => req(`/api/render/${id}`),
  buildProxies: () => req('/api/proxies?height=540', { method: 'POST' }),
  loudness: () => req('/api/loudness', { method: 'POST' }),

  // un preset = piu' effetti, applicati in un colpo solo (una sola voce di undo)
  applyPreset: (preset_id, clip_id = null) =>
    req('/api/preset/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset_id, clip_id }),
    }),

  chatReset: () => req('/api/chat/reset', { method: 'POST' }),
}

/**
 * Un turno con l'assistente. Gli eventi arrivano mentre il modello lavora
 * (testo, strumenti in esecuzione), quindi si legge il flusso invece di
 * aspettare la risposta completa.
 */
export async function chat(message, onEvent, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
    signal,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* non JSON */ }
    throw new Error(detail)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    // SSE: un evento per blocco separato da riga vuota
    let i
    while ((i = buf.indexOf('\n\n')) !== -1) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 2)
      if (line.startsWith('data:')) {
        try { onEvent(JSON.parse(line.slice(5))) } catch { /* blocco parziale */ }
      }
    }
  }
}

export function connectEvents(onEvent) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  let sock
  let closed = false
  const open = () => {
    sock = new WebSocket(`${proto}://${location.host}/ws`)
    sock.onmessage = (e) => onEvent(JSON.parse(e.data))
    sock.onclose = () => { if (!closed) setTimeout(open, 1500) }
  }
  open()
  return () => { closed = true; sock && sock.close() }
}
