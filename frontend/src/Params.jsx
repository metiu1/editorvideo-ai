import React from 'react'
import { EASINGS, isKf, sampleKf } from './util.js'

export function Row({ label, children, extra }) {
  return (
    <div className="row">
      <label>{label}</label>
      <div>{children}</div>
      <div>{extra}</div>
    </div>
  )
}

export function Num({ value, onChange, min, max, step = 0.01, disabled }) {
  return (
    <input
      type="number" value={round(value)} disabled={disabled}
      min={min ?? undefined} max={max ?? undefined} step={step}
      onChange={(e) => {
        const v = parseFloat(e.target.value)
        if (!Number.isNaN(v)) onChange(v)
      }}
    />
  )
}

export function Check({ value, onChange }) {
  return <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
}

export function Text({ value, onChange, placeholder }) {
  return (
    <input value={value ?? ''} placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)} />
  )
}

export function Select({ value, onChange, options }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  )
}

/**
 * Parametro numerico che puo' essere animato.
 * ``clipTime`` e' il tempo della testina relativo all'inizio della clip:
 * e' il riferimento dei keyframe, esattamente come nel backend.
 */
export function Anim({ label, value, onChange, min, max, step, animatable, clipTime = 0 }) {
  const animated = isKf(value)
  const current = animated ? sampleKf(value, clipTime) : (Number(value) || 0)

  const toggle = () => {
    if (animated) onChange(round(current))
    else onChange({ kf: [{ t: round(clipTime), v: round(current), ease: 'linear' }] })
  }

  const setKey = (i, patch) => {
    const kf = value.kf.map((k, j) => (j === i ? { ...k, ...patch } : k))
    onChange({ kf })
  }

  const addKey = () => {
    const t = round(clipTime)
    const kf = value.kf.filter((k) => Math.abs(k.t - t) > 1e-3)
    kf.push({ t, v: round(current), ease: 'linear' })
    kf.sort((a, b) => a.t - b.t)
    onChange({ kf })
  }

  return (
    <>
      <Row
        label={label}
        extra={animatable && (
          <button className={`kf-btn ${animated ? 'on' : ''}`} onClick={toggle}
            title={animated ? 'torna a valore fisso' : 'anima con keyframe'}>◆</button>
        )}
      >
        {animated
          ? <input value={`${round(current)} (animato)`} readOnly />
          : <Num value={current} onChange={onChange} min={min} max={max} step={step} />}
      </Row>

      {animated && (
        <div className="kf-list">
          {value.kf.map((k, i) => (
            <div className="kf-row" key={i}>
              <input type="number" step="0.05" value={round(k.t)} title="tempo (s dalla clip)"
                onChange={(e) => setKey(i, { t: parseFloat(e.target.value) || 0 })} />
              <input type="number" step={step || 0.01} value={round(k.v)} title="valore"
                onChange={(e) => setKey(i, { v: parseFloat(e.target.value) || 0 })} />
              <select value={k.ease || 'linear'} title="easing verso il prossimo"
                onChange={(e) => setKey(i, { ease: e.target.value })}>
                {EASINGS.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
              <button className="kf-btn" title="rimuovi"
                disabled={value.kf.length <= 1}
                onClick={() => onChange({ kf: value.kf.filter((_, j) => j !== i) })}>✕</button>
            </div>
          ))}
          <button className="kf-btn" onClick={addKey}>+ keyframe alla testina</button>
        </div>
      )}
    </>
  )
}

/** Controlli di un effetto, generati dal catalogo del backend. */
export function EffectParams({ spec, params, onChange, clipTime }) {
  return spec.params.map((p) => {
    const value = params?.[p.name] ?? p.default
    const set = (v) => onChange({ [p.name]: v })
    if (p.type === 'bool') return <Row key={p.name} label={p.name}><Check value={value} onChange={set} /></Row>
    if (p.type === 'enum') return <Row key={p.name} label={p.name}><Select value={value} onChange={set} options={p.choices} /></Row>
    if (p.type === 'string' || p.type === 'color' || p.type === 'file') {
      return <Row key={p.name} label={p.name}><Text value={value} onChange={set} placeholder={p.desc} /></Row>
    }
    return (
      <Anim key={p.name} label={p.name} value={value} onChange={set} clipTime={clipTime}
        min={p.min} max={p.max} animatable={p.animatable}
        step={p.max != null && p.max <= 4 ? 0.05 : 1} />
    )
  })
}

const round = (v) => Math.round((Number(v) || 0) * 1000) / 1000
