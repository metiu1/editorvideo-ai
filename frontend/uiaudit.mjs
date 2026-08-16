/**
 * Controlli di interfaccia sul bundle compilato.
 *
 * Non verifica che "compili": verifica le cose che rendono un'interfaccia
 * scomoda o poco professionale e che nessun test di logica intercetta —
 * comandi senza nome, finestre di sistema al posto delle proprie, emoji usate
 * come icone, testo troppo poco contrastato, fuoco che scappa dalle modali.
 *
 *   npm run build && node uiaudit.mjs
 */
import { readFileSync, readdirSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { JSDOM } from 'jsdom'

const FAKE_PROJECT = {
  name: 'demo', duration: 13,
  settings: { resolution: '1920x1080', fps: 30, sample_rate: 48000, background: 'black' },
  media: [
    { id: 'm1', name: 'ripresa.mp4', kind: 'video', duration: 6, resolution: '1920x1080', audio: true, folder: '' },
    { id: 'm2', name: 'musica.mp3', kind: 'audio', duration: 30, audio: true, folder: 'colonna sonora' },
  ],
  master: { loudnorm: { enabled: false, target_lufs: -14, measured: false }, effects: [], volume: 1 },
  tracks: [
    { id: 'V1', kind: 'video', name: 'riprese', hidden: false, muted: false, locked: false, solo: false, volume: 1, clips: [
      { id: 'c1', type: 'media', name: 'ripresa.mp4', start: 0, end: 4, duration: 4, media: 'm1',
        in: 0, speed: 1, reverse: false, enabled: true, fit: 'contain', color: 'black',
        fade_in: 0.5, fade_out: 0, transition: { type: 'wipe_right', duration: 0.8 },
        transform: { x: 0, y: 0, scale: 1, rotation: 0, opacity: { kf: [{ t: 0, v: 0 }, { t: 1, v: 1 }] } },
        audio: { gain_db: -3, mute: false, fade_in: 0, fade_out: 0, pan: 0 },
        effects: [{ i: 0, type: 'color', params: { saturation: 1.2 }, enabled: true }] },
    ] },
    { id: 'V2', kind: 'video', name: 'titoli', hidden: true, muted: false, locked: true, solo: false, volume: 1, clips: [] },
    { id: 'A1', kind: 'audio', name: 'musica', hidden: false, muted: false, locked: false, solo: true, volume: .8, clips: [] },
  ],
}

const STATE = {
  path: 'C:/tmp/p.json', revision: 'r1', presets: ['1080p', 'vertical'],
  transitions: ['dissolve', 'wipe_right'],
  effects: [{ name: 'color', kind: 'video', label: 'Correzione colore', desc: '', params: [
    { name: 'saturation', default: 1, type: 'number', min: 0, max: 3, animatable: true, choices: [], desc: '' }] }],
  library: {
    video: [{ id: 'vhs', name: "VHS anni '90", group: 'Stilizzati', desc: 'Grana grossa.' }],
    audio: [{ id: 'voce_pulita', name: 'Voce pulita', group: 'Voce', desc: 'Comprime.' }],
    transitions: [{ id: 'dissolve', name: 'Dissolvenza', group: 'Classica', desc: '', duration: 1 }],
  },
  chat: { ok: true, model: 'claude-opus-5' },
  system: { ffmpeg: 'finto', encoders: {}, hw: [] },
  project: FAKE_PROJECT,
}

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:8760/', pretendToBeVisual: true,
})
const jsdomErrors = []
dom.virtualConsole.on('jsdomError', (e) => jsdomErrors.push(String(e).split('\n')[0]))
const consoleErrors = []
dom.virtualConsole.on('error', (m) => consoleErrors.push(String(m)))

for (const k of ['window', 'document', 'HTMLElement', 'HTMLMediaElement', 'Node', 'Element',
  'Event', 'CustomEvent', 'MouseEvent', 'KeyboardEvent', 'PointerEvent', 'getComputedStyle',
  'requestAnimationFrame', 'cancelAnimationFrame', 'DOMParser', 'MutationObserver',
  'DocumentFragment', 'Text', 'Range', 'CSS', 'SVGElement']) {
  Object.defineProperty(globalThis, k, { value: dom.window[k], configurable: true, writable: true })
}
for (const k of ['navigator', 'location']) {
  Object.defineProperty(globalThis, k, { value: dom.window[k], configurable: true })
}
globalThis.self = dom.window
globalThis.WebSocket = class { close() {} }
globalThis.ResizeObserver = class { observe() {} disconnect() {} }
globalThis.localStorage = { _d: {}, getItem(k) { return this._d[k] ?? null }, setItem(k, v) { this._d[k] = String(v) } }
dom.window.HTMLMediaElement.prototype.play = () => Promise.resolve()
dom.window.HTMLMediaElement.prototype.pause = () => {}

// finestre di sistema: se qualcuno le chiama lo si scopre qui
const nativeDialogs = []
for (const fn of ['alert', 'confirm', 'prompt']) {
  dom.window[fn] = (...a) => { nativeDialogs.push(`${fn}(${a[0] ?? ''})`); return fn === 'confirm' ? true : '' }
  globalThis[fn] = dom.window[fn]
}

globalThis.fetch = async (url) => {
  const path = String(url).split('?')[0]
  if (path.endsWith('/strip')) return { ok: true, status: 200, json: async () => ({}) }
  if (path.endsWith('/waveform')) return { ok: true, status: 200, json: async () => ({ peaks: [], duration: 30 }) }
  if (path === '/api/browse') {
    return { ok: true, status: 200, json: async () => ({ path: 'C:/', parent: null, dirs: [{ name: 'video', path: 'C:/video' }], files: [{ name: 'a.mp4', path: 'C:/a.mp4', size: 1e6 }] }) }
  }
  const body = path === '/api/state' ? STATE : { result: { id: 'c1' }, project: FAKE_PROJECT, revision: 'r1' }
  return { ok: true, status: 200, json: async () => body }
}

const bundle = readdirSync('dist/assets').find((f) => f.endsWith('.js'))
await import(pathToFileURL(`dist/assets/${bundle}`).href)
await new Promise((r) => setTimeout(r, 450))

const doc = dom.window.document
const root = doc.getElementById('root')
const click = (el) => el?.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }))
const key = (k, opts = {}) => dom.window.dispatchEvent(
  new dom.window.KeyboardEvent('keydown', { key: k, bubbles: true, ...opts }))

const problems = []
const fail = (area, msg) => problems.push(`${area}: ${msg}`)

// --------------------------------------------------------------- 1. emoji
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u
const visitAll = () => [...root.querySelectorAll('*')]
const emojiNodes = visitAll().filter((el) =>
  [...el.childNodes].some((n) => n.nodeType === 3 && EMOJI.test(n.textContent)))
if (emojiNodes.length) {
  fail('icone', `${emojiNodes.length} emoji usate come icone: ` +
    emojiNodes.slice(0, 5).map((e) => JSON.stringify(e.textContent.trim().slice(0, 12))).join(', '))
}

// ------------------------------------------- 2. comandi senza nome leggibile
const unnamed = [...root.querySelectorAll('button')].filter((b) => {
  const text = b.textContent.trim()
  return !text && !b.getAttribute('title') && !b.getAttribute('aria-label')
})
if (unnamed.length) fail('accessibilita', `${unnamed.length} pulsanti senza testo ne' title`)

// pulsanti di sole icone: il title e' l'unica spiegazione, deve esserci
const iconOnly = [...root.querySelectorAll('button')].filter(
  (b) => b.querySelector('svg') && !b.textContent.trim())
const iconNoTitle = iconOnly.filter((b) => !b.getAttribute('title'))
if (iconNoTitle.length) fail('accessibilita', `${iconNoTitle.length} pulsanti-icona senza title`)

// --------------------------------------------------- 3. comandi annidati
const nested = [...root.querySelectorAll('button button, button a, a button')]
if (nested.length) fail('struttura', `${nested.length} comandi annidati dentro altri comandi`)

// ------------------------------------------------ 4. campi senza etichetta
// un'etichetta visibile accanto al campo conta quanto un title
const labelled = (el) => {
  const row = el.closest('.row')
  return !!(row && row.querySelector('label')?.textContent.trim())
}
const orphanInputs = [...root.querySelectorAll('input, select, textarea')].filter((el) => {
  if (el.getAttribute('title') || el.getAttribute('aria-label')) return false
  if (labelled(el)) return false
  if (el.type === 'range' || el.type === 'checkbox') return true
  return !el.getAttribute('placeholder')
})
if (orphanInputs.length) {
  fail('accessibilita', `${orphanInputs.length} campi senza etichetta ne' descrizione: ` +
    orphanInputs.map((e) => `<${e.tagName.toLowerCase()} type=${e.type} class="${e.className}">`).join(' '))
}

// ------------------------------------------------------- 5. interazioni
const clip = root.querySelector('.clip')
clip?.dispatchEvent(new dom.window.PointerEvent('pointerdown', { bubbles: true, clientX: 40, clientY: 40 }))
doc.dispatchEvent(new dom.window.PointerEvent('pointerup', { bubbles: true }))
await new Promise((r) => setTimeout(r, 120))
if (!root.querySelector('.clip.sel')) fail('timeline', 'la clip selezionata non si distingue')

// rinomina traccia: deve essere in linea, non una finestra di sistema
const tname = root.querySelector('.track-head .tname')
tname?.dispatchEvent(new dom.window.MouseEvent('dblclick', { bubbles: true }))
await new Promise((r) => setTimeout(r, 100))
if (!root.querySelector('.track-head input.rename')) fail('tracce', 'la rinomina non apre un campo in linea')
key('Escape')

// elimina traccia con clip: deve chiedere conferma con una finestra propria.
// Va scelta una traccia non bloccata e non vuota: sulle bloccate il comando e'
// disattivato apposta, e su una vuota la conferma sarebbe solo un intralcio.
const trackWithClips = [...root.querySelectorAll('.track')]
  .find((t) => t.querySelector('.clip') && !t.classList.contains('locked'))
const delBtn = [...(trackWithClips?.querySelectorAll('.track-head button') || [])]
  .find((b) => (b.getAttribute('title') || '').includes('Elimina la traccia'))
if (!delBtn) fail('tracce', 'nessun comando di eliminazione sulla traccia piena')
if (delBtn?.disabled) fail('tracce', 'eliminazione disattivata su una traccia non bloccata')
click(delBtn)
await new Promise((r) => setTimeout(r, 120))
const dialog = root.querySelector('.dialog[role=dialog]')
if (!dialog) fail('tracce', 'eliminare una traccia piena non chiede conferma')

// --------------------------------------------------------- 6. modali
if (dialog) {
  const inside = dialog.contains(doc.activeElement)
  if (!inside) fail('modale', 'il fuoco non entra nella finestra all\'apertura')
  key('Escape')
  await new Promise((r) => setTimeout(r, 100))
  if (root.querySelector('.dialog[role=dialog]')) fail('modale', 'Esc non chiude la finestra')
}

// --------------------------------------- 7. nessuna finestra di sistema
if (nativeDialogs.length) {
  fail('finestre', `usa i dialoghi del browser: ${nativeDialogs.join(', ')}`)
}

// ------------------------------------------------------ 8. contrasto
const css = readFileSync(`dist/assets/${readdirSync('dist/assets').find((f) => f.endsWith('.css'))}`, 'utf8')
const varOf = (n) => (css.match(new RegExp(`--${n}:\\s*(#[0-9a-fA-F]{3,8})`)) || [])[1]
const lum = (hex) => {
  const v = hex.replace('#', '')
  const p = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4))
  return .2126 * p[0] + .7152 * p[1] + .0722 * p[2]
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m)
  return (x + .05) / (y + .05)
}
const pairs = [
  ['text', 'panel', 4.5, 'testo principale'],
  ['text', 'bg', 4.5, 'testo sul fondo'],
  ['dim', 'panel', 4.5, 'testo secondario'],
  ['faint', 'panel', 3, 'etichette minori'],
  ['accent', 'panel', 3, 'accento'],
  ['danger', 'panel', 3, 'errori'],
  ['ok', 'panel', 3, 'conferme'],
]
const contrasts = []
for (const [fg, bg, min, label] of pairs) {
  const a = varOf(fg), b = varOf(bg)
  if (!a || !b) { fail('contrasto', `variabile mancante: --${fg} o --${bg}`); continue }
  const r = ratio(a, b)
  contrasts.push(`  ${label.padEnd(20)} ${r.toFixed(2)}:1 (min ${min})`)
  if (r < min) fail('contrasto', `${label} a ${r.toFixed(2)}:1, sotto il minimo ${min}`)
}

// ------------------------------- 9. la testata traccia ci sta all'altezza minima
// jsdom non calcola il layout: si verifica l'invariante sui numeri, cioe' che
// l'altezza minima consentita dal cursore basti per le due righe di comandi.
const js = readFileSync(`dist/assets/${bundle}`, 'utf8')
const minH = Number((js.match(/min:"44"|min:"(\d+)",max:"140"/) || [])[1] || 44)
const btnH = Number((css.match(/\.track-head button\{width:\d+px;height:(\d+)px/) || [])[1] || 18)
const rowGap = 3, pad = 2
const needed = btnH * 2 + rowGap + pad
if (minH < needed) {
  fail('tracce', `all'altezza minima (${minH}px) la testata ne chiede ${needed}px: i comandi escono`)
}

// ------------------------------------------------------------- referto
console.log('contrasto testo/sfondo:')
console.log(contrasts.join('\n'))
console.log(`\nelementi renderizzati : ${visitAll().length}`)
console.log(`pulsanti              : ${root.querySelectorAll('button').length} (${iconOnly.length} di sola icona)`)
console.log(`icone svg             : ${root.querySelectorAll('svg.ico').length}`)
console.log(`errori jsdom/console  : ${jsdomErrors.length + consoleErrors.length}`)
for (const e of [...jsdomErrors, ...consoleErrors].slice(0, 3)) console.log('   ' + e.slice(0, 160))

console.log('')
if (problems.length) {
  console.log(`${problems.length} problemi:`)
  problems.forEach((p) => console.log('  FAIL ' + p))
} else {
  console.log('nessun problema di interfaccia rilevato')
}
process.exit(problems.length + jsdomErrors.length ? 1 : 0)
