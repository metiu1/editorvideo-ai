import React, { useEffect, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import { EASINGS, isKf, sampleKf } from './util.js'

/**
 * Riga del pannello proprieta'.
 *
 * ``onReset`` mette il pulsante per rimettere il valore di partenza: senza, per
 * disfare una prova bisogna ricordarsi il numero di prima e riscriverlo.
 */
export function Row({ label, children, extra, onReset, modificato }) {
  return (
    <div className="row">
      <label>{label}</label>
      <div>{children}</div>
      <div className="rowextra">
        {extra}
        {onReset && (
          <button className={`icon sm reset ${modificato ? 'on' : ''}`} onClick={onReset}
            disabled={!modificato} title="Rimetti il valore di partenza">
            <Icon name="annulla" size={12} />
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Campo numerico con le frecce.
 *
 * Mentre si scrive il campo e' *suo*: il valore che arriva da fuori non lo
 * tocca. Prima invece ogni tasto premuto mandava un'operazione al server, e la
 * risposta riscriveva il campo sotto le dita — impossibile digitare "-", "0.",
 * o cancellare una cifra per correggerla, perche' il valore tornava indietro.
 * Si conferma uscendo dal campo o con Invio, si annulla con Esc.
 */
export function Num({ value, onChange, min, max, step = 0.01, disabled }) {
  const [bozza, setBozza] = useState(null)      // testo in scrittura, null = non attivo
  const inputRef = useRef(null)
  const mostrato = bozza ?? String(round(value))

  const limita = (v) => {
    if (min != null && v < min) return min
    if (max != null && v > max) return max
    return v
  }

  const conferma = () => {
    if (bozza === null) return
    const v = parseFloat(bozza)
    setBozza(null)
    if (!Number.isNaN(v) && Math.abs(v - value) > 1e-9) onChange(round(limita(v)))
  }

  /** Le frecce agiscono sul valore vero, anche se c'e' una bozza a metа'. */
  const passo = (segno) => {
    const base = bozza !== null && !Number.isNaN(parseFloat(bozza)) ? parseFloat(bozza) : Number(value) || 0
    setBozza(null)
    onChange(round(limita(base + segno * step)))
  }

  // ripetizione tenendo premuto, come nei campi numerici di sistema
  const ripeti = (segno) => {
    passo(segno)
    let via = setTimeout(function corri() {
      passo(segno)
      via = setTimeout(corri, 60)
    }, 400)
    const stop = () => { clearTimeout(via); window.removeEventListener('pointerup', stop) }
    window.addEventListener('pointerup', stop)
  }

  return (
    <div className="num">
      <input
        ref={inputRef} type="text" inputMode="decimal" value={mostrato} disabled={disabled}
        onChange={(e) => setBozza(e.target.value)}
        onBlur={conferma}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { conferma(); e.target.blur() }
          else if (e.key === 'Escape') { setBozza(null); e.target.blur() }
          else if (e.key === 'ArrowUp') { e.preventDefault(); passo(1) }
          else if (e.key === 'ArrowDown') { e.preventDefault(); passo(-1) }
        }}
      />
      <div className="numfrecce">
        <button tabIndex={-1} disabled={disabled} title="Aumenta"
          onPointerDown={(e) => { e.preventDefault(); ripeti(1) }}>
          <Icon name="su" size={10} />
        </button>
        <button tabIndex={-1} disabled={disabled} title="Diminuisci"
          onPointerDown={(e) => { e.preventDefault(); ripeti(-1) }}>
          <Icon name="giu" size={10} />
        </button>
      </div>
    </div>
  )
}

export function Check({ value, onChange, title }) {
  return <input type="checkbox" checked={!!value} title={title}
    onChange={(e) => onChange(e.target.checked)} />
}

/**
 * Campo di testo. Stessa regola del numerico: si conferma uscendo o con Invio.
 *
 * Un'operazione per ogni tasto premuto voleva dire un giro completo al server
 * per lettera, e il nome che si stava scrivendo tornava indietro a meta' parola.
 */
export function Text({ value, onChange, placeholder }) {
  const [bozza, setBozza] = useState(null)
  const conferma = () => {
    if (bozza === null) return
    const v = bozza
    setBozza(null)
    if (v !== (value ?? '')) onChange(v)
  }
  return (
    <input
      value={bozza ?? value ?? ''} placeholder={placeholder}
      onChange={(e) => setBozza(e.target.value)}
      onBlur={conferma}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { conferma(); e.target.blur() }
        else if (e.key === 'Escape') { setBozza(null); e.target.blur() }
      }}
    />
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
export function Anim({ label, value, onChange, min, max, step, animatable, clipTime = 0, def }) {
  const animated = isKf(value)
  const current = animated ? sampleKf(value, clipTime) : (Number(value) || 0)
  // "modificato" guarda il valore vero, non quello campionato: un parametro
  // animato e' modificato anche se in questo istante vale come il default
  const modificato = def != null && (animated || Math.abs((Number(value) || 0) - def) > 1e-9)

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
        modificato={modificato}
        onReset={def != null ? () => onChange(def) : undefined}
        extra={animatable && (
          <button className={`icon sm kf-btn ${animated ? 'on' : ''}`} onClick={toggle}
            title={animated ? 'Torna a un valore fisso' : 'Anima con i keyframe'}>
            <Icon name="keyframe" size={13} />
          </button>
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
              {/* stessi campi del resto: si confermano uscendo, non a ogni tasto */}
              <Num value={k.t} step={0.05} min={0} onChange={(v) => setKey(i, { t: v })} />
              <Num value={k.v} step={step || 0.01} min={min} max={max}
                onChange={(v) => setKey(i, { v })} />
              <select value={k.ease || 'linear'} title="easing verso il prossimo"
                onChange={(e) => setKey(i, { ease: e.target.value })}>
                {EASINGS.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
              <button className="icon sm danger" title="Rimuovi il keyframe"
                disabled={value.kf.length <= 1}
                onClick={() => onChange({ kf: value.kf.filter((_, j) => j !== i) })}>
                <Icon name="chiudi" size={12} />
              </button>
            </div>
          ))}
          <button style={{ width: '100%', height: 22, fontSize: 11 }} onClick={addKey}>
            <Icon name="piu" size={12} />keyframe alla testina
          </button>
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
    // il valore di partenza lo dichiara gia' il catalogo del backend: il tasto
    // per rimetterlo non ha bisogno di una tabella a parte
    const reset = { onReset: () => set(p.default), modificato: value !== p.default }
    if (p.type === 'bool') return <Row key={p.name} label={p.name} {...reset}><Check value={value} onChange={set} /></Row>
    if (p.type === 'enum') return <Row key={p.name} label={p.name} {...reset}><Select value={value} onChange={set} options={p.choices} /></Row>
    if (p.type === 'string' || p.type === 'color' || p.type === 'file') {
      return <Row key={p.name} label={p.name} {...reset}><Text value={value} onChange={set} placeholder={p.desc} /></Row>
    }
    return (
      <Anim key={p.name} label={p.name} value={value} onChange={set} clipTime={clipTime}
        min={p.min} max={p.max} animatable={p.animatable} def={p.default}
        step={p.max != null && p.max <= 4 ? 0.05 : 1} />
    )
  })
}

const round = (v) => Math.round((Number(v) || 0) * 1000) / 1000
