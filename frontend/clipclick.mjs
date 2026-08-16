/**
 * Seleziona ogni clip della timeline e controlla che l'interfaccia regga.
 *
 * Un'eccezione durante il render smonta l'albero React e lascia la pagina
 * vuota: dall'esterno sembra che l'editor si sia chiuso. Il progetto finto di
 * smoke.mjs ha due clip semplici e non basta — qui si usa lo stato vero,
 * salvato dal server, con tutti i tipi di clip e di effetto che ci finiscono.
 *
 *   npm run build && node clipclick.mjs [state.json]
 */
import { readFileSync, readdirSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'

/**
 * Progetto di prova. Serve che *alcune* clip stiano sotto la testina e altre
 * no: il riquadro di trasformazione compare solo sulle prime, e il difetto che
 * questo file sorveglia si manifesta nel passaggio fra i due casi.
 */
function progettoDiProva() {
  const clip = (id, start, dur, extra = {}) => ({
    id, type: 'media', name: `clip ${id}`, media: 'm1',
    start, end: start + dur, duration: dur, in: 0, speed: 1, reverse: false,
    enabled: true, fit: 'contain', color: 'black', fade_in: 0, fade_out: 0,
    transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 },
    audio: { gain_db: 0, mute: false, fade_in: 0, fade_out: 0, pan: 0 },
    effects: [], ...extra,
  })
  return {
    path: 'C:/tmp/p.json', revision: 'r1', presets: ['1080p'],
    transitions: ['dissolve', 'wipe_right', 'slide_left', 'iris'],
    system: { ffmpeg: 'finto', encoders: {}, hw: [] },
    effects: [{ name: 'color', kind: 'video', label: 'Correzione colore', desc: '', params: [
      { name: 'saturation', default: 1, type: 'number', min: 0, max: 3, animatable: true, choices: [], desc: '' }] }],
    project: {
      name: 'prova', duration: 20,
      settings: { resolution: '1920x1080', fps: 30, sample_rate: 48000, background: 'black' },
      media: [{ id: 'm1', name: 'clip.mp4', kind: 'video', duration: 30, resolution: '1920x1080', audio: true, folder: '', path: 'C:/tmp/clip.mp4' }],
      master: { loudnorm: { enabled: false, target_lufs: -14, measured: false }, effects: [], volume: 1 },
      tracks: [
        { id: 'V1', kind: 'video', name: 'V1', hidden: false, muted: false, volume: 1, clips: [
          clip('c1', 0, 3),            // sotto la testina (che parte da 0)
          clip('c2', 3, 3),            // fuori
          clip('c3', 6, 3, { transform: { x: 0, y: 0, rotation: 0, opacity: 1, scale: { kf: [{ t: 0, v: 1 }, { t: 2, v: 1.2 }] } } }),
          clip('c4', 9, 3, { fit: 'none' }),
          { id: 'c5', type: 'text', name: 'Titolo', start: 12, end: 14, duration: 2,
            speed: 1, reverse: false, enabled: true, fit: 'contain', color: 'black',
            fade_in: 0, fade_out: 0, transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 },
            audio: { gain_db: 0, mute: false, fade_in: 0, fade_out: 0, pan: 0 },
            text: { text: 'Ciao', font_size: 64, color: 'white', align: 'center', box: false }, effects: [] },
        ] },
        { id: 'A1', kind: 'audio', name: 'A1', hidden: false, muted: false, volume: 1, clips: [
          clip('c6', 0, 5), clip('c7', 5, 5),
        ] },
      ],
    },
  }
}

const statePath = process.argv[2]
const STATE = statePath ? JSON.parse(readFileSync(statePath, 'utf-8')) : progettoDiProva()

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:8765/', pretendToBeVisual: true,
})

const errori = []
dom.virtualConsole.on('jsdomError', (e) => errori.push(String(e)))
dom.window.addEventListener('error', (e) => errori.push(String(e.error || e.message)))

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

// jsdom non fa layout: ogni elemento misura zero. Il riquadro di trasformazione
// sull'anteprima si disegna solo se l'immagine ha una dimensione, quindi senza
// queste due righe quel pezzo di interfaccia non viene mai eseguito — ed e'
// proprio dove stava il difetto che svuotava la pagina.
Object.defineProperty(dom.window.HTMLElement.prototype, 'clientWidth', { get() { return 640 } })
Object.defineProperty(dom.window.HTMLElement.prototype, 'clientHeight', { get() { return 360 } })
dom.window.Element.prototype.getBoundingClientRect = function () {
  return { left: 0, top: 0, right: 640, bottom: 360, width: 640, height: 360, x: 0, y: 0 }
}
globalThis.localStorage = {
  // modalita' fedele: il riquadro di trasformazione vive solo li', ed e'
  // esattamente il pezzo che questo file sorveglia
  _d: { 'vedit.diretta': 'no' },
  getItem(k) { return this._d[k] ?? null }, setItem(k, v) { this._d[k] = String(v) },
}
globalThis.fetch = async (url) => {
  const path = String(url).split('?')[0]
  if (path.endsWith('/strip')) {
    return { ok: true, status: 200, json: async () => ({ url: '/api/file?path=s.jpg', tiles: 15, interval: 1, tile_width: 82, tile_height: 44 }) }
  }
  if (path.endsWith('/waveform')) {
    return { ok: true, status: 200, json: async () => ({ peaks: Array.from({ length: 600 }, (_, i) => Math.abs(Math.sin(i / 9))), duration: 30 }) }
  }
  const body = path === '/api/state' ? STATE
    : { result: {}, project: STATE.project, revision: STATE.revision }
  return { ok: true, status: 200, json: async () => body }
}

// L'anteprima scarica il fotogramma fuori dal DOM e lo mostra solo a
// caricamento finito; jsdom non scarica niente, quindi il `load` va simulato.
// Senza, l'immagine non compare, il riquadro di trasformazione non si misura e
// quel pezzo di interfaccia resta di nuovo non eseguito.
const creati = []
const creaOriginale = dom.window.document.createElement.bind(dom.window.document)
dom.window.document.createElement = (tag, ...rest) => {
  const el = creaOriginale(tag, ...rest)
  if (String(tag).toLowerCase() === 'img') creati.push(el)
  return el
}

const bundle = readdirSync('dist/assets').find((f) => f.endsWith('.js'))
if (!bundle) throw new Error('nessun bundle in dist/assets: lancia prima `npm run build`')
await import(pathToFileURL(`dist/assets/${bundle}`).href)
await new Promise((r) => setTimeout(r, 500))

for (const img of creati) img.dispatchEvent(new dom.window.Event('load'))
await new Promise((r) => setTimeout(r, 200))

const root = dom.window.document.getElementById('root')
const clips = [...root.querySelectorAll('.clip')]
console.log(`clip in timeline: ${clips.length}`)

let rotte = 0
for (const [i, clip] of clips.entries()) {
  const prima = errori.length
  clip.dispatchEvent(new dom.window.PointerEvent('pointerdown', { bubbles: true, clientX: 40, clientY: 40 }))
  dom.window.document.dispatchEvent(new dom.window.PointerEvent('pointerup', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 25))

  const vivo = root.querySelectorAll('*').length
  if (vivo < 50) {
    console.log(`  clip ${i} (${clip.textContent.slice(0, 24)}): interfaccia svuotata, ${vivo} nodi`)
    rotte++
    break   // l'albero e' smontato: da qui in poi non c'e' piu' niente da cliccare
  }
  if (errori.length > prima) {
    console.log(`  clip ${i} (${clip.textContent.slice(0, 24)}): ${errori[prima].split('\n')[0]}`)
    rotte++
  }
}

if (errori.length) {
  console.log('\nerrori raccolti:')
  for (const e of [...new Set(errori)].slice(0, 5)) console.log('  ' + e.split('\n').slice(0, 3).join('\n  '))
}
console.log(rotte ? `\n${rotte} clip rompono l'interfaccia` : '\nnessuna clip rompe l\'interfaccia')
process.exit(rotte || errori.length ? 1 : 0)
