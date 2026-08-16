import React, { useEffect, useRef, useState } from 'react'
import { api, chat as sendChat } from './api.js'
import Icon from './Icons.jsx'

const TOOL_LABEL = {
  project_info: 'guarda la timeline', import_media: 'importa file', add_clip: 'aggiunge una clip',
  add_text: 'aggiunge un titolo', split_clip: 'taglia', remove_clip: 'elimina una clip',
  move_clip: 'sposta una clip', trim_clip: 'ritaglia', set_speed: 'cambia velocita\'',
  set_fades: 'dissolvenze', crossfade: 'transizione', set_transition: 'transizione',
  apply_preset: 'applica un preset', add_effect: 'applica un effetto',
  set_transform: 'posizione e scala', set_audio: 'audio della clip', set_text: 'modifica il testo',
  add_track: 'aggiunge una traccia', close_gaps: 'chiude i buchi', undo: 'annulla',
}

/**
 * Chat con l'assistente. Gli strumenti che usa sono le stesse operazioni dei
 * pulsanti: quello che fa compare in timeline e si annulla con Ctrl+Z.
 */
export default function Chat({ available, onProject, setError }) {
  const [turns, setTurns] = useState([])   // {role, text, tools:[]}
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [turns, busy])

  if (!available?.ok) {
    return (
      <div className="chat">
        <div className="section-title">assistente</div>
        <div className="group hint">
          Chat non disponibile.<br /><br />
          {available?.motivo || 'nessuna credenziale Anthropic trovata.'}
          <br /><br />
          Imposta <b>ANTHROPIC_API_KEY</b> nell'ambiente e riavvia <code>vedit ui</code>.
        </div>
      </div>
    )
  }

  const send = async () => {
    const q = input.trim()
    if (!q || busy) return
    setInput('')
    setBusy(true)
    setTurns((t) => [...t, { role: 'user', text: q }, { role: 'assistant', text: '', tools: [] }])

    const patch = (fn) => setTurns((t) => {
      const out = [...t]
      out[out.length - 1] = fn(out[out.length - 1])
      return out
    })

    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await sendChat(q, (ev) => {
        if (ev.type === 'text') patch((m) => ({ ...m, text: m.text + ev.text }))
        else if (ev.type === 'thinking') patch((m) => ({ ...m, thinking: true }))
        else if (ev.type === 'tool') {
          patch((m) => ({ ...m, thinking: false, tools: [...m.tools, { name: ev.name, state: 'run' }] }))
        } else if (ev.type === 'tool_done' || ev.type === 'tool_error') {
          patch((m) => {
            const tools = [...m.tools]
            for (let i = tools.length - 1; i >= 0; i--) {
              if (tools[i].name === ev.name && tools[i].state === 'run') {
                tools[i] = { ...tools[i], state: ev.type === 'tool_done' ? 'ok' : 'err', message: ev.message }
                break
              }
            }
            return { ...m, tools }
          })
        } else if (ev.type === 'error') {
          patch((m) => ({ ...m, error: ev.message }))
        } else if (ev.type === 'end') {
          onProject(ev.project, ev.revision)
        }
      }, ctrl.signal)
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }

  const reset = () => {
    abortRef.current?.abort()
    api.chatReset().catch(() => {})
    setTurns([])
  }

  return (
    <div className="chat">
      <div className="section-title">
        assistente
        <span className="spacer" />
        <button className="icon sm" onClick={reset} title="Ricomincia la conversazione">
          <Icon name="cestino" size={14} />
        </button>
      </div>

      <div className="chatlog">
        {!turns.length && (
          <div className="chatempty">
            Chiedi una modifica in italiano:<br />
            <em>«togli i primi 2 secondi della prima clip»</em><br />
            <em>«metti una dissolvenza tra le due riprese»</em><br />
            <em>«rendi il video più cinematografico»</em><br />
            <em>«sposta la musica su una traccia sua»</em><br /><br />
            Modifica il progetto davvero. Quello che fa lo annulli con Ctrl+Z.
          </div>
        )}
        {turns.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === 'user' ? m.text : (
              <>
                {m.tools?.map((t, j) => (
                  <div key={j} className={`toolrow ${t.state}`}>
                    <Icon size={13} className={t.state === 'run' ? 'spin' : ''}
                      name={t.state === 'run' ? 'attesa' : t.state === 'ok' ? 'spunta' : 'chiudi'} />
                    {TOOL_LABEL[t.name] || t.name}
                    {t.message && <span className="hint"> — {t.message}</span>}
                  </div>
                ))}
                {m.thinking && !m.text && (
                  <div className="toolrow"><Icon size={13} name="attesa" className="spin" />sto ragionando…</div>
                )}
                {m.text}
                {m.error && <div className="chaterr">{m.error}</div>}
              </>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className="chatbar">
        <textarea
          rows={2} value={input} disabled={busy}
          placeholder={busy ? 'sto lavorando…' : 'chiedi una modifica…'}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
          }}
        />
        <button className="primary icon" disabled={busy || !input.trim()} onClick={send}
          title="Invia (Invio)"><Icon name="invia" /></button>
      </div>
    </div>
  )
}
