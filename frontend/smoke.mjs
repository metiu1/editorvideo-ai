/**
 * Monta la UI compilata in jsdom con il backend simulato.
 *
 * Non sostituisce una prova manuale, ma intercetta subito gli errori che
 * romperebbero la pagina: import sbagliati, hook usati male, campi mancanti
 * nelle risposte dell'API.
 *
 *   npm run build && node smoke.mjs
 */
import { readdirSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'

const FAKE = {
  '/api/state': {
    path: 'C:/tmp/p.json',
    revision: 'abc123',
    presets: ['1080p', 'vertical'],
    transitions: ['dissolve', 'wipe_right', 'slide_left', 'iris'],
    system: { ffmpeg: 'finto', encoders: { h264: 'h264_nvenc' }, hw: ['h264_nvenc'] },
    effects: [
      { name: 'color', kind: 'video', label: 'Correzione colore', desc: '', params: [
        { name: 'saturation', default: 1, type: 'number', min: 0, max: 3, animatable: true, choices: [], desc: '' }] },
      { name: 'compressor', kind: 'audio', label: 'Compressore', desc: '', params: [
        { name: 'ratio', default: 3, type: 'number', min: 1, max: 20, animatable: false, choices: [], desc: '' }] },
    ],
    project: {
      name: 'demo', duration: 6,
      settings: { resolution: '1920x1080', fps: 30, sample_rate: 48000, background: 'black' },
      media: [
        { id: 'm1', name: 'clip.mp4', kind: 'video', duration: 6, resolution: '1920x1080', audio: true, folder: '' },
        { id: 'm2', name: 'musica.mp3', kind: 'audio', duration: 30, audio: true, folder: 'colonna sonora' },
      ],
      master: { loudnorm: { enabled: false, target_lufs: -14, measured: false }, effects: [], volume: 1 },
      tracks: [
        { id: 'V1', kind: 'video', name: 'V1', hidden: false, muted: false, volume: 1, clips: [
          { id: 'c1', type: 'media', name: 'clip.mp4', start: 0, end: 4, duration: 4, media: 'm1',
            in: 0, speed: 1, reverse: false, enabled: true, fit: 'contain', color: 'black',
            fade_in: 0.5, fade_out: 0, transition: { type: 'wipe_right', duration: 0.8 },
            transition_out: { type: 'wipe_right', duration: 0.8 },
            transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: { kf: [{ t: 0, v: 0 }, { t: 1, v: 1 }] } },
            audio: { gain_db: -3, mute: false, fade_in: 0, fade_out: 0, pan: 0 },
            effects: [{ i: 0, type: 'color', params: { saturation: 1.2 }, enabled: true }] },
          { id: 'c2', type: 'text', name: 'Titolo', start: 4, end: 6, duration: 2,
            speed: 1, reverse: false, enabled: true, fit: 'contain', color: 'black',
            fade_in: 0, fade_out: 0,
            transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 },
            audio: { gain_db: 0, mute: false, fade_in: 0, fade_out: 0, pan: 0 },
            text: { text: 'Ciao', font_size: 64, color: 'white', align: 'center', box: false },
            effects: [] },
        ] },
        { id: 'A1', kind: 'audio', name: 'A1', hidden: false, muted: false, volume: 0.8, clips: [
          { id: 'c3', type: 'media', name: 'musica.mp3', start: 0, end: 6, duration: 6, media: 'm2',
            in: 2, speed: 1, reverse: false, enabled: true, fit: 'contain', color: 'black',
            fade_in: 0, fade_out: 0,
            transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 },
            audio: { gain_db: -6, mute: false, fade_in: 0, fade_out: 0, pan: 0 },
            effects: [] },
        ] },
      ],
    },
  },
}

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:8760/', pretendToBeVisual: true,
})

const errors = []
dom.virtualConsole.on('jsdomError', (e) => errors.push(String(e)))

for (const k of ['window', 'document', 'HTMLElement', 'Node', 'Element',
  'Event', 'CustomEvent', 'MouseEvent', 'KeyboardEvent', 'getComputedStyle',
  'requestAnimationFrame', 'cancelAnimationFrame', 'DOMParser',
  'MutationObserver', 'DocumentFragment', 'Text', 'Range', 'CSS']) {
  Object.defineProperty(globalThis, k, { value: dom.window[k], configurable: true, writable: true })
}
for (const k of ['navigator', 'location']) {
  Object.defineProperty(globalThis, k, { value: dom.window[k], configurable: true })
}
globalThis.self = dom.window

globalThis.WebSocket = class { close() {} }
globalThis.ResizeObserver = class { observe() {} disconnect() {} }
globalThis.localStorage = {
  _d: {}, getItem(k) { return this._d[k] ?? null }, setItem(k, v) { this._d[k] = String(v) },
}
globalThis.fetch = async (url) => {
  const path = String(url).split('?')[0]
  if (path.endsWith('/strip')) {
    return { ok: true, status: 200, json: async () => ({ url: '/api/file?path=s.jpg', tiles: 6, interval: 1, tile_width: 78, tile_height: 44 }) }
  }
  if (path.endsWith('/waveform')) {
    return { ok: true, status: 200, json: async () => ({ peaks: Array.from({ length: 300 }, (_, i) => Math.abs(Math.sin(i / 9))), duration: 30 }) }
  }
  // le operazioni di editing rimandano semplicemente il progetto invariato
  const body = FAKE[path] ?? { result: { id: 'c1' }, project: FAKE['/api/state'].project, revision: 'abc123' }
  return { ok: true, status: 200, json: async () => body }
}

const bundle = readdirSync('dist/assets').find((f) => f.endsWith('.js'))
if (!bundle) throw new Error('nessun bundle in dist/assets: lancia prima `npm run build`')

await import(pathToFileURL(`dist/assets/${bundle}`).href)

await new Promise((r) => setTimeout(r, 400))

const root = dom.window.document.getElementById('root')
const html = root.innerHTML

// selezione di una clip: apre il pannello proprieta' con i keyframe
const clip = root.querySelector('.clip')
clip.dispatchEvent(new dom.window.PointerEvent('pointerdown', { bubbles: true, clientX: 40, clientY: 40 }))
dom.window.document.dispatchEvent(new dom.window.PointerEvent('pointerup', { bubbles: true }))
await new Promise((r) => setTimeout(r, 150))
const afterClick = root.innerHTML

const checks = [
  ['selezione clip', afterClick.includes('posizione e scala')],
  ['pannello transizione', afterClick.includes('transizione in uscita')],
  ['tipi di transizione', afterClick.includes('tendina verso destra')],
  // il riquadro di trasformazione dipende dal layout dell'immagine, che jsdom
  // non calcola: la sua geometria e' verificata a parte in test-util.mjs
  ['editor keyframe', afterClick.includes('keyframe alla testina')],
  ['effetti della clip', afterClick.includes('Correzione colore')],
  ['catalogo effetti', afterClick.includes('aggiungi effetto')],
  ['barra strumenti', html.includes('esporta')],
  ['elenco media', html.includes('clip.mp4')],
  ['tracce', html.includes('V1') && html.includes('A1')],
  ['clip in timeline', html.includes('class="clip')],
  ['trasporto', html.includes('zoom')],
  ['pannello progetto', html.includes('normalizza') || html.includes('progetto')],
  ['cartelle nel bin', html.includes('colonna sonora')],
  ['schede monitor', html.includes('sorgente')],
  ['striscia fotogrammi', afterClick.includes('background-image')],
  ['forma d onda', afterClick.includes('class="wave"')],
  ['volume traccia', html.includes('tvol')],
  ['divisori pannelli', html.includes('divider')],
]

let bad = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}`)
  if (!ok) bad++
}
if (errors.length) {
  console.log('\nerrori jsdom:')
  errors.forEach((e) => console.log('  ' + e.split('\n')[0]))
  bad += errors.length
}
console.log(`\nnodi renderizzati: ${root.querySelectorAll('*').length}`)
process.exit(bad ? 1 : 0)
