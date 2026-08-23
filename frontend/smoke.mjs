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
    // l'elenco completo del backend: serve a verificare che ogni effetto
    // abbia la sua icona, non solo quelli di comodo
    effects: [{"name": "color", "kind": "video", "label": "Correzione colore", "desc": "", "params": [{"name": "brightness", "default": 0.0, "type": "number", "min": -1, "max": 1, "animatable": false, "choices": [], "desc": ""}]}, {"name": "colorbalance", "kind": "video", "label": "Bilanciamento colore", "desc": "", "params": [{"name": "rs", "default": 0.0, "type": "number", "min": -1, "max": 1, "animatable": false, "choices": [], "desc": ""}]}, {"name": "temperature", "kind": "video", "label": "Temperatura colore", "desc": "", "params": [{"name": "temperature", "default": 6500, "type": "number", "min": 1000, "max": 40000, "animatable": false, "choices": [], "desc": ""}]}, {"name": "curves", "kind": "video", "label": "Curve", "desc": "", "params": [{"name": "preset", "default": "none", "type": "enum", "min": null, "max": null, "animatable": false, "choices": ["none", "color_negative", "cross_process", "darker", "increase_contrast", "lighter", "linear_contrast", "medium_contrast", "negative", "strong_contrast", "vintage"], "desc": ""}]}, {"name": "lut", "kind": "video", "label": "LUT 3D", "desc": "", "params": [{"name": "file", "default": "", "type": "file", "min": null, "max": null, "animatable": false, "choices": [], "desc": ""}]}, {"name": "blur", "kind": "video", "label": "Sfocatura", "desc": "", "params": [{"name": "sigma", "default": 8, "type": "number", "min": 0, "max": 100, "animatable": false, "choices": [], "desc": ""}]}, {"name": "sharpen", "kind": "video", "label": "Nitidezza", "desc": "", "params": [{"name": "amount", "default": 1.0, "type": "number", "min": -2, "max": 5, "animatable": false, "choices": [], "desc": ""}]}, {"name": "glow", "kind": "video", "label": "Glow", "desc": "", "params": [{"name": "sigma", "default": 12, "type": "number", "min": 1, "max": 60, "animatable": false, "choices": [], "desc": ""}]}, {"name": "vignette", "kind": "video", "label": "Vignettatura", "desc": "", "params": [{"name": "angle", "default": 0.8, "type": "number", "min": 0, "max": 1.57, "animatable": false, "choices": [], "desc": ""}]}, {"name": "grain", "kind": "video", "label": "Grana", "desc": "", "params": [{"name": "strength", "default": 12, "type": "number", "min": 0, "max": 100, "animatable": false, "choices": [], "desc": ""}]}, {"name": "denoise", "kind": "video", "label": "Riduzione rumore", "desc": "", "params": [{"name": "strength", "default": 4, "type": "number", "min": 0, "max": 20, "animatable": false, "choices": [], "desc": ""}]}, {"name": "chromakey", "kind": "video", "label": "Chroma key", "desc": "", "params": [{"name": "color", "default": "green", "type": "color", "min": null, "max": null, "animatable": false, "choices": [], "desc": ""}]}, {"name": "crop", "kind": "video", "label": "Ritaglio", "desc": "", "params": [{"name": "w", "default": 1920, "type": "number", "min": null, "max": null, "animatable": false, "choices": [], "desc": ""}]}, {"name": "pixelate", "kind": "video", "label": "Pixel", "desc": "", "params": [{"name": "size", "default": 16, "type": "number", "min": 2, "max": 200, "animatable": false, "choices": [], "desc": ""}]}, {"name": "mirror", "kind": "video", "label": "Specchia", "desc": "", "params": [{"name": "horizontal", "default": true, "type": "bool", "min": null, "max": null, "animatable": false, "choices": [], "desc": ""}]}, {"name": "stabilize", "kind": "video", "label": "Stabilizzazione", "desc": "", "params": [{"name": "smoothing", "default": 15, "type": "number", "min": 1, "max": 100, "animatable": false, "choices": [], "desc": ""}]}, {"name": "motionblur", "kind": "video", "label": "Motion blur", "desc": "", "params": [{"name": "mode", "default": "blend", "type": "enum", "min": null, "max": null, "animatable": false, "choices": ["blend", "interpolate"], "desc": ""}]}, {"name": "eq3", "kind": "audio", "label": "Equalizzatore", "desc": "", "params": [{"name": "bass", "default": 0, "type": "number", "min": -20, "max": 20, "animatable": false, "choices": [], "desc": ""}]}, {"name": "compressor", "kind": "audio", "label": "Compressore", "desc": "", "params": [{"name": "threshold", "default": -18, "type": "number", "min": -60, "max": 0, "animatable": false, "choices": [], "desc": ""}]}, {"name": "limiter", "kind": "audio", "label": "Limiter", "desc": "", "params": [{"name": "limit", "default": 0.95, "type": "number", "min": 0.1, "max": 1, "animatable": false, "choices": [], "desc": ""}]}, {"name": "adenoise", "kind": "audio", "label": "Riduzione rumore", "desc": "", "params": [{"name": "reduction", "default": 12, "type": "number", "min": 0.01, "max": 97, "animatable": false, "choices": [], "desc": ""}]}, {"name": "highpass", "kind": "audio", "label": "Passa-alto", "desc": "", "params": [{"name": "freq", "default": 80, "type": "number", "min": 10, "max": 2000, "animatable": false, "choices": [], "desc": ""}]}, {"name": "lowpass", "kind": "audio", "label": "Passa-basso", "desc": "", "params": [{"name": "freq", "default": 16000, "type": "number", "min": 500, "max": 20000, "animatable": false, "choices": [], "desc": ""}]}, {"name": "echo", "kind": "audio", "label": "Eco", "desc": "", "params": [{"name": "delay_ms", "default": 300, "type": "number", "min": 10, "max": 5000, "animatable": false, "choices": [], "desc": ""}]}, {"name": "reverb", "kind": "audio", "label": "Riverbero", "desc": "", "params": [{"name": "amount", "default": 0.3, "type": "number", "min": 0, "max": 0.9, "animatable": false, "choices": [], "desc": ""}]}, {"name": "pitch", "kind": "audio", "label": "Pitch", "desc": "", "params": [{"name": "semitones", "default": 0, "type": "number", "min": -24, "max": 24, "animatable": false, "choices": [], "desc": ""}]}, {"name": "gate", "kind": "audio", "label": "Noise gate", "desc": "", "params": [{"name": "threshold", "default": 0.02, "type": "number", "min": 0, "max": 1, "animatable": false, "choices": [], "desc": ""}]}, {"name": "dynnorm", "kind": "audio", "label": "Normalizzazione dinamica", "desc": "", "params": [{"name": "frame_ms", "default": 200, "type": "number", "min": 10, "max": 8000, "animatable": false, "choices": [], "desc": ""}]}],
    // la libreria vera del backend: serve a verificare che look,
    // catene audio e transizioni abbiano tutte la loro icona
    library: {"video": [{"id": "cinema_teal_orange", "name": "Cinema teal & orange", "group": "Colore", "desc": "Ombre fredde, incarnati caldi: il look da trailer."}, {"id": "bianco_e_nero", "name": "Bianco e nero", "group": "Colore", "desc": "Desaturazione totale con un po' di contrasto in piu'."}, {"id": "bn_contrastato", "name": "Bianco e nero contrastato", "group": "Colore", "desc": "Neri profondi, stile reportage."}, {"id": "caldo_tramonto", "name": "Caldo tramonto", "group": "Colore", "desc": "Temperatura verso l'arancio, luce di fine giornata."}, {"id": "freddo_notturno", "name": "Freddo notturno", "group": "Colore", "desc": "Blu, contrasto alto: notte o interni al neon."}, {"id": "sbiadito_pellicola", "name": "Sbiadito pellicola", "group": "Colore", "desc": "Neri alzati e grana: sembra girato su pellicola."}, {"id": "vhs", "name": "VHS anni '90", "group": "Stilizzati", "desc": "Grana grossa, colori slavati, bordi morbidi."}, {"id": "sogno", "name": "Sogno", "group": "Stilizzati", "desc": "Alone luminoso diffuso, ricordo o flashback."}, {"id": "nitido", "name": "Nitido", "group": "Ritocco", "desc": "Dettaglio in piu' senza toccare i colori."}, {"id": "pulisci_ripresa", "name": "Pulisci ripresa", "group": "Ritocco", "desc": "Riduzione rumore e recupero di contrasto: girato in poca luce."}, {"id": "vignettatura", "name": "Vignettatura", "group": "Ritocco", "desc": "Bordi scuriti, lo sguardo va al centro."}, {"id": "censura", "name": "Censura (pixel)", "group": "Stilizzati", "desc": "Mosaico su tutta l'immagine: volti o targhe."}, {"id": "specchia", "name": "Specchia", "group": "Ritocco", "desc": "Ribalta in orizzontale: risolve le riprese speculari."}, {"id": "stabilizza", "name": "Stabilizza", "group": "Ritocco", "desc": "Toglie il tremolio della camera a mano. Render piu' lento."}], "audio": [{"id": "voce_pulita", "name": "Voce pulita", "group": "Voce", "desc": "Taglia i bassi di rimbombo, comprime, riduce il fruscio."}, {"id": "voce_radio", "name": "Voce radiofonica", "group": "Voce", "desc": "Compressione decisa e presenza sui medi."}, {"id": "telefono", "name": "Telefono", "group": "Effetti", "desc": "Banda stretta: voce al telefono o alla radio."}, {"id": "sala_grande", "name": "Sala grande", "group": "Effetti", "desc": "Riverbero ampio."}, {"id": "eco", "name": "Eco", "group": "Effetti", "desc": "Ripetizione ritmica."}, {"id": "musica_sotto_voce", "name": "Musica sotto la voce", "group": "Musica", "desc": "Abbassa e scurisce la base perche' non copra il parlato."}, {"id": "volume_costante", "name": "Volume costante", "group": "Musica", "desc": "Normalizzazione dinamica: livella i punti troppo alti o bassi."}], "transitions": [{"id": "dissolve", "name": "Dissolvenza", "group": "Classica", "desc": "Una sfuma nell'altra.", "duration": 1.0}, {"id": "wipe_right", "name": "Tendina ▸", "group": "Tendina", "desc": "Scopre da sinistra a destra.", "duration": 0.8}, {"id": "wipe_left", "name": "Tendina ◂", "group": "Tendina", "desc": "Scopre da destra a sinistra.", "duration": 0.8}, {"id": "wipe_down", "name": "Tendina ▾", "group": "Tendina", "desc": "Scopre dall'alto.", "duration": 0.8}, {"id": "wipe_up", "name": "Tendina ▴", "group": "Tendina", "desc": "Scopre dal basso.", "duration": 0.8}, {"id": "slide_left", "name": "Scorri ◂", "group": "Scorrimento", "desc": "La clip esce verso sinistra.", "duration": 0.7}, {"id": "slide_right", "name": "Scorri ▸", "group": "Scorrimento", "desc": "La clip esce verso destra.", "duration": 0.7}, {"id": "slide_up", "name": "Scorri ▴", "group": "Scorrimento", "desc": "La clip esce verso l'alto.", "duration": 0.7}, {"id": "slide_down", "name": "Scorri ▾", "group": "Scorrimento", "desc": "La clip esce verso il basso.", "duration": 0.7}, {"id": "iris", "name": "Iris", "group": "Classica", "desc": "Cerchio che si apre dal centro.", "duration": 1.0}]},
    project: {
      name: 'demo', duration: 6,
      settings: { resolution: '1920x1080', fps: 30, sample_rate: 48000, background: 'black' },
      media: [
        { id: 'm1', name: 'clip.mp4', kind: 'video', duration: 6, resolution: '1920x1080', audio: true, folder: '', path: 'C:/tmp/clip.mp4' },
        { id: 'm2', name: 'musica.mp3', kind: 'audio', duration: 30, audio: true, folder: 'colonna sonora', path: 'C:/tmp/musica.mp3' },
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
  // si parte in "fedele": i controlli sull'anteprima renderizzata devono
  // vedere quel percorso. La diretta si prova dopo, con l'interruttore.
  _d: { 'vedit.diretta': 'no' },
  getItem(k) { return this._d[k] ?? null }, setItem(k, v) { this._d[k] = String(v) },
}

// jsdom non fa layout: senza una dimensione il canvas della diretta non si
// disegna e quel pezzo di interfaccia resta non eseguito
Object.defineProperty(dom.window.HTMLElement.prototype, 'clientWidth', { get() { return 640 } })
Object.defineProperty(dom.window.HTMLElement.prototype, 'clientHeight', { get() { return 360 } })

// jsdom non riproduce niente: senza questi, ogni play() finisce fra gli errori
for (const m of ['play', 'pause', 'load']) {
  dom.window.HTMLMediaElement.prototype[m] = function () { return Promise.resolve() }
}
const chiamate = []
globalThis.fetch = async (url, opts) => {
  chiamate.push({ url: String(url), method: opts?.method || 'GET' })
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

// L'anteprima scarica i fotogrammi fuori dal DOM: qui li si intercetta per
// controllare *quante* richieste partono davvero durante uno spostamento
// continuo della testina.
const fotogrammi = []
const creaOriginale = dom.window.document.createElement.bind(dom.window.document)
dom.window.document.createElement = (tag, ...rest) => {
  const el = creaOriginale(tag, ...rest)
  if (String(tag).toLowerCase() === 'img') fotogrammi.push(el)
  return el
}

const bundle = readdirSync('dist/assets').find((f) => f.endsWith('.js'))
if (!bundle) throw new Error('nessun bundle in dist/assets: lancia prima `npm run build`')

await import(pathToFileURL(`dist/assets/${bundle}`).href)

const root = dom.window.document.getElementById('root')

// Il primo montaggio passa da fetch e da un paio di giri di effetti: quanto ci
// metta dipende dalla macchina, quindi si aspetta la *condizione* invece di un
// tempo fisso. Un'attesa a orologio qui falliva sulle esecuzioni a freddo.
const attendi = async (che, quale, ms = 8000) => {
  const scadenza = Date.now() + ms
  for (;;) {
    const trovato = quale()
    if (trovato) return trovato
    if (Date.now() > scadenza) throw new Error(`atteso invano: ${che}`)
    await new Promise((r) => setTimeout(r, 25))
  }
}

// selezione di una clip: apre il pannello proprieta' con i keyframe
const clip = await attendi('clip in timeline', () => root.querySelector('.clip'))
const html = root.innerHTML
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
  // l'ordine della catena cambia il risultato: dalla UI si deve poter cambiare
  ['ordine effetti', afterClick.includes('Sposta prima nella catena')
    && afterClick.includes('Sposta dopo nella catena')],
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

// ---- anteprima durante uno spostamento continuo della testina --------------
// jsdom non scarica le immagini: il caricamento va simulato a mano.
const richieste = () => fotogrammi.filter((i) => (i.src || '').includes('/api/frame'))
const carica = async (img) => {
  img.dispatchEvent(new dom.window.Event('load'))
  await new Promise((r) => setTimeout(r, 60))
}

// primo fotogramma: finche' non e' pronto il monitor non mostra niente
const primo = richieste().at(-1)
if (primo) await carica(primo)
const srcIniziale = root.querySelector('.preview img')?.getAttribute('src') || ''

// Venti spostamenti di seguito, come un trascinamento della testina. Il server
// renderizza un fotogramma alla volta: una richiesta per evento riempiva la
// coda di lavoro gia' superato e l'anteprima arrivava decine di secondi dopo.
// Ne deve partire una sola, e il fotogramma a video non deve sparire nel
// frattempo — era quello che faceva diventare nero il monitor.
const prima = richieste().length
for (let i = 0; i < 20; i++) {
  dom.window.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
}
await new Promise((r) => setTimeout(r, 120))
const partite = richieste().length - prima
const srcDurante = root.querySelector('.preview img')?.getAttribute('src') || ''

// ---- anteprime nel pannello media -----------------------------------------
const righe = [...root.querySelectorAll('.medialist .media')]
const conFotogramma = righe.filter((r) => {
  const t = r.querySelector('.thumb')
  return t && (t.getAttribute('style') || '').includes('background-image')
})
const conOnda = righe.filter((r) => r.querySelector('.thumb.onda i'))

// ---- riproduzione in diretta -----------------------------------------------
// In diretta la composizione la fa il browser sui proxy: nessun fotogramma
// renderizzato, nessun segmento da preparare. E' il motivo per cui esiste.
const interruttore = [...root.querySelectorAll('.transport .modo')][0]
const modoPrima = interruttore?.textContent.trim()
interruttore?.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
await new Promise((r) => setTimeout(r, 200))

const primaDiretta = chiamate.length
const fotogrammiPrima = richieste().length
const livelli = [...root.querySelectorAll('.livecanvas .livelayer')]
const conSorgente = livelli.filter((l) => (l.getAttribute('src') || '').includes('/api/media/'))

// si lascia scorrere un momento: non deve partire nessun render
await new Promise((r) => setTimeout(r, 250))
const chiesteDopo = chiamate.slice(primaDiretta)
  .filter((c) => c.url.includes('/api/preview') || c.url.includes('/api/frame'))
const fotogrammiDopo = richieste().length - fotogrammiPrima

checks.push(
  ['diretta: l interruttore cambia modo', modoPrima === 'fedele'
    && interruttore?.textContent.trim() === 'diretta'],
  ['diretta: compone con i media veri', conSorgente.length > 0],
  ['diretta: non renderizza niente', chiesteDopo.length === 0 && fotogrammiDopo === 0],
)

// ---- catalogo degli effetti ------------------------------------------------
// Ogni effetto deve avere la sua icona: il catalogo e' a riquadri, e uno senza
// disegno diventa un rettangolo con solo il nome.
const schede = [...root.querySelectorAll('.fxcard')]
const attesi = FAKE['/api/state'].effects.length
const senzaIcona = schede.filter((c) => !c.querySelector('svg'))

// Col mouse sopra si vede l'anteprima, ma l'effetto non si applica: deve
// partire una richiesta di fotogramma con effect=, e nessuna operazione.
//
// useFrame tiene una sola richiesta in volo: se ne resta una aperta, l'hover
// aggiorna solo la destinazione e non ne fa partire un'altra. Qui si portano a
// termine tutte finche' non ne nascono di nuove, cosi' il test non dipende da
// quante ne erano rimaste appese dai controlli precedenti.
const concluse = new WeakSet()
const drena = async () => {
  for (let giro = 0; giro < 8; giro++) {
    let mosse = 0
    for (const img of richieste()) {
      if (concluse.has(img)) continue
      concluse.add(img)
      img.dispatchEvent(new dom.window.Event('load'))
      mosse++
    }
    await new Promise((r) => setTimeout(r, 40))
    if (!mosse) return
  }
}

await drena()
const primaHover = chiamate.length
const primaFotogrammi = richieste().length
const schedaVideo = schede[0]
schedaVideo.dispatchEvent(new dom.window.MouseEvent('mouseover', { bubbles: true }))
await new Promise((r) => setTimeout(r, 200))
const dopoHover = chiamate.slice(primaHover)
// il fotogramma si scarica creando un <img> fuori dal DOM, non con fetch:
// e' li' che va cercata la richiesta
const conEffetto = richieste().slice(primaFotogrammi)
  .some((i) => (i.src || '').includes('effect='))
const haApplicato = dopoHover.some((c) => c.url.includes('/api/op/add_effect'))

// ---- libreria: look, catene audio, transizioni -----------------------------
// Stessa regola del catalogo: ogni voce deve avere il suo disegno.
const lib = FAKE['/api/state'].library
const senzaIconaLib = []
let voci = 0
// il pannello sta dietro la scheda "libreria" del lato sinistro
const schedaLib = [...root.querySelectorAll('.tabs button')]
  .find((b) => b.textContent.trim() === 'libreria')
schedaLib?.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
await new Promise((r) => setTimeout(r, 60))
for (const [scheda, quante] of [['look', lib.video.length], ['audio', lib.audio.length],
  ['transizioni', lib.transitions.length]]) {
  const bottone = [...root.querySelectorAll('.tabs button')].find((b) => b.textContent.trim() === scheda)
  bottone?.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
  await new Promise((r) => setTimeout(r, 60))
  const righe = [...root.querySelectorAll('.preset')]
  voci += righe.length
  if (righe.length !== quante) senzaIconaLib.push(`${scheda}: ${righe.length} voci invece di ${quante}`)
  for (const r of righe) {
    if (!r.querySelector('.picon svg')) senzaIconaLib.push(`${scheda}: ${r.textContent.slice(0, 20)}`)
  }
}

checks.push(
  ["libreria: ogni voce ha l icona", senzaIconaLib.length === 0 && voci > 0],
  ['catalogo: un riquadro per effetto', schede.length === attesi],
  ['catalogo: ogni effetto ha l icona', senzaIcona.length === 0],
  ['catalogo: hover chiede l anteprima', conEffetto],
  ['catalogo: hover non applica l effetto', !haApplicato],
  ['anteprima: primo fotogramma mostrato', srcIniziale.includes('/api/frame')],
  ['anteprima: una richiesta alla volta', partite === 1],
  ['anteprima: il fotogramma resta a video', srcDurante === srcIniziale],
  ['bin: fotogramma sui video', conFotogramma.length === 1],
  ['bin: onda sugli audio', conOnda.length === 1],
)

// ---- campi del pannello proprieta' -----------------------------------------
// Scrivere non deve mandare niente al server: un'operazione per tasto premuto
// significa che la risposta riscrive il campo sotto le dita, e non si riesce a
// digitare "-", "0." o a cancellare una cifra per correggerla.
const campo = root.querySelector('.inspector .num input')
const scriviamo = chiamate.length
if (campo) {
  campo.dispatchEvent(new dom.window.FocusEvent('focusin', { bubbles: true }))
  // React tiene un proprio registro del valore: assegnare .value non gli fa
  // vedere niente. Il setter nativo e' il modo di simulare una digitazione.
  const scrivi = Object.getOwnPropertyDescriptor(
    dom.window.HTMLInputElement.prototype, 'value').set
  for (const testo of ['1', '12', '12.', '12.5']) {
    scrivi.call(campo, testo)
    campo.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    await new Promise((r) => setTimeout(r, 15))
  }
}
const durante = chiamate.slice(scriviamo).filter((c) => c.url.includes('/api/op/'))
const testoTenuto = campo?.value

// uscendo dal campo il valore si conferma, una volta sola
// React ascolta focusout (che risale), non blur
campo?.dispatchEvent(new dom.window.FocusEvent('focusout', { bubbles: true }))
await new Promise((r) => setTimeout(r, 60))
const dopoUscita = chiamate.slice(scriviamo).filter((c) => c.url.includes('/api/op/'))

const frecce = root.querySelectorAll('.inspector .numfrecce button')

checks.push(
  ['proprieta: scrivere non manda operazioni', !!campo && durante.length === 0],
  ['proprieta: il testo scritto resta', testoTenuto === '12.5'],
  ['proprieta: si conferma uscendo', dopoUscita.length === 1],
  ['proprieta: frecce su e giu', frecce.length >= 2],
  ['proprieta: tasto per rimettere il valore', !!root.querySelector('.inspector .reset')],
)

// ---- transizione lasciata sullo stacco -------------------------------------
// Come negli altri montaggi: si prende la transizione dalla libreria e la si
// lascia fra due clip, invece di selezionare una clip e applicargliela.
const stacchi = [...root.querySelectorAll('.giunzione')]
const primaStacco = chiamate.length
if (stacchi[0]) {
  const dati = new Map([['text/transition', 'dissolve'], ['text/duration', '0.8']])
  const dataTransfer = { types: [...dati.keys()], getData: (k) => dati.get(k) ?? '' }
  const ev = new dom.window.Event('drop', { bubbles: true, cancelable: true })
  ev.dataTransfer = dataTransfer
  stacchi[0].dispatchEvent(ev)
  await new Promise((r) => setTimeout(r, 80))
}
const applicata = chiamate.slice(primaStacco)
  .some((c) => c.url.includes('/api/op/crossfade') || c.url.includes('/api/op/set_transition'))

checks.push(
  ['stacco: bersaglio fra due clip attaccate', stacchi.length > 0],
  ['stacco: lasciarci una transizione la applica', applicata],
)

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
