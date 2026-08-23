import React, { useState } from 'react'
import Icon from './Icons.jsx'
import { Anim, Check, EffectParams, Num, Row, Select, Text } from './Params.jsx'

/** Pannello proprieta': clip selezionata, oppure progetto e master. */
export default function Inspector({
  project, effects, transitions, clip, playhead, run, setError, setBusy, onProva,
}) {
  const call = (op, args) => run(op, args).catch((e) => setError(e.message))
  return (
    <div className="inspector">
      {clip
        ? <ClipPanel clip={clip} effects={effects} transitions={transitions}
            project={project} playhead={playhead} call={call} onProva={onProva} />
        : <ProjectPanel project={project} effects={effects} call={call} setBusy={setBusy}
            setError={setError} onProva={onProva} />}
    </div>
  )
}

function ClipPanel({ clip, effects, transitions, project, playhead, call, onProva }) {
  const clipTime = Math.max(0, playhead - clip.start)
  const set = (patch) => call('set_clip', { clip_id: clip.id, ...patch })
  const tr = clip.transform || {}
  const au = clip.audio || {}

  return (
    <>
      <div className="section-title">{clip.type} · {clip.id}</div>

      <div className="group">
        <h4>clip</h4>
        <Row label="nome"><Text value={clip.name} onChange={(v) => set({ name: v })} /></Row>
        <Row label="inizio"><Num value={clip.start} step={0.05}
          onChange={(v) => call('move_clip', { clip_id: clip.id, start: v })} /></Row>
        <Row label="durata"><Num value={clip.duration} step={0.05} min={0.05}
          onChange={(v) => set({ duration: v })} /></Row>
        {clip.type === 'media' && (
          <Row label="attacco"><Num value={clip.in ?? 0} step={0.05} min={0}
            onChange={(v) => set({ in_: v })} /></Row>
        )}
        <Row label="attiva"><Check value={clip.enabled !== false} onChange={(v) => set({ enabled: v })} /></Row>
        {clip.type === 'media' && (
          <Row label="inquadra"><Select value={clip.fit || 'contain'} onChange={(v) => set({ fit: v })}
            options={['contain', 'cover', 'stretch', 'none']} /></Row>
        )}
        {clip.type === 'color' && (
          <Row label="colore"><Text value={clip.color} onChange={(v) => set({ color: v })} /></Row>
        )}
        <div className="hint">
          contain: tutto visibile · cover: riempie tagliando · none: dimensione originale
        </div>
      </div>

      {clip.type === 'media' && (
        <div className="group">
          <h4>velocita'</h4>
          <Row label="fattore">
            <Num value={clip.speed ?? 1} min={0.01} max={100} step={0.05}
              onChange={(v) => call('set_speed', { clip_id: clip.id, speed: v })} />
          </Row>
          <Row label="al contrario">
            <Check value={!!clip.reverse}
              onChange={(v) => call('set_reverse', { clip_id: clip.id, reverse: v })} />
          </Row>
          <div className="hint">2 = doppia velocita', 0.5 = slow motion</div>
        </div>
      )}

      <div className="group">
        <h4>dissolvenze</h4>
        <Row label="entrata"><Num value={clip.fade_in || 0} min={0} step={0.05}
          onChange={(v) => call('set_fades', { clip_id: clip.id, fade_in: v })} /></Row>
        <Row label="uscita"><Num value={clip.fade_out || 0} min={0} step={0.05}
          onChange={(v) => call('set_fades', { clip_id: clip.id, fade_out: v })} /></Row>
      </div>

      <TransitionPanel clip={clip} transitions={transitions} project={project} call={call} />

      <div className="group">
        <h4>
          posizione e scala
          <button className="icon sm azzera" title="Rimetti tutti i valori di partenza"
            onClick={() => call('set_transform',
              { clip_id: clip.id, x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 })}>
            <Icon name="annulla" size={12} />
          </button>
        </h4>
        {['x', 'y', 'scale', 'rotation', 'opacity'].map((k) => (
          <Anim key={k} label={k} value={tr[k] ?? (k === 'scale' || k === 'opacity' ? 1 : 0)}
            clipTime={clipTime} animatable def={k === 'scale' || k === 'opacity' ? 1 : 0}
            min={k === 'opacity' ? 0 : undefined} max={k === 'opacity' ? 1 : undefined}
            step={k === 'x' || k === 'y' || k === 'rotation' ? 1 : 0.05}
            onChange={(v) => call('set_transform', { clip_id: clip.id, [k]: v })} />
        ))}
        <div className="hint">x/y in pixel dal centro, y negativo verso l'alto</div>
      </div>

      {clip.type === 'text' && <TextPanel clip={clip} call={call} />}

      <div className="group">
        <h4>
          audio
          <button className="icon sm azzera" title="Rimetti tutti i valori di partenza"
            onClick={() => call('set_audio',
              { clip_id: clip.id, gain_db: 0, mute: false, pan: 0, fade_in: 0, fade_out: 0 })}>
            <Icon name="annulla" size={12} />
          </button>
        </h4>
        <Anim label="volume dB" value={au.gain_db ?? 0} clipTime={clipTime} animatable
          def={0} min={-60} max={24} step={0.5}
          onChange={(v) => call('set_audio', { clip_id: clip.id, gain_db: v })} />
        <Row label="muto"><Check value={!!au.mute}
          onChange={(v) => call('set_audio', { clip_id: clip.id, mute: v })} /></Row>
        <Row label="pan"><Num value={au.pan ?? 0} min={-1} max={1} step={0.1}
          onChange={(v) => call('set_audio', { clip_id: clip.id, pan: v })} /></Row>
        <Row label="fade in"><Num value={au.fade_in ?? 0} min={0} step={0.05}
          onChange={(v) => call('set_audio', { clip_id: clip.id, fade_in: v })} /></Row>
        <Row label="fade out"><Num value={au.fade_out ?? 0} min={0} step={0.05}
          onChange={(v) => call('set_audio', { clip_id: clip.id, fade_out: v })} /></Row>
      </div>

      <Effects target={clip.id} list={clip.effects || []} effects={effects}
        clipTime={clipTime} call={call} onProva={onProva} />
    </>
  )
}

const TR_NAMES = {
  dissolve: 'dissolvenza', iris: 'iris (cerchio)',
  wipe_right: 'tendina verso destra', wipe_left: 'tendina verso sinistra',
  wipe_down: 'tendina verso il basso', wipe_up: 'tendina verso l\'alto',
  slide_left: 'scorre a sinistra', slide_right: 'scorre a destra',
  slide_up: 'scorre in alto', slide_down: 'scorre in basso',
}

function TransitionPanel({ clip, transitions, project, call }) {
  const tr = clip.transition_out || {}
  const active = clip.transition?.type || (clip.fade_out > 0 ? 'dissolve' : '')
  const dur = clip.transition?.duration || clip.fade_out || 1.0

  // clip successiva sulla stessa traccia: serve per accostarla e sovrapporla
  const track = project?.tracks.find((t) => t.clips.some((c) => c.id === clip.id))
  const next = track?.clips
    .filter((c) => c.start >= clip.end - 1e-6 && c.id !== clip.id)
    .sort((a, b) => a.start - b.start)[0]

  const apply = (type, duration) => {
    if (next && Math.abs(next.start - clip.end) < 1e-3) {
      // clip attaccate: la transizione ha bisogno di sovrapposizione, le accosta
      call('crossfade', { clip_a: clip.id, clip_b: next.id, duration, type })
    } else {
      call('set_transition', { clip_id: clip.id, type, duration })
    }
  }

  return (
    <div className="group">
      <h4>transizione in uscita</h4>
      <Row label="tipo">
        <select value={active} onChange={(e) => {
          if (!e.target.value) { call('set_transition', { clip_id: clip.id, duration: 0 }); return }
          apply(e.target.value, dur)
        }}>
          <option value="">nessuna</option>
          {(transitions || []).map((t) => (
            <option key={t} value={t}>{TR_NAMES[t] || t}</option>
          ))}
        </select>
      </Row>
      {active && (
        <Row label="durata"><Num value={dur} min={0.05} max={clip.duration} step={0.1}
          onChange={(v) => apply(active, v)} /></Row>
      )}
      <div className="hint">
        {next
          ? 'la clip successiva viene accostata e sovrapposta della durata scelta'
          : 'nessuna clip dopo: la transizione scoprira\' lo sfondo'}
      </div>
    </div>
  )
}

function TextPanel({ clip, call }) {
  const t = clip.text || {}
  const set = (patch) => call('set_text', { clip_id: clip.id, ...patch })
  return (
    <div className="group">
      <h4>testo</h4>
      <div className="row wide">
        <textarea rows={3} value={t.text || ''} onChange={(e) => set({ text: e.target.value })} />
      </div>
      <Row label="corpo"><Num value={t.font_size ?? 64} min={8} max={400} step={2}
        onChange={(v) => set({ font_size: Math.round(v) })} /></Row>
      <Row label="colore"><Text value={t.color} onChange={(v) => set({ color: v })} /></Row>
      <Row label="allinea"><Select value={t.align || 'center'} onChange={(v) => set({ align: v })}
        options={['left', 'center', 'right']} /></Row>
      <Row label="riquadro"><Check value={!!t.box} onChange={(v) => set({ box: v })} /></Row>
      {t.box && (
        <>
          <Row label="col. riq."><Text value={t.box_color} onChange={(v) => set({ box_color: v })} /></Row>
          <Row label="opacita'"><Num value={t.box_opacity ?? 0.5} min={0} max={1} step={0.05}
            onChange={(v) => set({ box_opacity: v })} /></Row>
        </>
      )}
      <Row label="bordo"><Num value={t.border_width ?? 0} min={0} max={20} step={1}
        onChange={(v) => set({ border_width: Math.round(v) })} /></Row>
      <Row label="font"><Text value={t.font_file} placeholder="percorso .ttf (facoltativo)"
        onChange={(v) => set({ font_file: v })} /></Row>
    </div>
  )
}

function Effects({ target, list, effects, clipTime, call, onProva }) {
  const byName = Object.fromEntries(effects.map((e) => [e.name, e]))
  const args = (extra) => (target ? { clip_id: target, ...extra } : { clip_id: null, ...extra })

  /**
   * Il catalogo: un riquadro per effetto, con l'icona.
   *
   * Col mouse sopra, il monitor mostra come verrebbe senza applicarlo — il
   * fotogramma lo rende il server su una copia del progetto, quindi non c'e'
   * niente da annullare se poi non lo si vuole. Gli effetti audio non cambiano
   * un fotogramma fermo: per quelli non si prova niente e si dice perche'.
   */
  const Catalogo = ({ kind }) => (
    <div className="fxgrid">
      {effects.filter((e) => e.kind === kind).map((e) => (
        <button
          key={e.name} className="fxcard"
          title={`${e.label}${e.desc ? ` — ${e.desc}` : ''}`
            + (kind === 'video' ? '\nPassa sopra per vedere l\'anteprima.' : '')}
          onMouseEnter={() => kind === 'video' && onProva?.({ effect: e.name, label: e.label })}
          onMouseLeave={() => kind === 'video' && onProva?.(null)}
          onFocus={() => kind === 'video' && onProva?.({ effect: e.name, label: e.label })}
          onBlur={() => kind === 'video' && onProva?.(null)}
          onClick={() => { onProva?.(null); call('add_effect', args({ effect: e.name })) }}
        >
          <Icon name={e.name} size={20} />
          <span>{e.label}</span>
        </button>
      ))}
    </div>
  )

  return (
    <div className="group">
      <h4>effetti</h4>
      {list.map((e) => {
        const spec = byName[e.type]
        if (!spec) return null
        return (
          <div className="effect" key={e.i}>
            <header>
              <Check value={e.enabled !== false} title="Attiva o disattiva l'effetto"
                onChange={(v) => call('update_effect', args({ index: e.i, enabled: v }))} />
              <b>{spec.label}</b>
              <span className="spacer" />
              {/* l'ordine della catena cambia il risultato: denoise prima di
                  sharpen pulisce e poi incide, al contrario incide il rumore */}
              <button className="icon sm" title="Sposta prima nella catena"
                disabled={e.i === 0}
                onClick={() => call('move_effect', args({ index: e.i, to: e.i - 1 }))}>
                <Icon name="su" size={13} />
              </button>
              <button className="icon sm" title="Sposta dopo nella catena"
                disabled={e.i === list.length - 1}
                onClick={() => call('move_effect', args({ index: e.i, to: e.i + 1 }))}>
                <Icon name="giu" size={13} />
              </button>
              <button className="icon sm danger" title="Rimuovi l'effetto"
                onClick={() => call('remove_effect', args({ index: e.i }))}>
                <Icon name="chiudi" size={13} />
              </button>
            </header>
            <EffectParams spec={spec} params={e.params} clipTime={clipTime}
              onChange={(patch) => call('update_effect', args({ index: e.i, params: patch }))} />
            {spec.desc && <div className="hint">{spec.desc}</div>}
          </div>
        )
      })}
      <h4 className="fxtitolo">aggiungi effetto</h4>
      <div className="hint fxnota">video — passa sopra per vedere l'anteprima</div>
      <Catalogo kind="video" />
      <div className="hint fxnota">audio</div>
      <Catalogo kind="audio" />
    </div>
  )
}

function ProjectPanel({ project, effects, call, setBusy, setError, onProva }) {
  const s = project?.settings
  const ln = project?.master?.loudnorm || {}
  const [lufs, setLufs] = useState(ln.target_lufs ?? -14)
  if (!project) return <div className="group hint">Nessun progetto aperto.</div>

  const measure = async () => {
    setBusy('misuro il volume del mix…')
    try {
      const res = await fetch('/api/loudness', { method: 'POST' }).then((r) => r.json())
      await call('set_loudnorm', { enabled: true, target_lufs: lufs, measured: res.measured })
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  return (
    <>
      <div className="section-title">progetto</div>
      <div className="group">
        <h4>{project.name}</h4>
        <Row label="risoluzione"><Text value={s.resolution} onChange={(v) => {
          const [w, h] = v.split('x').map((n) => parseInt(n, 10))
          if (w > 0 && h > 0) call('set_settings', { width: w, height: h })
        }} /></Row>
        <Row label="fps"><Num value={s.fps} min={1} max={240} step={1}
          onChange={(v) => call('set_settings', { fps: v })} /></Row>
        <Row label="sfondo"><Text value={s.background} onChange={(v) => call('set_settings', { background: v })} /></Row>
        <div className="hint">durata timeline: {project.duration.toFixed(2)}s</div>
      </div>

      <div className="group">
        <h4>volume generale</h4>
        <Row label="normalizza"><Check value={!!ln.enabled}
          onChange={(v) => call('set_loudnorm', { enabled: v, target_lufs: lufs })} /></Row>
        <Row label="target LUFS"><Num value={lufs} min={-40} max={0} step={0.5} onChange={setLufs} /></Row>
        <button onClick={measure}>misura il mix e applica</button>
        <div className="hint">
          -14 YouTube/Spotify · -16 podcast · -23 TV. {ln.measured ? 'Misura presente.' : 'Nessuna misura: normalizzazione dinamica.'}
        </div>
      </div>

      <Effects target={null} list={project.master.effects.map((e, i) => ({ ...e, i }))}
        effects={effects} clipTime={0} call={call} onProva={onProva} />
    </>
  )
}
