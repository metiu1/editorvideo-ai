/**
 * Verifiche delle funzioni pure della UI (niente DOM).
 *
 *   node test-util.mjs
 */
import assert from 'node:assert/strict'
import { isKf, sampleKf, transformBox } from './src/util.js'

let ok = 0
const test = (name, fn) => {
  try { fn(); ok++; console.log('ok   ' + name) }
  catch (e) { console.log('FAIL ' + name + ': ' + e.message); process.exitCode = 1 }
}

test('keyframe interpolati come nel backend', () => {
  const v = { kf: [{ t: 0, v: 0 }, { t: 2, v: 10 }] }
  assert.equal(isKf(v), true)
  assert.equal(sampleKf(v, -1), 0)
  assert.equal(sampleKf(v, 1), 5)
  assert.equal(sampleKf(v, 9), 10)
  assert.equal(sampleKf(3.5, 1), 3.5)
})

test('easing: ease_in_out passa da meta a meta strada', () => {
  const v = { kf: [{ t: 0, v: 0, ease: 'ease_in_out' }, { t: 1, v: 1 }] }
  assert.equal(sampleKf(v, 0.5), 0.5)
  assert.ok(sampleKf(v, 0.2) < 0.2)
})

test('riquadro: clip a schermo intero copre tutta l anteprima', () => {
  const r = transformBox({
    box: { left: 10, top: 4, w: 960, h: 540 },
    canvas: { width: 1920, height: 1080 },
    native: { width: 1920, height: 1080 },
  })
  assert.equal(r.k, 0.5)
  assert.equal(r.left, 10)
  assert.equal(r.top, 4)
  assert.equal(r.width, 960)
  assert.equal(r.height, 540)
})

test('riquadro: scala e offset in pixel di progetto', () => {
  const r = transformBox({
    box: { left: 0, top: 0, w: 960, h: 540 },
    canvas: { width: 1920, height: 1080 },
    native: { width: 1920, height: 1080 },
    x: 480, y: -270, scale: 0.5,
  })
  // meta' dimensione, spostata di un quarto canvas: a schermo vale la meta'
  assert.equal(r.width, 480)
  assert.equal(r.left, 960 / 2 - 240 + 240)
  assert.equal(r.top, 540 / 2 - 135 - 135)
})

test('riquadro: sorgente piu piccola del canvas (fit=none)', () => {
  const r = transformBox({
    box: { left: 0, top: 0, w: 640, h: 360 },
    canvas: { width: 1280, height: 720 },
    native: { width: 200, height: 120 },
    scale: 2,
  })
  assert.equal(r.width, 200)   // 200 * 2 * 0.5
  assert.equal(r.height, 120)
})

console.log(`\n${ok} verifiche superate`)
